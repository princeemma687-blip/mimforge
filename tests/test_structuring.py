"""Phase 2.3: step segmentation + template match + draft generation.

Test T2.3: a transcript built from the template's own narration must
reproduce the template's step list -- same ids, same order, all drafts.
Test T2.3b: the same run with no advisor (network off / unconfigured)
completes through the offline fallback.
"""

import pytest

from mimforge.narration import Transcript, TranscriptSegment, manual_transcript
from mimforge.structuring import (
    AuthoringDraft,
    OfflineAdvisor,
    WorkerAdvisor,
    build_draft,
)
from mimforge.templates import load_template


def _template_transcript():
    """A narration that says each template step in order, 10 s apart."""
    template = load_template()
    entries = []
    t = 0.0
    for step in sorted(template.steps, key=lambda s: s.order):
        entries.append((t, t + 8.0, step.narration))
        t += 10.0
    return template, manual_transcript(entries)


def test_build_draft_reproduces_template_steps():
    """T2.3: structure comes from the template, wording is a draft."""
    template, transcript = _template_transcript()
    draft = build_draft(template, transcript)
    assert draft.template_id == template.id
    assert len(draft.steps) == len(template.steps) == 9
    assert [s.step_id for s in draft.steps] == [
        s.id for s in sorted(template.steps, key=lambda s: s.order)
    ]
    assert [s.order for s in draft.steps] == list(range(1, 10))
    assert all(s.status == "draft" for s in draft.steps)
    assert all(s.advisor_used == "offline" for s in draft.steps)
    assert draft.mean_confidence > 0.3
    assert draft.unassigned_segments == []
    # Each step carries its narration span for the teacher to check.
    assert all(len(s.source_spans) == 1 for s in draft.steps)


def test_build_draft_offline_fallback_no_advisor():
    """T2.3b: no advisor configured -- the run still completes."""
    template, transcript = _template_transcript()
    draft = build_draft(template, transcript, advisor=None)
    assert len(draft.steps) == 9
    assert draft.steps[0].draft_text == template.steps[0].narration


def test_worker_advisor_failure_falls_back_offline():
    """An unreachable advisor must not fail the run (network off)."""
    template, transcript = _template_transcript()
    advisor = WorkerAdvisor("http://127.0.0.1:9/draft")
    assert advisor.draft("setup", "Set up", {}) is None
    draft = build_draft(template, transcript, advisor=advisor)
    assert len(draft.steps) == 9
    assert all(s.advisor_used == "offline" for s in draft.steps)


def test_unmatched_narration_is_flagged_not_forced():
    template, _ = _template_transcript()
    transcript = Transcript(
        segments=[
            TranscriptSegment(0.0, 5.0, template.steps[0].narration),
            TranscriptSegment(
                6.0, 10.0, "the weather today is cloudy and the bus is late"
            ),
        ],
        engine="manual",
    )
    draft = build_draft(template, transcript)
    assert len(draft.unassigned_segments) == 1
    assert "cloudy" in draft.unassigned_segments[0]["text"]
    assert any("matched no step" in w for w in draft.warnings)
    # Steps with no matched narration warn the teacher instead of guessing.
    assert any("no narration matched" in w for w in draft.warnings)


def test_low_track_coverage_warns():
    template, transcript = _template_transcript()
    draft = build_draft(template, transcript, track_coverage=0.5)
    assert any("below the 98% target" in w for w in draft.warnings)


def test_draft_json_round_trip():
    template, transcript = _template_transcript()
    draft = build_draft(template, transcript)
    restored = AuthoringDraft.from_dict(draft.to_dict())
    assert restored.template_id == draft.template_id
    assert [s.step_id for s in restored.steps] == [
        s.step_id for s in draft.steps
    ]
    assert restored.steps[0].draft_text == draft.steps[0].draft_text
    assert restored.to_json() == draft.to_json()


def test_offline_advisor_returns_none():
    assert OfflineAdvisor().draft("x", "y", {}) is None


# ------------------------------------------- full spec audit (2026-11-26)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


@pytest.mark.parametrize(
    "body",
    [b"[1, 2, 3]", b'"just a string"', b'{"text": 123}', b"not json"],
)
def test_worker_advisor_bad_bodies_degrade_to_none(monkeypatch, body):
    """A misbehaving Worker -- non-object JSON, a non-string text,
    invalid JSON -- degrades to the offline draft (None), it never
    raises out of draft()."""
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(body),
    )
    advisor = WorkerAdvisor("http://worker.invalid")
    assert advisor.draft("s1", "Title", {}) is None


def test_advisor_receives_the_teachers_spoken_words():
    """The advisor context carries what the teacher actually said
    for the step (not only timing brackets), so an online advisor
    can improve real wording."""
    captured = {}

    class _Capture:
        name = "capture"

        def draft(self, step_id, title, context):
            captured[step_id] = context
            return None

    transcript = Transcript(
        segments=[
            TranscriptSegment(
                0.0,
                4.0,
                "Set up the stand, clamp the thread and measure "
                "the length from the pivot to the centre.",
            )
        ],
        engine="test",
    )
    template = load_template()
    build_draft(template, transcript, advisor=_Capture())
    first_step = template.steps[0].id
    assert "clamp the thread" in captured[first_step]["spoken"]
    assert captured[first_step]["spoken_spans"].startswith("[0.0-4.0s]")
