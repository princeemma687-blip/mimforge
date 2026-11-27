"""Stage 3 production document: the dossier carries the whole
virtual production in one self-contained HTML file, and it is
gated like the signed package -- a production document leaves
only after a teacher has signed the risk assessment.

Pins:
- every section is present (machine views, what it does, the
  coupling steps, wiring, panel, materials at all three tiers,
  safety, controller code);
- the document references nothing external (it must open
  offline, forever);
- an unsigned assessment refuses the export BEFORE any file is
  written, through the same risk gate as the signed package;
- machine images fall back to generated SVG projections when no
  renderer is available, so the dossier never depends on one.
"""

from __future__ import annotations

import pytest

from mimforge import dossier, risk
from mimforge.bom import TIERS, PartsDB, generate_bom
from mimforge.delivery import (
    build_assessment,
    fingerprint_design,
    generate_checked_code,
)
from mimforge.design import GantryParameters, build_gantry
from mimforge.playback import LessonPackage, LessonStep
from mimforge.templates import load_template_data

PARAMS = GantryParameters()
TEMPLATE = load_template_data("pendulum")  # a template, as data


def _tier_boms():
    db = PartsDB()
    part_ids = build_gantry(PARAMS).part_ids
    return {tier: generate_bom(db, tier, part_ids) for tier in TIERS}


def _signed_assessment():
    assessment = build_assessment(TEMPLATE)
    assessment.design_fingerprint = fingerprint_design(PARAMS)
    risk.sign(assessment, "Ada Teacher")
    return assessment


def _build(assessment, **overrides):
    kwargs = dict(
        project_title="Pendulum Bench",
        template_data=TEMPLATE,
        params=PARAMS,
        tier_boms=_tier_boms(),
        assessment=assessment,
        code=generate_checked_code(TEMPLATE, PARAMS),
        images={},  # images are exercised separately; keep this fast
    )
    kwargs.update(overrides)
    return dossier.build_dossier_html(**kwargs)


SECTIONS = (
    "THE MACHINE — EVERY SIDE",
    "WHAT IT DOES",
    "HOW IT IS BUILT — STEP-BY-STEP COUPLING",
    "WIRING — HOW IT WORKS",
    "CONTROL PANEL",
    "MATERIALS — EVERYTHING NEEDED",
    "SAFETY — RISK ASSESSMENT",
    "CONTROLLER CODE",
)


def test_dossier_has_every_section():
    doc = _build(_signed_assessment())
    for heading in SECTIONS:
        assert heading in doc, heading
    # Materials carry all three tier totals.
    for total in ("₦69,500", "₦159,000", "₦359,500"):
        assert total in doc
    # The coupling sequence is in, step by step.
    assert "Step 1 of 9" in doc and "Step 9 of 9" in doc
    # The sign-off is stated, with the teacher's name.
    assert "SIGNED BY Ada Teacher" in doc
    # The generated drawings are embedded.
    assert 'class="wiring"' in doc and 'class="panel"' in doc
    assert "CONTROLLER" in doc and "E-STOP" in doc


def test_dossier_is_fully_self_contained():
    doc = _build(_signed_assessment())
    assert "http://" not in doc
    assert "https://" not in doc
    assert 'src="data:' in doc or "<svg" in doc  # images are inline


def test_dossier_uses_the_lesson_when_one_exists():
    lesson = LessonPackage(
        title="Pendulum Bench",
        subject="Physics",
        template_id="pendulum",
        steps=[
            LessonStep(
                order=1,
                title="A very distinctive lesson step",
                narration="Do the distinctive thing.",
            )
        ],
    )
    doc = _build(_signed_assessment(), lesson=lesson)
    assert "A very distinctive lesson step" in doc
    assert "Do the distinctive thing." in doc


def test_export_refuses_unsigned_before_writing(tmp_path):
    target = tmp_path / "production.html"
    with pytest.raises(risk.ExportBlocked):
        dossier.export_production_document(
            out_path=target,
            assessment=build_assessment(TEMPLATE),  # unsigned
            project_title="Pendulum Bench",
            template_data=TEMPLATE,
            params=PARAMS,
            tier_boms=_tier_boms(),
            code=generate_checked_code(TEMPLATE, PARAMS),
            images={},
        )
    assert not target.exists()


def test_export_writes_the_document_when_signed(tmp_path):
    target = tmp_path / "production.html"
    out = dossier.export_production_document(
        out_path=target,
        assessment=_signed_assessment(),
        project_title="Pendulum Bench",
        template_data=TEMPLATE,
        params=PARAMS,
        tier_boms=_tier_boms(),
        code=generate_checked_code(TEMPLATE, PARAMS),
        images={},
    )
    assert out == target and target.exists()
    text = target.read_text(encoding="utf-8")
    for heading in SECTIONS:
        assert heading in text


def test_machine_images_fall_back_to_svg_projections():
    images = dossier.machine_image_data_uris(PARAMS, use_renderer=False)
    assert set(images) == {"front", "side", "top", "internals"}
    for uri in images.values():
        assert uri.startswith("data:image/svg+xml")
