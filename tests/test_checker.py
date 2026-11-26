"""Muse Spark double-checker — client and service contract.

A fake transport speaks the Worker's wire shape. The rules under
test are the binding ones: the local result always stands; agree
and flag are the only verdicts a completed call can return; every
failure is ``unavailable``; the toggle and the daily cap gate the
calls, and only completed calls count against the cap.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from mimforge.checker import CheckerClient, CheckerService


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _opener_returning(payload, calls: list):
    def opener(request, timeout=None):
        calls.append((request.full_url, timeout))
        return _Response(json.dumps(payload).encode("utf-8"))

    return opener


def test_client_agree_and_flag(tmp_path):
    calls: list = []
    client = CheckerClient(
        "https://worker.example/",
        opener=_opener_returning({"verdict": "agree"}, calls),
    )
    verdict = client.check("verification", {"recovered": 9.796})
    assert verdict.verdict == "agree"
    assert verdict.concerns == []
    assert calls[0][0] == "https://worker.example/check"
    assert calls[0][1] == 5.0  # the short timeout

    client = CheckerClient(
        "https://worker.example",
        opener=_opener_returning(
            {"verdict": "flag", "concerns": ["Slope uses only two points."]},
            calls,
        ),
    )
    verdict = client.check("verification", {})
    assert verdict.verdict == "flag"
    assert verdict.concerns == ["Slope uses only two points."]
    assert "FLAGGED" in verdict.plain()


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        OSError("connection reset"),
    ],
)
def test_client_failures_are_unavailable_never_raised(failure):
    def dead_opener(request, timeout=None):
        raise failure

    client = CheckerClient("https://worker.example", opener=dead_opener)
    verdict = client.check("draft", {})
    assert verdict.verdict == "unavailable"
    assert "NOT AVAILABLE" in verdict.plain()


def test_client_bad_replies_are_unavailable():
    for payload in (["not", "a", "dict"], {"verdict": "maybe"}, {"nope": 1}):
        client = CheckerClient(
            "https://worker.example",
            opener=_opener_returning(payload, []),
        )
        assert client.check("code", {}).verdict == "unavailable"

    def garbage_opener(request, timeout=None):
        return _Response(b"this is not json")

    client = CheckerClient("https://worker.example", opener=garbage_opener)
    assert client.check("code", {}).verdict == "unavailable"


def test_service_gates_and_counts(tmp_path):
    calls: list = []
    client = CheckerClient(
        "https://worker.example",
        opener=_opener_returning({"verdict": "agree"}, calls),
    )
    service = CheckerService(
        tmp_path / "checker-state.json", client=client, daily_cap=2
    )
    assert service.check("draft", {}).verdict == "agree"
    assert service.calls_today == 1
    assert service.check("lesson", {}).verdict == "agree"
    assert service.calls_today == 2
    # Cap reached: no further call is even attempted.
    assert service.check("risk", {}).verdict == "capped"
    assert len(calls) == 2


def test_service_unavailable_does_not_burn_the_cap(tmp_path):
    def dead_opener(request, timeout=None):
        raise urllib.error.URLError("offline")

    client = CheckerClient("https://worker.example", opener=dead_opener)
    service = CheckerService(
        tmp_path / "state.json", client=client, daily_cap=1
    )
    assert service.check("draft", {}).verdict == "unavailable"
    assert service.calls_today == 0


def test_service_off_and_not_set_up(tmp_path):
    calls: list = []
    client = CheckerClient(
        "https://worker.example",
        opener=_opener_returning({"verdict": "agree"}, calls),
    )
    service = CheckerService(tmp_path / "state.json", client=client)
    service.set_enabled(False)
    assert service.check("draft", {}).verdict == "off"
    assert calls == []  # toggle off = zero calls

    bare = CheckerService(tmp_path / "state2.json", client=None)
    assert bare.check("draft", {}).verdict == "not_set_up"
    assert "NOT SET UP" in bare.check("draft", {}).plain()


def test_service_state_persists_and_the_day_rolls_over(tmp_path):
    path = tmp_path / "state.json"
    day = {"today": "2026-11-26"}
    client = CheckerClient(
        "https://worker.example",
        opener=_opener_returning({"verdict": "agree"}, []),
    )
    service = CheckerService(
        path, client=client, daily_cap=1, today=lambda: day["today"]
    )
    service.set_enabled(False)
    assert service.check("draft", {}).verdict == "off"

    # A fresh service over the same file remembers the toggle.
    again = CheckerService(
        path, client=client, daily_cap=1, today=lambda: day["today"]
    )
    assert not again.enabled
    again.set_enabled(True)
    assert again.check("draft", {}).verdict == "agree"
    assert again.check("draft", {}).verdict == "capped"
    # Tomorrow the cap resets; the toggle stays as the teacher left it.
    day["today"] = "2026-11-27"
    assert again.calls_today == 0
    assert again.check("draft", {}).verdict == "agree"
