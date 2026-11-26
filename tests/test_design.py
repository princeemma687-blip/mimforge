"""Phase 3.1 tests: parametric bench gantry (plan test T3.1).

Generated CAD must open, and key dimensions measured in the model must
match the parameters within +/-1 mm.
"""

import pytest

from mimforge.design import (
    GantryParameters,
    build_gantry,
    export_cad,
    measure_gantry,
    read_step_dimensions,
)


def test_default_gantry_dimensions_match_parameters():
    design = build_gantry(GantryParameters())
    m = measure_gantry(design)
    assert m.overall_span_mm == pytest.approx(600.0, abs=1.0)
    # Beam sits on top of the uprights: height + one section.
    assert m.overall_height_mm == pytest.approx(1100.0 + 40.0, abs=1.0)
    assert m.overall_depth_mm == pytest.approx(300.0, abs=1.0)
    assert m.beam_length_mm == pytest.approx(600.0, abs=1.0)
    assert m.upright_height_mm == pytest.approx(1100.0, abs=1.0)
    assert m.suspension_range_mm == (500.0, 1000.0)


def test_custom_parameters_drive_the_model():
    params = GantryParameters(
        span_mm=800.0,
        height_mm=750.0,
        section_mm=30.0,
        base_depth_mm=250.0,
        suspension_range_mm=(400.0, 700.0),
    )
    design = build_gantry(params)
    m = measure_gantry(design)
    assert m.overall_span_mm == pytest.approx(800.0, abs=1.0)
    assert m.overall_height_mm == pytest.approx(750.0 + 30.0, abs=1.0)
    assert m.overall_depth_mm == pytest.approx(250.0, abs=1.0)
    assert m.suspension_range_mm == (400.0, 700.0)


def test_exported_step_reopens_with_same_dimensions(tmp_path):
    design = build_gantry(
        GantryParameters(span_mm=700.0, height_mm=800.0, suspension_range_mm=(400.0, 700.0))
    )
    step_path = export_cad(design, tmp_path / "gantry.step")
    stl_path = export_cad(design, tmp_path / "gantry.stl")
    assert step_path.is_file() and step_path.stat().st_size > 0
    assert stl_path.is_file() and stl_path.stat().st_size > 0
    reopened = read_step_dimensions(step_path)
    assert reopened.overall_span_mm == pytest.approx(700.0, abs=1.0)
    assert reopened.overall_height_mm == pytest.approx(800.0 + 40.0, abs=1.0)


def test_all_nine_parts_listed_for_bom_tracing():
    design = build_gantry(GantryParameters())
    assert design.part_ids == [
        "upright_left",
        "upright_right",
        "top_beam",
        "foot_left",
        "foot_right",
        "carriage",
        "spool_drum",
        "release_gate",
        "sensor_bracket",
    ]


def test_invalid_parameters_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_gantry(GantryParameters(span_mm=50.0))  # narrower than sections
    with pytest.raises(ValueError):
        build_gantry(GantryParameters(carriage_x_mm=400.0))  # outside uprights
    with pytest.raises(ValueError):
        build_gantry(GantryParameters(suspension_range_mm=(1200.0, 1500.0)))
    with pytest.raises(ValueError):
        export_cad(build_gantry(GantryParameters()), tmp_path / "x.dxf")


# ------------------------------------------- full spec audit (2026-11-26)


@pytest.mark.parametrize(
    "overrides",
    [
        {"spool_radius_mm": 0.0},
        {"spool_length_mm": -5.0},
        {"carriage_width_mm": 0.0},
        {"carriage_height_mm": -1.0},
        {"foot_height_mm": 0.0},
    ],
)
def test_validate_rejects_every_nonsense_dimension(overrides):
    """validate() covers ALL dimensions, not only the headline
    ones: a zero/negative spool, carriage or foot dimension is
    rejected before any CAD is built."""
    params = GantryParameters(**overrides)
    with pytest.raises(ValueError):
        params.validate()


def test_measurements_come_from_the_solids_not_the_parameters():
    """Beam length and upright height are read back from the kept
    sub-solids' bounding boxes (a non-default size proves the
    numbers travel with the geometry)."""
    design = build_gantry(
        GantryParameters(span_mm=800.0, height_mm=1200.0)
    )
    measured = measure_gantry(design)
    assert measured.beam_length_mm == pytest.approx(800.0, abs=1.0)
    assert measured.upright_height_mm == pytest.approx(1200.0, abs=1.0)
