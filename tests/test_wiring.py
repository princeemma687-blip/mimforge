"""Stage 3 wiring + panel generators: the schematic and the
panel face are generated from the design and the tier's BOM --
never drawn by hand, so they cannot drift from the machine.

Pins:
- the diagram covers the whole electrical system (power in,
  supply, the monitored-stop chain, limit switches, controller,
  carriage, spool, release actuator, timing sensor) and every
  run connects nodes that exist;
- purchasable nodes take their names from the selected tier's
  BOM lines (a tier switch renames them), and the travel note is
  computed from the design's parameters;
- the panel layout places the template's own control list (the
  same list the generated panel code builds from), inside the
  face, without overlaps, and guarantees a stop control;
- both SVG renderings are self-contained (no external reference
  of any kind) and carry the generated content.
"""

from __future__ import annotations

from mimforge.bom import PartsDB, generate_bom
from mimforge.design import GantryParameters, build_gantry
from mimforge.templates import load_template_data
from mimforge.wiring import (
    build_panel_layout,
    build_wiring_diagram,
    panel_svg,
    wiring_svg,
)

PARAMS = GantryParameters()
DB = PartsDB()


def _bom(tier: str):
    return generate_bom(DB, tier, build_gantry(PARAMS).part_ids)


def _diagram(tier: str = "prototype"):
    return build_wiring_diagram(PARAMS, _bom(tier), db=DB)


# ------------------------------------------------------------------ wiring


def test_diagram_covers_the_whole_electrical_system():
    roles = {node.role for node in _diagram().nodes}
    assert roles == {
        "power_inlet",
        "psu",
        "estop",
        "limits",
        "controller",
        "carriage",
        "spool",
        "release",
        "sensor",
    }


def test_every_run_connects_existing_nodes():
    diagram = _diagram()
    roles = {node.role for node in diagram.nodes}
    assert diagram.runs, "the schematic must wire something"
    for run in diagram.runs:
        assert run.from_role in roles
        assert run.to_role in roles
        assert run.kind in ("power", "safety", "signal", "mechanical")
    # The safety story is wired, not just drawn: a safety run
    # lands on the controller from the stop panel.
    assert any(
        run.kind == "safety" and run.to_role == "controller"
        for run in diagram.runs
    )


def test_node_names_come_from_the_tier_bom():
    proto = _diagram("prototype")
    industrial = _diagram("industrial")
    assert proto.node("release").detail == "Release servo, SG90-class"
    assert industrial.node("release").detail == "Release, encoded motor"
    assert proto.node("controller").detail != industrial.node(
        "controller"
    ).detail
    assert proto.node("sensor").detail == "Timing camera, USB webcam"


def test_travel_note_is_computed_from_the_design():
    wide = GantryParameters(span_mm=800.0)
    diagram = build_wiring_diagram(wide, _bom("prototype"), db=DB)
    # 800 span - 2 x 40 section - 120 carriage = 600 mm of travel.
    assert any("600 mm" in note for note in diagram.notes)
    default = _diagram()
    # 600 span - 2 x 40 section - 120 carriage = 400 mm of travel.
    assert any("400 mm" in note for note in default.notes)


def test_wiring_svg_is_self_contained_and_labelled():
    svg = wiring_svg(_diagram())
    assert "http" not in svg  # no external reference of any kind
    assert "CONTROLLER" in svg
    assert "E-STOP PANEL" in svg
    assert "monitored stop" in svg


# ------------------------------------------------------------------- panel


def _assert_inside_and_disjoint(layout):
    for control in layout.controls:
        assert control.x >= 0 and control.y >= 0
        assert control.x + control.w <= layout.width_mm
        assert control.y + control.h <= layout.height_mm
    rects = [
        (c.x, c.y, c.x + c.w, c.y + c.h) for c in layout.controls
    ]
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            overlap = (
                a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            )
            assert not overlap, f"panel controls overlap: {a} vs {b}"


def test_panel_layout_places_the_templates_own_controls():
    layout = build_panel_layout(load_template_data("pendulum"))
    kinds = {control.kind for control in layout.controls}
    # The template's list: selector, release button, live readout,
    # readings table, graph, stop.
    assert {"selector", "button", "readout", "table", "graph", "estop"} <= kinds
    _assert_inside_and_disjoint(layout)
    stop = next(c for c in layout.controls if c.kind == "estop")
    assert stop.shape == "round"
    # The stop sits at the top-right corner of the face.
    assert stop.x + stop.w >= layout.width_mm - 12
    assert stop.y <= 40


def test_panel_layout_guarantees_a_stop():
    layout = build_panel_layout({})
    assert any(c.kind == "estop" for c in layout.controls)
    _assert_inside_and_disjoint(layout)
    layout = build_panel_layout({"control_panel": ["release", "graph"]})
    assert any(c.kind == "estop" for c in layout.controls)
    _assert_inside_and_disjoint(layout)


def test_panel_svg_is_self_contained_and_dimensioned():
    svg = panel_svg(build_panel_layout(load_template_data("pendulum")))
    assert "http" not in svg
    assert "CONTROL PANEL" in svg
    assert "320 mm" in svg
    assert "E-STOP" in svg
