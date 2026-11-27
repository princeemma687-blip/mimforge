"""Step segmentation + template match + draft generation (plan Phase 2.3).

The engine takes a transcribed narration and a template (the generic
schema's step list, loaded from template DATA) and produces an
``AuthoringDraft``: one draft step per template step, in template order,
each carrying the transcript segments that belong to it and a
confidence score. The structure always comes from the template -- the
teacher may edit wording, never structure.

Draft wording may be improved by an *advisor* (Muse Spark via the
owner's Cloudflare Worker). The advisor is advisory only: it is never
required, never trusted for safety content, and every failure falls
back to the offline draft built from the template's own text. A run
with no advisor configured -- or with the network off -- completes
identically through the offline path (plan test T2.3b).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from .models import PracticalTemplate
from .narration import Transcript

# A segment must share at least this much vocabulary with a step to be
# assigned to it; below it, the segment is left unassigned for the
# teacher to place by hand.
MATCH_THRESHOLD = 0.08

_STOPWORDS = frozenset(
    "a an the and or of to in on at for with from by is are was were be "
    "been it its this that these those we you he she they i my our your "
    "so then now first next after before when while as do does did will "
    "would can could should must not no yes if".split()
)

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {w for w in _TOKEN.findall(text.lower()) if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ------------------------------------------------------------------- draft


@dataclass
class DraftStep:
    step_id: str
    order: int
    title: str
    draft_text: str
    status: str = "draft"  # draft | approved | rejected | edited
    source_spans: list[tuple[float, float]] = field(default_factory=list)
    confidence: float = 0.0
    apparatus_refs: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    check_question: str = ""
    advisor_used: str = "offline"
    # Transient: the teacher's actual spoken words assigned to this
    # step, kept only for the advisor call during build_draft. It is
    # deliberately NOT serialised -- the stored record keeps the
    # spans, and the words live in the project's transcript record.
    spoken_text: str = ""
    # The teacher's own recorded voice for this step (Stage 2), as a
    # mimforge.speech.StepAudio dict. Serialised: when the lesson is
    # built, this recording replaces the app's synthetic voice for
    # the step and is labelled as the teacher's voice everywhere.
    voice_audio: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "order": self.order,
            "title": self.title,
            "draft_text": self.draft_text,
            "status": self.status,
            "source_spans": [list(s) for s in self.source_spans],
            "confidence": self.confidence,
            "apparatus_refs": self.apparatus_refs,
            "safety_notes": self.safety_notes,
            "check_question": self.check_question,
            "advisor_used": self.advisor_used,
            "voice_audio": self.voice_audio,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftStep":
        return cls(
            step_id=data["step_id"],
            order=int(data["order"]),
            title=data["title"],
            draft_text=data["draft_text"],
            status=data.get("status", "draft"),
            source_spans=[tuple(s) for s in data.get("source_spans", [])],
            confidence=float(data.get("confidence", 0.0)),
            apparatus_refs=list(data.get("apparatus_refs", [])),
            safety_notes=list(data.get("safety_notes", [])),
            check_question=data.get("check_question", ""),
            advisor_used=data.get("advisor_used", "offline"),
            voice_audio=data.get("voice_audio"),
        )


@dataclass
class AuthoringDraft:
    template_id: str
    practical_title: str
    steps: list[DraftStep] = field(default_factory=list)
    transcript_engine: str = ""
    unassigned_segments: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "practical_title": self.practical_title,
            "steps": [s.to_dict() for s in self.steps],
            "transcript_engine": self.transcript_engine,
            "unassigned_segments": self.unassigned_segments,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthoringDraft":
        return cls(
            template_id=data["template_id"],
            practical_title=data["practical_title"],
            steps=[DraftStep.from_dict(s) for s in data["steps"]],
            transcript_engine=data.get("transcript_engine", ""),
            unassigned_segments=list(data.get("unassigned_segments", [])),
            warnings=list(data.get("warnings", [])),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @property
    def approved_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "approved")

    @property
    def mean_confidence(self) -> float:
        if not self.steps:
            return 0.0
        return sum(s.confidence for s in self.steps) / len(self.steps)


# ----------------------------------------------------------------- advisor


class Advisor(Protocol):
    name: str

    def draft(self, step_id: str, title: str, context: dict[str, Any]) -> str | None:
        """Return improved draft wording, or None to use the offline text."""


class OfflineAdvisor:
    """The always-available advisor: returns None, so the caller uses
    the template's own narration as the draft text."""

    name = "offline"

    def draft(self, step_id: str, title: str, context: dict[str, Any]) -> str | None:
        return None


class WorkerAdvisor:
    """Muse Spark drafting through the owner's Cloudflare Worker.

    The Worker URL is configuration, never hard-coded, and the API key
    lives only as a Worker secret. Any failure -- no URL, no network,
    non-200, bad JSON -- returns None and the offline draft is used.
    """

    name = "worker"

    def __init__(self, url: str, timeout_s: float = 20.0) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def draft(self, step_id: str, title: str, context: dict[str, Any]) -> str | None:
        payload = json.dumps(
            {"step_id": step_id, "title": title, "context": context}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/draft-step",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        # A misbehaving Worker (non-object JSON, a non-string text)
        # must degrade to the offline draft, never crash the build.
        if not isinstance(body, dict):
            return None
        text = body.get("text") or body.get("draft") or ""
        if not isinstance(text, str):
            return None
        return text.strip() or None


# -------------------------------------------------------------- segmentation


def _step_text(step) -> str:
    parts = [step.title, step.narration, step.expected_observation,
             step.check_question, " ".join(step.apparatus_refs)]
    return " ".join(p for p in parts if p)


def segment_transcript(
    transcript: Transcript, template: PracticalTemplate
) -> tuple[list[DraftStep], list[dict[str, Any]]]:
    """Assign each transcript segment to a template step, monotonically:
    the teacher narrates the steps in order, so assignment never moves
    backwards. Returns (draft steps, unassigned segments)."""
    steps = sorted(template.steps, key=lambda s: s.order)
    step_tokens = [_tokens(_step_text(s)) for s in steps]
    assigned: dict[int, list] = {i: [] for i in range(len(steps))}
    unassigned: list[dict[str, Any]] = []
    pointer = 0  # earliest step index a segment may still belong to
    for seg in transcript.segments:
        seg_tokens = _tokens(seg.text)
        best_i, best_score = -1, 0.0
        for i in range(pointer, len(steps)):
            score = _jaccard(seg_tokens, step_tokens[i])
            if score > best_score:
                best_i, best_score = i, score
        if best_i >= 0 and best_score >= MATCH_THRESHOLD:
            assigned[best_i].append((seg, best_score))
            pointer = best_i
        else:
            unassigned.append(
                {"start_s": seg.start_s, "end_s": seg.end_s, "text": seg.text}
            )
    drafts: list[DraftStep] = []
    for i, step in enumerate(steps):
        segs = assigned[i]
        confidence = (
            sum(score for _, score in segs) / len(segs) if segs else 0.0
        )
        drafts.append(
            DraftStep(
                step_id=step.id,
                order=step.order,
                title=step.title,
                draft_text=step.narration,
                status="draft",
                source_spans=[(s.start_s, s.end_s) for s, _ in segs],
                confidence=round(confidence, 3),
                apparatus_refs=list(step.apparatus_refs),
                safety_notes=list(step.safety_notes),
                check_question=step.check_question,
                spoken_text=" ".join(
                    s.text.strip() for s, _ in segs if s.text.strip()
                ),
            )
        )
    return drafts, unassigned


def _mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def build_draft(
    template: PracticalTemplate,
    transcript: Transcript,
    advisor: Advisor | None = None,
    track_coverage: float | None = None,
    track_report: dict | None = None,
) -> AuthoringDraft:
    """Build the full authoring draft for one demonstration."""
    advisor = advisor or OfflineAdvisor()
    drafts, unassigned = segment_transcript(transcript, template)
    warnings: list[str] = []
    for draft in drafts:
        if draft.confidence == 0.0:
            warnings.append(
                f"step {draft.order} ({draft.step_id}): no narration matched; "
                "draft uses the template text -- teacher should check it"
            )
        context = {
            "template_narration": draft.draft_text,
            "spoken": draft.spoken_text,
            "spoken_spans": " ".join(
                f"[{s[0]:.1f}-{s[1]:.1f}s]" for s in draft.source_spans
            ),
        }
        improved = advisor.draft(draft.step_id, draft.title, context)
        if improved:
            draft.draft_text = improved
            draft.advisor_used = advisor.name
    if unassigned:
        warnings.append(
            f"{len(unassigned)} transcript segment(s) matched no step; "
            "teacher to place them by hand"
        )
    if track_coverage is not None and track_coverage < 0.98:
        warnings.append(
            f"tracked-object coverage {track_coverage:.1%} of the "
            "examined frames is below the 98% target -- check the "
            "footage for occlusions"
        )
    if track_report:
        # The honesty layer reaches the draft: a part of the
        # demonstration that could not be tracked is named here, so
        # the steps built from that moment are known to rest on the
        # narration alone -- never silently complete.
        spans = track_report.get("spans", [])
        for span in spans:
            if span.get("kind") == "failed":
                warnings.append(
                    "part of the demonstration could not be tracked "
                    f"({_mmss(span['start_s'])}-{_mmss(span['end_s'])}): "
                    f"{span.get('reason', '')} -- steps from that "
                    "moment rest on the narration alone"
                )
        bridged = [s for s in spans if s.get("kind") == "bridged"]
        if bridged:
            warnings.append(
                f"{len(bridged)} short part(s) of the motion were "
                "bridged across brief losses and are marked as "
                "bridged in the saved record"
            )
    return AuthoringDraft(
        template_id=template.id,
        practical_title=template.practical.title,
        steps=drafts,
        transcript_engine=transcript.engine,
        unassigned_segments=unassigned,
        warnings=warnings,
    )
