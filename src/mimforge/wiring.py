"""Wiring schematic + control-panel layout (Prince's virtual
production spec, 2026-11-26 18:14): the machine must show HOW IT
WORKS -- its wiring and its paneling -- as generated views, from
the same data the rest of the app runs on.

Both drawings are *generated*, never drawn by hand:

- The wiring diagram's nodes are the machine's electrical roles,
  and every node that is a purchasable thing takes its name from
  the selected tier's BOM line (the servo a prototype buys is not
  the stepper a professional buys, and the schematic says which).
  The runs between them are the platform's electrical story --
  power in, the monitored-stop chain, drive and timing signals --
  and the safety notes repeat the risk assessment's own words:
  extra-low voltage only, current-limited supply, no mains parts
  in any tier.
- The panel layout places the very controls the generated
  control panel (``codegen.generate_control_panel``) builds --
  the template's ``control_panel`` list, read from the same two
  places codegen reads it -- on a dimensioned panel face, with
  the same guarantee codegen makes: a stop control exists even
  when the template's list forgot to ask for one.

Positions are data: the Qt views in ``ui.drawings`` and the SVG
renderers below (which the production dossier embeds) draw the
same numbers, so the app and the exported document can never
show two different wirings.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from .bom import Bom, BomLine, PartsDB
from .design import GantryParameters

__all__ = [
    "PanelControl",
    "PanelLayout",
    "WireNode",
    "WireRun",
    "WiringDiagram",
    "build_panel_layout",
    "build_wiring_diagram",
    "panel_svg",
    "wiring_svg",
]

# Schematic palette (the drafting style, extended by run kind).
_RUN_COLOURS = {
    "power": "#E5484D",
    "safety": "#FFB020",
    "signal": "#00E5FF",
    "mechanical": "#7A838D",
}
_BG = "#101216"
_BOX = "#1B1E24"
_TEXT = "#D7DDE3"
_MUTED = "#7A838D"
_ACCENT = "#00E5FF"


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


# ------------------------------------------------------------------ wiring


@dataclass(frozen=True)
class WireNode:
    """One box on the schematic. ``x``/``y``/``w``/``h`` are in
    schematic units (the canvas is 100 x 70); ``role`` is the
    platform role key, ``label`` the drawn name, ``detail`` the
    smaller line under it (a BOM line name, or the platform
    standard's words)."""

    role: str
    label: str
    detail: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class WireRun:
    """One connection between two nodes. ``kind`` is power,
    safety, signal or mechanical (a physical link, drawn dashed).
    """

    from_role: str
    to_role: str
    label: str
    kind: str


@dataclass
class WiringDiagram:
    title: str
    tier: str
    nodes: list[WireNode] = field(default_factory=list)
    runs: list[WireRun] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def node(self, role: str) -> WireNode:
        for node in self.nodes:
            if node.role == role:
                return node
        raise KeyError(f"no wiring node for role {role!r}")


def _line_for(bom: Bom, db: PartsDB, *, cad: str = "", consumable: str = "") -> BomLine | None:
    """The tier's BOM line traced to one CAD part or consumable."""
    for line in bom.lines:
        part = db.parts.get(line.part_id)
        if part is None:
            continue
        if cad and cad in part.cad_part_ids:
            return line
        if consumable and part.consumable == consumable:
            return line
    return None


def build_wiring_diagram(
    params: GantryParameters,
    bom: Bom,
    db: PartsDB | None = None,
) -> WiringDiagram:
    """The machine's wiring, generated for one tier's BOM.

    Node names for purchasable things come from the tier's own
    lines; the travel note is computed from the design's
    parameters, so the schematic follows the design."""
    db = db if db is not None else PartsDB()
    controller = _line_for(bom, db, consumable="controller-board")
    estop = _line_for(bom, db, consumable="estop-panel")
    carriage = _line_for(bom, db, cad="carriage")
    spool = _line_for(bom, db, cad="spool_drum")
    release = _line_for(bom, db, cad="release_gate")
    sensor = _line_for(bom, db, cad="sensor_bracket")

    def detail(line: BomLine | None, fallback: str) -> str:
        return line.name if line is not None else fallback

    travel_mm = (
        params.span_mm - 2 * params.section_mm - params.carriage_width_mm
    )
    nodes = [
        WireNode("power_inlet", "BENCH POWER INLET",
                 "extra-low voltage only", 2, 30, 15, 12),
        WireNode("psu", "POWER SUPPLY",
                 "current-limited, short-circuit cut-off", 23, 30, 16, 12),
        WireNode("estop", "E-STOP PANEL",
                 detail(estop, "latching stop panel"), 23, 4, 16, 12),
        WireNode("limits", "TRAVEL LIMIT SWITCHES",
                 "one at each end of the beam", 47, 4, 17, 12),
        WireNode("controller", "CONTROLLER",
                 detail(controller, "controller board"), 47, 30, 17, 12),
        WireNode("carriage", "CARRIAGE",
                 detail(carriage, "travelling carriage"), 74, 4, 22, 12),
        WireNode("spool", "SPOOL DRUM",
                 detail(spool, "spool drum"), 74, 26, 22, 12),
        WireNode("release", "RELEASE ACTUATOR",
                 detail(release, "release gate actuator"), 74, 48, 22, 12),
        WireNode("sensor", "TIMING SENSOR",
                 detail(sensor, "timing sensor"), 47, 52, 17, 12),
    ]
    runs = [
        WireRun("power_inlet", "psu", "bench feed", "power"),
        WireRun("psu", "controller", "power, current-limited", "power"),
        WireRun("psu", "estop", "stop-chain feed", "power"),
        WireRun("estop", "controller",
                "monitored stop — breaks the drive enable", "safety"),
        WireRun("limits", "controller", "travel-end signals", "signal"),
        WireRun("controller", "carriage", "drive + position", "signal"),
        WireRun("carriage", "spool",
                "mechanical — the drum rides the carriage", "mechanical"),
        WireRun("controller", "release", "release command", "signal"),
        WireRun("sensor", "controller", "timing pulses", "signal"),
    ]
    notes = [
        "Extra-low voltage only; current-limited supply; "
        "short-circuit cut-off; no mains parts in any tier.",
        "The monitored stop chain (E-stop panel to controller) "
        "breaks the drive enable; the safety kernel latches the "
        "stop until a teacher resets it deliberately.",
        f"Carriage travel between the limit switches: "
        f"{travel_mm:.0f} mm on this design.",
        "Colours: red = power, amber = safety chain, cyan = "
        "signal, grey dashed = mechanical link.",
    ]
    return WiringDiagram(
        title="WIRING — HOW THE MACHINE IS CONNECTED",
        tier=bom.tier,
        nodes=nodes,
        runs=runs,
        notes=notes,
    )


# ------------------------------------------------------------------- panel


@dataclass(frozen=True)
class PanelControl:
    """One control on the panel face. Position and size in
    millimetres on the face; ``shape`` is "rect" or "round"
    (the latching stop is drawn as the round switch it is)."""

    control_id: str
    label: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    shape: str = "rect"


@dataclass
class PanelLayout:
    title: str
    width_mm: float
    height_mm: float
    controls: list[PanelControl] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def control(self, control_id: str) -> PanelControl:
        for control in self.controls:
            if control.control_id == control_id:
                return control
        raise KeyError(f"no panel control {control_id!r}")


def _control_kind(name: str) -> str:
    """The kind of one control from the template's list -- the
    same keyword reading ``codegen`` gives the same list, so the
    drawn panel and the generated panel agree."""
    key = name.lower()
    if "selector" in key:
        return "selector"
    if "release" in key:
        return "button"
    if "stop" in key:
        return "estop"
    if "count" in key or "time" in key or "live" in key:
        return "readout"
    if "table" in key:
        return "table"
    if "graph" in key:
        return "graph"
    return "label"


# Face size and per-kind footprints (mm). The face is a standard
# enclosure front; wide kinds (readout, table, graph) take a row.
_PANEL_W, _PANEL_H = 320.0, 216.0
_KIND_SIZE = {
    "selector": (150.0, 18.0),
    "button": (110.0, 20.0),
    "readout": (210.0, 18.0),
    "table": (296.0, 52.0),
    "graph": (296.0, 52.0),
    "label": (150.0, 16.0),
    "estop": (48.0, 48.0),
}


def build_panel_layout(template_data: dict) -> PanelLayout:
    """The control-panel face for one template, generated from
    the same control list the generated panel code is built
    from. The latching stop sits at the top-right corner, big
    and round; the rest flow in rows beneath the title strip.
    A stop control is guaranteed (codegen's rule, kept here):
    a panel without one is not finished."""
    practical = template_data.get("practical", {}) or {}
    title = str(practical.get("title", "Untitled practical"))
    controls_in = template_data.get("control_panel", []) or []
    if not controls_in:
        controls_in = (
            template_data.get("machine_design_hint", {}).get(
                "control_panel", []
            )
            or []
        )
    names = [str(c) for c in controls_in]
    if not any("stop" in n.lower() for n in names):
        names.append("stop")

    placed: list[PanelControl] = []
    estop_rect = (
        _PANEL_W - 12.0 - _KIND_SIZE["estop"][0],
        30.0,
        _KIND_SIZE["estop"][0],
        _KIND_SIZE["estop"][1],
    )
    flow: list[tuple[str, str, str]] = []  # (id, label, kind)
    used_ids: set[str] = set()
    for name in names:
        kind = _control_kind(name)
        cid = name.lower().replace(" ", "_")
        if cid in used_ids:
            cid = f"{cid}_{len(used_ids)}"
        used_ids.add(cid)
        if kind == "estop":
            placed.append(
                PanelControl(
                    cid, "E-STOP — LATCHING", kind,
                    estop_rect[0], estop_rect[1],
                    estop_rect[2], estop_rect[3], shape="round",
                )
            )
        else:
            flow.append((cid, name.upper(), kind))

    x, y = 12.0, 30.0
    row_h = 0.0
    # The stop's corner (inflated) is out of bounds for the flow:
    # a control that would crowd it starts a fresh row below it.
    corner_x = estop_rect[0] - 4
    corner_bottom = estop_rect[1] + estop_rect[3] + 4
    for cid, label, kind in flow:
        w, h = _KIND_SIZE[kind]
        if x + w > _PANEL_W - 12:
            x, y, row_h = 12.0, y + row_h + 8, 0.0
        if y < corner_bottom and x + w > corner_x:
            x, y, row_h = 12.0, corner_bottom + 4, 0.0
        placed.append(PanelControl(cid, label, kind, x, y, w, h))
        x += w + 10
        row_h = max(row_h, h)
    height = max(_PANEL_H, y + row_h + 12)
    notes = [
        "Panel face 320 mm wide; the latching stop is the round "
        "switch at the top right, reachable without looking.",
        "Release and Stop act only through the safety kernel; "
        "the stop latches until a teacher resets it.",
        "Every control drawn here is one the generated control "
        "panel builds -- same list, same order.",
    ]
    return PanelLayout(
        title=title,
        width_mm=_PANEL_W,
        height_mm=height,
        controls=placed,
        notes=notes,
    )


# -------------------------------------------------------------- SVG output
#
# The dossier's drawings. Inline SVG (no namespace declaration --
# inline SVG in HTML does not need one, and the dossier asserts
# it carries no external reference of any kind).


def _svg_open(width: float, height: float, css_class: str) -> list[str]:
    return [
        f'<svg class="{css_class}" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="{_BG}"/>',
    ]


def wiring_svg(diagram: WiringDiagram, *, width: float = 920.0) -> str:
    """The wiring diagram as a self-contained SVG drawing."""
    scale = width / 100.0
    height = 70.0 * scale + 22.0 + 13.0 * len(diagram.notes)
    out = _svg_open(width, height, "wiring")
    by_role = {node.role: node for node in diagram.nodes}

    def px(v: float) -> float:
        return v * scale

    # Runs first (under the boxes): orthogonal elbows from the
    # source's edge to the target's edge.
    for run in diagram.runs:
        a, b = by_role[run.from_role], by_role[run.to_role]
        ax, ay = px(a.x + a.w), px(a.y + a.h / 2)
        bx, by = px(b.x), px(b.y + b.h / 2)
        if run.kind == "mechanical":
            ax, ay = px(a.x + a.w / 2), px(a.y + a.h)
            bx, by = px(b.x + b.w / 2), px(b.y)
        mid_x = (ax + bx) / 2
        colour = _RUN_COLOURS[run.kind]
        dash = ' stroke-dasharray="5 4"' if run.kind == "mechanical" else ""
        out.append(
            f'<path d="M {ax:.1f} {ay:.1f} L {mid_x:.1f} {ay:.1f} '
            f'L {mid_x:.1f} {by:.1f} L {bx:.1f} {by:.1f}" fill="none" '
            f'stroke="{colour}" stroke-width="1.6"{dash}/>'
        )
        out.append(
            f'<text x="{mid_x + 3:.1f}" y="{(ay + by) / 2 - 3:.1f}" '
            f'fill="{_MUTED}" font-size="8.5">{_esc(run.label)}</text>'
        )
    for node in diagram.nodes:
        x, y, w, h = px(node.x), px(node.y), px(node.w), px(node.h)
        stroke = _ACCENT if node.role in ("controller", "estop") else "#4A5158"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{_BOX}" stroke="{stroke}" stroke-width="1.2"/>'
        )
        out.append(
            f'<text x="{x + 5:.1f}" y="{y + 13:.1f}" fill="{_TEXT}" '
            f'font-size="9.5" font-weight="bold">{_esc(node.label)}</text>'
        )
        out.append(
            f'<text x="{x + 5:.1f}" y="{y + 25:.1f}" fill="{_MUTED}" '
            f'font-size="8">{_esc(node.detail)}</text>'
        )
    note_y = 70.0 * scale + 16.0
    for note in diagram.notes:
        out.append(
            f'<text x="2" y="{note_y:.1f}" fill="{_MUTED}" '
            f'font-size="9">{_esc(note)}</text>'
        )
        note_y += 13.0
    out.append("</svg>")
    return "\n".join(out)


def panel_svg(layout: PanelLayout, *, width: float = 760.0) -> str:
    """The panel face as a self-contained SVG drawing, with
    dimension lines for the face width and height."""
    scale = width / (layout.width_mm + 36.0)
    height = (layout.height_mm + 30.0) * scale
    ox, oy = 4.0, 4.0
    out = _svg_open(width, height, "panel")

    def px(v: float) -> float:
        return ox + v * scale

    def py(v: float) -> float:
        return oy + v * scale

    out.append(
        f'<rect x="{px(0):.1f}" y="{py(0):.1f}" '
        f'width="{layout.width_mm * scale:.1f}" '
        f'height="{layout.height_mm * scale:.1f}" fill="{_BOX}" '
        f'stroke="{_ACCENT}" stroke-width="1.4"/>'
    )
    out.append(
        f'<text x="{px(12):.1f}" y="{py(20):.1f}" fill="{_ACCENT}" '
        f'font-size="11" font-weight="bold">CONTROL PANEL — '
        f'{_esc(layout.title.upper())}</text>'
    )
    for control in layout.controls:
        x, y = px(control.x), py(control.y)
        w, h = control.w * scale, control.h * scale
        if control.shape == "round":
            out.append(
                f'<circle cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" '
                f'r="{min(w, h) / 2:.1f}" fill="#5C1A1A" '
                f'stroke="#E5484D" stroke-width="2"/>'
            )
            out.append(
                f'<text x="{x + w / 2:.1f}" y="{y + h + 12:.1f}" '
                f'fill="{_TEXT}" font-size="8.5" text-anchor="middle">'
                f'{_esc(control.label)}</text>'
            )
            continue
        fill = "#22252B"
        stroke = _ACCENT if control.kind in ("button", "selector") else "#4A5158"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.1"/>'
        )
        out.append(
            f'<text x="{x + 5:.1f}" y="{y + 13:.1f}" fill="{_TEXT}" '
            f'font-size="8.5">{_esc(control.label)}</text>'
        )
    # Dimension lines: width under the face, height at its right.
    dim_y = py(layout.height_mm) + 16
    out.append(
        f'<line x1="{px(0):.1f}" y1="{dim_y:.1f}" x2="{px(layout.width_mm):.1f}" '
        f'y2="{dim_y:.1f}" stroke="{_MUTED}" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{px(layout.width_mm / 2):.1f}" y="{dim_y + 11:.1f}" '
        f'fill="{_MUTED}" font-size="9" text-anchor="middle">'
        f'{layout.width_mm:.0f} mm</text>'
    )
    dim_x = px(layout.width_mm) + 14
    out.append(
        f'<line x1="{dim_x:.1f}" y1="{py(0):.1f}" x2="{dim_x:.1f}" '
        f'y2="{py(layout.height_mm):.1f}" stroke="{_MUTED}" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{dim_x + 10:.1f}" y="{py(layout.height_mm / 2):.1f}" '
        f'fill="{_MUTED}" font-size="9">{layout.height_mm:.0f} mm</text>'
    )
    out.append("</svg>")
    return "\n".join(out)
