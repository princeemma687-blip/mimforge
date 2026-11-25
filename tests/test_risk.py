"""Phase 3.3 tests: risk assessment + teacher sign-off gate."""

import pytest

from mimforge.risk import (
    ExportBlocked,
    assert_export_ready,
    generate_risk_assessment,
    sign,
    to_safety_case,
)


def test_export_blocked_until_signed():
    assessment = generate_risk_assessment("demo-1", "bench_gantry")
    with pytest.raises(ExportBlocked):
        assert_export_ready(assessment)


def test_signing_unblocks_export():
    assessment = generate_risk_assessment("demo-1", "bench_gantry")
    sign(assessment, "Mrs A. Teacher")
    assert assessment.signed
    assert_export_ready(assessment)  # must not raise


def test_tamper_after_signing_reblocks_export():
    assessment = generate_risk_assessment("demo-1", "bench_gantry")
    sign(assessment, "Mrs A. Teacher")
    assessment.hazards[0].description = "edited after signing"
    assert not assessment.verify_signoff()
    assert not assessment.signed
    with pytest.raises(ExportBlocked):
        assert_export_ready(assessment)


def test_template_hazards_merge_with_platform_hazards():
    assessment = generate_risk_assessment(
        "demo-1",
        "bench_gantry",
        template_hazards=[
            "falling stand if base is unstable",
            "pinch at the pivot clamp",
        ],
        template_id="demo-template",
    )
    assert len(assessment.hazards) == 4 + 2  # 4 platform + 2 template
    template_entries = [h for h in assessment.hazards if h.source.startswith("template:")]
    assert len(template_entries) == 2
    assert all(h.source == "template:demo-template" for h in template_entries)


def test_blank_teacher_name_cannot_sign():
    assessment = generate_risk_assessment("demo-1", "bench_gantry")
    with pytest.raises(ValueError):
        sign(assessment, "   ")


def test_safety_case_reflects_signoff():
    assessment = generate_risk_assessment("demo-1", "bench_gantry")
    case = to_safety_case(assessment)
    assert not case.signed_by_teacher
    sign(assessment, "Mrs A. Teacher")
    case = to_safety_case(assessment)
    assert case.signed_by_teacher
    assert "Mrs A. Teacher" in case.risk_assessment
    assert "monitored stop" in case.interlocks[0]
