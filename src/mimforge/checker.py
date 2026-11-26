"""Muse Spark double-checker: an advisory second opinion.

Prince's direction (2026-11-26): when the machine is online, Muse
Spark double-checks what the app built at each major step. The
binding rule comes from his own products: the LOCAL result is
always the official one. The checker can agree, or flag plain-words
concerns for the teacher to see; it can never change, block, or
override anything, and it never touches the safety kernel. A flag
is stored with the project record; the teacher decides.

What travels: a STRUCTURED summary of the step's own result (step
counts, fitted values, verdicts) -- never raw video, never
personal data. The endpoint is the owner's Worker (the same
``MIMFORGE_WORKER_URL`` configuration the drafting advisor uses);
the API key lives only as a Worker secret, never in the app.

Offline, endpoint missing, timeout, cap reached, toggle off, or
any error: the step proceeds exactly as it would without the
checker, and the returned verdict says which of those it was --
CHECKER NOT AVAILABLE / NOT SET UP / OFF / DAILY CAP -- never a
failure, never more than a short timeout of delay.

A per-day call cap (default 50) is kept in a small state file so
credits cannot burn silently; the shell shows the day's count.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional

#: The build steps the checker reviews.
CHECK_STEPS = ("draft", "verification", "code", "lesson", "risk")

STEP_LABELS = {
    "draft": "DRAFT",
    "verification": "VERIFICATION",
    "code": "GENERATED CODE",
    "lesson": "LESSON",
    "risk": "RISK ASSESSMENT",
}

DEFAULT_DAILY_CAP = 50
DEFAULT_TIMEOUT_S = 5.0


@dataclass
class CheckVerdict:
    """One second opinion. ``verdict`` is one of: agree, flag,
    unavailable, not_set_up, off, capped."""

    step: str
    verdict: str
    concerns: list[str] = field(default_factory=list)
    checked_at: str = ""

    def plain(self) -> str:
        """The one-line status the shell shows."""
        label = STEP_LABELS.get(self.step, self.step.upper())
        if self.verdict == "agree":
            return f"MUSE CHECK — {label}: AGREES WITH THE LOCAL RESULT"
        if self.verdict == "flag":
            first = self.concerns[0] if self.concerns else "SEE THE PROJECT RECORD"
            return f"MUSE CHECK — {label}: FLAGGED — {first}"
        if self.verdict == "unavailable":
            return "MUSE CHECK: NOT AVAILABLE — THE LOCAL RESULT STANDS"
        if self.verdict == "not_set_up":
            return "MUSE CHECK: NOT SET UP — THE LOCAL RESULT STANDS"
        if self.verdict == "off":
            return "MUSE CHECK: OFF — THE LOCAL RESULT STANDS"
        if self.verdict == "capped":
            return "MUSE CHECK: DAILY CAP REACHED — THE LOCAL RESULT STANDS"
        return "MUSE CHECK: THE LOCAL RESULT STANDS"

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "verdict": self.verdict,
            "concerns": list(self.concerns),
            "checked_at": self.checked_at,
        }


class CheckerClient:
    """One POST to the owner's Worker per check. Never raises:
    every failure is the ``unavailable`` verdict."""

    def __init__(
        self,
        url: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        opener: Optional[Callable] = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self._opener = opener or urllib.request.urlopen

    def check(self, step: str, summary: dict) -> CheckVerdict:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload = json.dumps({"step": step, "summary": summary}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/check",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:  # offline, timeout, bad reply -- all the same
            return CheckVerdict(step, "unavailable", [], stamp)
        if not isinstance(body, dict):
            return CheckVerdict(step, "unavailable", [], stamp)
        verdict = body.get("verdict")
        if verdict not in ("agree", "flag"):
            return CheckVerdict(step, "unavailable", [], stamp)
        concerns = body.get("concerns") or []
        if not isinstance(concerns, list):
            concerns = []
        concerns = [str(c) for c in concerns if str(c).strip()]
        if verdict == "flag" and not concerns:
            concerns = ["The checker raised a concern without details."]
        return CheckVerdict(step, verdict, concerns, stamp)


class CheckerService:
    """Enablement + the daily cap + the call counter, persisted in
    one small JSON state file beside the projects folder."""

    def __init__(
        self,
        state_path: str | Path,
        client: CheckerClient | None = None,
        daily_cap: int = DEFAULT_DAILY_CAP,
        today: Optional[Callable[[], str]] = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.client = client
        self.daily_cap = daily_cap
        self._today = today or (lambda: date.today().isoformat())
        self._state = self._load()

    # -- state -----------------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state is not an object")
        except (OSError, ValueError):
            data = {}
        if data.get("date") != self._today():
            data = {"date": self._today(), "count": 0,
                    "enabled": data.get("enabled", True)}
        data.setdefault("count", 0)
        data.setdefault("enabled", True)
        return data

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._state), encoding="utf-8"
            )
        except OSError:
            pass  # the checker must never break the app over its own file

    @property
    def enabled(self) -> bool:
        return bool(self._state.get("enabled", True))

    def set_enabled(self, on: bool) -> None:
        self._state["enabled"] = bool(on)
        self._save()

    @property
    def calls_today(self) -> int:
        if self._state.get("date") != self._today():
            self._state = {"date": self._today(), "count": 0,
                           "enabled": self.enabled}
        return int(self._state.get("count", 0))

    @property
    def configured(self) -> bool:
        return self.client is not None

    # -- the check ---------------------------------------------------------

    def check(self, step: str, summary: dict) -> CheckVerdict:
        """Run one double-check under the toggle and the cap. Only
        a completed call (agree or flag) counts against the cap."""
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.enabled:
            return CheckVerdict(step, "off", [], stamp)
        if self.client is None:
            return CheckVerdict(step, "not_set_up", [], stamp)
        if self.calls_today >= self.daily_cap:
            return CheckVerdict(step, "capped", [], stamp)
        verdict = self.client.check(step, summary)
        if verdict.verdict in ("agree", "flag"):
            self._state["count"] = self.calls_today + 1
            self._state["date"] = self._today()
            self._save()
        return verdict
