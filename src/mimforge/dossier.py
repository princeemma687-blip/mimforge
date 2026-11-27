"""Production-document export (Prince's virtual production spec,
2026-11-26 18:14): the whole virtual production as one
self-contained HTML document that shows the production itself.

The dossier is the paper twin of the app: the machine from every
side (rendered views + the taken-apart internals), what it does,
how it is coupled together step by step, its wiring and its
control panel, the full materials at every tier's prices, the
signed risk assessment, and the checked controller code. It sits
beside the signed ``.tmachine`` package in Deliver, and it is
gated exactly like it: :func:`export_production_document` runs
the sign-off gate FIRST, before a single image is rendered or a
byte is written -- a production document is how someone would
build the machine, so it does not leave without a teacher's
signature.

Everything in it is generated from the same data the app runs
on (design parameters, the parts database, the assembly table,
the wiring/panel generators, the checked code bundle), so the
document cannot drift from the app it was exported from. No
external references: images are data URIs, drawings are inline
SVG, and the file works offline in any browser.
"""

from __future__ import annotations

import base64
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import risk
from .assembly import AssemblyPlan, build_assembly_plan
from .bom import TIERS, Bom, PartsDB
from .delivery import CodeBundle, design_parameters
from .design import GantryParameters, PLATFORM_ID
from .risk import RiskAssessment
from .visuals import part_layout
from .wiring import (
    build_panel_layout,
    build_wiring_diagram,
    panel_svg,
    wiring_svg,
)

__all__ = [
    "build_dossier_html",
    "export_production_document",
    "machine_image_data_uris",
]


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _money(value: float) -> str:
    return f"₦{value:,.0f}"


# ------------------------------------------------------------ machine views

_PART_COLOURS = [
    "#6b7580", "#7d8791", "#0094a8", "#8a929a", "#8a929a",
    "#00b3c8", "#bf993f", "#d94d33", "#9aa3ab",
]


def robot_outline_svg(params: GantryParameters) -> str:
    """The robot teacher as a dimensioned front drawing, from the
    shared outline geometry (``visuals.robot_outline``) -- the
    same figure the app draws, in the document's own medium."""
    from .visuals import robot_layout, robot_outline, robot_state_default

    layout = robot_layout(params)
    outline = robot_outline(layout, robot_state_default(params))
    width, height = 300.0, 400.0
    xs = [r[0] - r[2] / 2 for r in outline["rects"]]
    xs += [r[0] + r[2] / 2 for r in outline["rects"]]
    xs += [outline["station_x_m"] - 0.10, outline["station_x_m"] + 0.16]
    min_x, max_x = min(xs) - 0.03, max(xs) + 0.03
    min_y, max_y = -0.03, layout.height_m + 0.03
    scale = min(width / (max_x - min_x), height / (max_y - min_y))

    def px(v: float) -> float:
        return (v - min_x) * scale

    def py(v: float) -> float:
        return height - (v - min_y) * scale

    out = [
        f'<svg width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#101216"/>',
    ]
    for cx, cz, w, h, _kind in outline["rects"]:
        out.append(
            f'<rect x="{px(cx - w / 2):.1f}" y="{py(cz + h / 2):.1f}" '
            f'width="{max(w * scale, 2):.1f}" height="{max(h * scale, 2):.1f}" '
            f'fill="none" stroke="#8a929a" stroke-width="1.6"/>'
        )
    vx, vz, vw, vh = outline["visor"]
    out.append(
        f'<rect x="{px(vx - vw / 2):.1f}" y="{py(vz + vh / 2):.1f}" '
        f'width="{max(vw * scale, 2):.1f}" height="{max(vh * scale, 2):.1f}" '
        f'fill="#00E5FF"/>'
    )
    arm = outline["arm"]
    points = " ".join(f"{px(x):.1f},{py(z):.1f}" for x, z in arm)
    out.append(
        f'<polyline points="{points}" fill="none" stroke="#00E5FF" '
        f'stroke-width="2"/>'
    )
    for (x1, z1), (x2, z2) in outline["gripper"]:
        out.append(
            f'<line x1="{px(x1):.1f}" y1="{py(z1):.1f}" x2="{px(x2):.1f}" '
            f'y2="{py(z2):.1f}" stroke="#d94d33" stroke-width="2"/>'
        )
    dim_x = px(outline["station_x_m"] + 0.13)
    out.append(
        f'<line x1="{dim_x:.1f}" y1="{py(0):.1f}" x2="{dim_x:.1f}" '
        f'y2="{py(layout.height_m):.1f}" stroke="#7A838D" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{dim_x + 6:.1f}" y="{py(layout.height_m / 2):.1f}" '
        f'fill="#7A838D" font-size="11">'
        f'ROBOT {layout.height_m * 1000.0:.0f} mm</text>'
    )
    out.append(
        '<text x="8" y="16" fill="#7A838D" font-size="11">'
        "ROBOT TEACHER — FRONT, AS DESIGNED</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


def _projection_svg(params: GantryParameters, projection: str) -> str:
    """One orthographic drawing of the assembled machine from
    the design's own part placements -- the fallback when no GL
    renderer exists, and honest drafting either way."""
    parts = part_layout(params)
    axis = {"front": (0, 2), "side": (1, 2), "top": (0, 1)}[projection]
    width, height = 560.0, 400.0
    xs, ys = [], []
    for pl in parts:
        c, s = pl.center_mm, pl.size_mm
        xs += [c[axis[0]] - s[axis[0]] / 2, c[axis[0]] + s[axis[0]] / 2]
        ys += [c[axis[1]] - s[axis[1]] / 2, c[axis[1]] + s[axis[1]] / 2]
    if projection == "front":
        # The robot teacher stands in the front drawing too, at
        # its station to the right of the frame.
        from .visuals import robot_layout

        station_mm = robot_layout(params).station_x_m * 1000.0
        xs += [station_mm - 60, station_mm + 60]
    min_x, max_x = min(xs) - 30, max(xs) + 30
    min_y, max_y = min(ys) - 30, max(ys) + 30
    scale = min(width / (max_x - min_x), height / (max_y - min_y))

    def px(v: float) -> float:
        return (v - min_x) * scale

    def py(v: float) -> float:
        return height - (v - min_y) * scale

    out = [
        f'<svg width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#101216"/>',
    ]
    for i, pl in enumerate(parts):
        c, s = pl.center_mm, pl.size_mm
        x0, y0 = px(c[axis[0]] - s[axis[0]] / 2), py(c[axis[1]] + s[axis[1]] / 2)
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" '
            f'width="{max(s[axis[0]] * scale, 2):.1f}" '
            f'height="{max(s[axis[1]] * scale, 2):.1f}" fill="none" '
            f'stroke="{_PART_COLOURS[i % len(_PART_COLOURS)]}" stroke-width="1.6"/>'
        )
    if projection == "front":
        from .visuals import (
            robot_layout,
            robot_outline,
            robot_state_default,
        )

        outline = robot_outline(
            robot_layout(params), robot_state_default(params)
        )
        for cx, cz, w, h, _kind in outline["rects"]:
            out.append(
                f'<rect x="{px(cx * 1000.0 - w * 500.0):.1f}" '
                f'y="{py(cz * 1000.0 + h * 500.0):.1f}" '
                f'width="{max(w * 1000.0 * scale, 2):.1f}" '
                f'height="{max(h * 1000.0 * scale, 2):.1f}" fill="none" '
                f'stroke="#8a929a" stroke-width="1.6"/>'
            )
        points = " ".join(
            f"{px(x * 1000.0):.1f},{py(z * 1000.0):.1f}"
            for x, z in outline["arm"]
        )
        out.append(
            f'<polyline points="{points}" fill="none" stroke="#00E5FF" '
            f'stroke-width="2"/>'
        )
    out.append(
        f'<text x="8" y="16" fill="#7A838D" font-size="11">'
        f'{_esc(projection.upper())} VIEW — AS DESIGNED</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def _internals_svg(params: GantryParameters) -> str:
    """The machine taken apart: exploded placements, labelled --
    the dossier form of the app's INTERNALS view."""
    parts = part_layout(params)
    width, height = 860.0, 460.0
    label_w = 250.0
    xs = [pl.exploded_center_mm[0] - pl.size_mm[0] / 2 for pl in parts]
    xs += [pl.exploded_center_mm[0] + pl.size_mm[0] / 2 for pl in parts]
    zs = [pl.exploded_center_mm[2] - pl.size_mm[2] / 2 for pl in parts]
    zs += [pl.exploded_center_mm[2] + pl.size_mm[2] / 2 for pl in parts]
    min_x, max_x = min(xs) - 40, max(xs) + 40
    min_z, max_z = min(zs) - 40, max(zs) + 40
    scale = min(
        (width - label_w) / (max_x - min_x), height / (max_z - min_z)
    )

    def px(v: float) -> float:
        return (v - min_x) * scale

    def py(v: float) -> float:
        return height - (v - min_z) * scale

    out = [
        f'<svg width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#101216"/>',
        '<text x="8" y="16" fill="#7A838D" font-size="11">'
        "INTERNALS — PARTS SEPARATED, AS DESIGNED</text>",
    ]
    for i, pl in enumerate(parts):
        cx, _cy, cz = pl.exploded_center_mm
        sw, _sd, sh = pl.size_mm
        x0, y0 = px(cx - sw / 2), py(cz + sh / 2)
        colour = _PART_COLOURS[i % len(_PART_COLOURS)]
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" '
            f'width="{max(sw * scale, 2):.1f}" '
            f'height="{max(sh * scale, 2):.1f}" fill="none" '
            f'stroke="{colour}" stroke-width="1.6"/>'
        )
        out.append(
            f'<text x="{px(max_x) + 10:.1f}" y="{py(cz) + 4:.1f}" '
            f'fill="#D7DDE3" font-size="11">'
            f'{i + 1:02d} {_esc(pl.name.upper())}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")
    ).decode("ascii")


def machine_image_data_uris(
    params: GantryParameters, *, use_renderer: bool = True
) -> dict[str, str]:
    """The machine from every side, as embeddable data URIs:
    front / side / top rendered by the Stage 1 machine renderer
    when a GL backend exists, drafting projections from the
    design's placements when it does not; internals always the
    exploded drawing. Never raises -- a dossier without a working
    renderer still shows the whole machine."""
    images: dict[str, str] = {}
    rendered = False
    if use_renderer:
        try:
            from . import visuals

            if visuals.renderer_available():
                renderer = visuals.MachineRenderer(
                    params, width=640, height=480
                )
                try:
                    timeline = visuals.MachineTimeline.rest(params)
                    state = timeline.state_at(0.0)
                    # At rest the robot holds the load at its
                    # gate -- the dossier's pictures show the
                    # teaching machine whole: apparatus + robot.
                    robot = timeline.robot_state_at(0.0)
                    import cv2

                    for view in ("front", "side", "top"):
                        frame = renderer.render(state, view, robot)
                        ok, buf = cv2.imencode(
                            ".png",
                            cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
                        )
                        if not ok:
                            raise ValueError("PNG encode failed")
                        images[view] = (
                            "data:image/png;base64,"
                            + base64.b64encode(buf.tobytes()).decode("ascii")
                        )
                    rendered = True
                finally:
                    renderer.close()
        except Exception:
            rendered = False
            images = {}
    if not rendered:
        for view in ("front", "side", "top"):
            images[view] = _svg_uri(_projection_svg(params, view))
    images["internals"] = _svg_uri(_internals_svg(params))
    return images


# ----------------------------------------------------------------- dossier

_CSS = """
:root { color-scheme: dark; }
body { background:#17191D; color:#D7DDE3; font-family:Consolas,'DejaVu Sans Mono',monospace; margin:0; padding:0; }
body::before { content:""; position:fixed; inset:0; pointer-events:none;
  background-image:linear-gradient(#262B31 1px,transparent 1px),linear-gradient(90deg,#262B31 1px,transparent 1px);
  background-size:24px 24px; opacity:.35; }
header { border-bottom:1px solid #343A42; padding:16px 22px; position:relative; }
header h1 { color:#00E5FF; font-size:19px; margin:0 0 4px; letter-spacing:1px; }
.dim { color:#7A838D; font-size:12px; }
main { padding:6px 22px 22px; position:relative; max-width:1060px; }
h2 { color:#00E5FF; font-size:14px; letter-spacing:1px; border-bottom:1px solid #343A42;
  padding-bottom:6px; margin:26px 0 12px; }
h3 { color:#D7DDE3; font-size:13px; margin:16px 0 6px; }
p, li { font-size:13px; line-height:1.55; }
.meta { color:#7A838D; font-size:12.5px; }
.meta b { color:#D7DDE3; }
table { border-collapse:collapse; margin:10px 0 16px; font-size:12.5px; }
th, td { border:1px solid #343A42; padding:5px 9px; text-align:left; }
th { color:#00E5FF; }
td.num, th.num { text-align:right; }
.views { display:flex; flex-wrap:wrap; gap:14px; }
.views figure { margin:0; }
.views img, .views svg { border:1px solid #343A42; background:#101216; max-width:100%; }
figcaption { color:#7A838D; font-size:11.5px; margin-top:4px; letter-spacing:.5px; }
svg.wiring, svg.panel { border:1px solid #343A42; max-width:100%; }
.step { border:1px solid #343A42; background:#1B1E24; padding:10px 14px; margin:10px 0; }
.step h3 { margin:0 0 4px; color:#00E5FF; font-size:12.5px; }
pre { background:#101216; border:1px solid #343A42; padding:12px; overflow:auto;
  font-size:11.5px; line-height:1.45; }
details summary { cursor:pointer; color:#00E5FF; font-size:12.5px; margin:8px 0; }
footer { border-top:1px solid #343A42; padding:10px 22px; color:#7A838D; font-size:12px; position:relative; }
"""


def _bom_table(bom: Bom) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_esc(line.name)}</td>"
        f'<td class="num">{line.quantity}</td>'
        f'<td class="num">{_money(line.unit_price_ngn)}</td>'
        f'<td class="num">{_money(line.line_total_ngn)}</td>'
        "</tr>"
        for line in bom.lines
    )
    return (
        f"<h3>TIER — {_esc(bom.tier.upper())} · TOTAL {_money(bom.total_ngn)}</h3>"
        "<table><thead><tr><th>MATERIAL</th><th class='num'>QTY</th>"
        "<th class='num'>UNIT PRICE</th><th class='num'>LINE TOTAL</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def build_dossier_html(
    *,
    project_title: str,
    template_data: dict,
    params: GantryParameters,
    tier_boms: dict[str, Bom],
    assessment: RiskAssessment,
    code: CodeBundle,
    lesson=None,
    db: PartsDB | None = None,
    assembly_tier: str = "prototype",
    images: Optional[dict[str, str]] = None,
) -> str:
    """Assemble the production document. Pure builder -- the
    sign-off gate lives in :func:`export_production_document`
    (and in the shell, before any dialog), exactly as the signed
    package splits its gate the same way."""
    db = db if db is not None else PartsDB()
    practical = template_data.get("practical", {}) or {}
    hint = template_data.get("machine_design_hint", {}) or {}
    title = str(practical.get("title", "Untitled practical"))
    subject = str(practical.get("subject", ""))
    platform = str(template_data.get("platform_id") or PLATFORM_ID)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if images is None:
        images = machine_image_data_uris(params)
    plan: AssemblyPlan = build_assembly_plan(
        params, assembly_tier, db=db
    )
    wiring = build_wiring_diagram(params, tier_boms[assembly_tier], db=db)
    panel = build_panel_layout(template_data)

    # -- what it does: the lesson's steps when a lesson exists,
    #    else the template's own steps (same words, less polish).
    if lesson is not None:
        task_steps = [
            (step.title, step.narration) for step in lesson.steps
        ]
        voice_labels = []
        for step in lesson.steps:
            if step.audio and step.audio.label \
                    and step.audio.label not in voice_labels:
                voice_labels.append(step.audio.label)
    else:
        raw_steps = sorted(
            template_data.get("steps", []) or [],
            key=lambda s: s.get("order", 0),
        )
        task_steps = [
            (str(s.get("title", "")), str(s.get("narration", "")))
            for s in raw_steps
        ]
        voice_labels = []
    task_html = "".join(
        f"<li><b>{_esc(step_title)}</b>"
        + (f" — {_esc(step_text)}" if step_text else "")
        + "</li>"
        for step_title, step_text in task_steps
    )
    voice_note = ""
    if voice_labels:
        voice_note = (
            '<p class="meta"><b>Lesson voice:</b> '
            + _esc(" · ".join(voice_labels))
            + "</p>"
        )
    description = str(hint.get("description", "") or "")
    outcome_spec = str(practical.get("outcome_spec", "") or "")

    # -- coupling steps.
    coupling_html = ""
    for step in plan.steps:
        coupling_html += (
            '<div class="step">'
            f"<h3>STEP {step.index} OF {step.total} — "
            f"{_esc(step.part_name.upper())}</h3>"
            f"<p>{_esc(step.text)}</p>"
            f'<p class="meta">The part is {_esc(step.approach_text)}; '
            f"materials for this step: {_money(step.lines_total_ngn)} "
            f"at {_esc(plan.tier)} prices.</p>"
            "</div>"
        )

    # -- materials: every tier, itemised, with its total.
    materials_html = "".join(
        _bom_table(tier_boms[tier]) for tier in TIERS if tier in tier_boms
    )

    # -- safety: the assessment itself + its sign-off.
    hazards_html = "".join(
        "<tr>"
        f"<td>{_esc(h.description)}</td>"
        f"<td>{_esc(h.severity)} / {_esc(h.likelihood)}</td>"
        f"<td>{_esc(h.mitigation)}</td>"
        "</tr>"
        for h in assessment.hazards
    )
    if assessment.signed_by:
        signoff = (
            f"SIGNED BY {_esc(assessment.signed_by)} — "
            f"{_esc(assessment.signed_at or '')} — EXPORT OPEN"
        )
    else:
        signoff = "NOT SIGNED — EXPORT STAYS CLOSED"

    # -- controller code: summary + the checked source itself.
    params_data = design_parameters(params)
    params_rows = "".join(
        f"<tr><td>{_esc(key)}</td><td>{_esc(value)}</td></tr>"
        for key, value in sorted(params_data.items())
    )
    motions = code.controller.count("kernel.execute")
    code_summary = (
        "<table><tbody>"
        f"<tr><td>Controller safety check</td><td>"
        f"{'PASSED' if code.controller_report.passed else 'FAILED'}</td></tr>"
        f"<tr><td>Control panel safety check</td><td>"
        f"{'PASSED' if code.panel_report.passed else 'FAILED'}</td></tr>"
        f"<tr><td>Motion commands in the sequence</td><td>{motions}</td></tr>"
        f"<tr><td>Controller source</td><td>{len(code.controller)} characters</td></tr>"
        f"<tr><td>Control panel source</td><td>{len(code.control_panel)} characters</td></tr>"
        "</tbody></table>"
    )

    views_html = "".join(
        f'<figure><img src="{images[key]}" alt="{key} view">'
        f"<figcaption>{key.upper()} VIEW</figcaption></figure>"
        for key in ("front", "side", "top", "internals")
        if key in images
    )
    robot_svg = robot_outline_svg(params)
    low, high = params.suspension_range_mm
    dims = (
        f"SPAN {params.span_mm:.0f} mm · HEIGHT {params.height_mm:.0f} mm · "
        f"SECTION {params.section_mm:.0f} mm · BASE DEPTH "
        f"{params.base_depth_mm:.0f} mm · SUSPENSION RANGE {low:.0f}–{high:.0f} mm"
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(project_title)} — Mimforge production document</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>PRODUCTION DOCUMENT — {_esc(project_title)}</h1>
<div class="dim">{_esc(title)} · {_esc(subject)} · PLATFORM {_esc(platform)} · GENERATED {_esc(generated_at)}</div>
<div class="dim">SIGN-OFF: {_esc(signoff)}</div>
</header>
<main>
<h2>THE MACHINE — EVERY SIDE</h2>
<div class="views">{views_html}</div>
<p class="meta">{_esc(dims)}</p>
<p>The machine complete: outside from the front, the side and above, and
taken apart inside — every part the materials list names, drawn from the
same design the app builds.</p>
<h2>THE ROBOT TEACHER</h2>
<div class="views"><figure>{robot_svg}<figcaption>ROBOT — FRONT ELEVATION</figcaption></figure></div>
<p>The robot stands at the machine's right-front corner and performs
the practical with the class: it holds the load, releases it, points
to the reference position while readings are taken, and works the
carriage for each adjustment — the same figure the app shows
performing in Playback and Simulate, drawn here to scale.</p>
<h2>WHAT IT DOES</h2>
<p>{_esc(description)}</p>
<p>{_esc(outcome_spec)}</p>
{voice_note}
<ol>{task_html}</ol>
<h2>HOW IT IS BUILT — STEP-BY-STEP COUPLING</h2>
<p class="meta">Assembly priced at the {_esc(plan.tier.upper())} tier;
the full materials for every tier are listed below. Total materials
at this tier: {_money(plan.total_ngn)}.</p>
{coupling_html}
<h2>WIRING — HOW IT WORKS</h2>
{wiring_svg(wiring)}
<h2>CONTROL PANEL</h2>
{panel_svg(panel)}
<h2>MATERIALS — EVERYTHING NEEDED</h2>
{materials_html}
<h2>SAFETY — RISK ASSESSMENT</h2>
<p class="meta">SIGN-OFF: {_esc(signoff)} · DESIGN FINGERPRINT {_esc((assessment.design_fingerprint or '')[:16])}</p>
<table><thead><tr><th>HAZARD</th><th>SEVERITY / LIKELIHOOD</th><th>CONTROL</th></tr></thead>
<tbody>{hazards_html}</tbody></table>
<h2>CONTROLLER CODE</h2>
{code_summary}
<h3>DESIGN PARAMETERS</h3>
<table><tbody>{params_rows}</tbody></table>
<details><summary>CONTROLLER SOURCE — AS GENERATED AND CHECKED</summary>
<pre>{_esc(code.controller)}</pre></details>
<details><summary>CONTROL PANEL SOURCE — AS GENERATED AND CHECKED</summary>
<pre>{_esc(code.control_panel)}</pre></details>
</main>
<footer>Generated by Mimforge — production document for {_esc(project_title)} ·
self-contained: no network, no external files. Prices are the parts
database's local-market estimates.</footer>
</body>
</html>
"""
    return doc


def export_production_document(
    *,
    out_path: str | Path,
    assessment: RiskAssessment,
    **build_kwargs,
) -> Path:
    """Write the production document. The sign-off gate runs
    FIRST -- before any rendering or writing -- exactly as the
    signed package's gate does: ``risk.ExportBlocked`` propagates
    until a named teacher's valid sign-off exists."""
    risk.assert_export_ready(assessment)
    doc = build_dossier_html(assessment=assessment, **build_kwargs)
    out = Path(out_path)
    out.write_text(doc, encoding="utf-8")
    return out
