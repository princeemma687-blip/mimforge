"""Lesson playback (plan Phase 6.1).

A ``LessonPackage`` is the self-contained, engine-free form of a
finished practical: the teacher-approved steps, the readings table,
the fitted graph, and a *precomputed* replay trajectory. Nothing in
a package needs a model, a simulation engine, or a network at
playback time -- that is what makes it playable on a low-spec school
PC. The package is plain JSON data, so it can be exported as a
single self-contained HTML file (``export_html_lesson``) that plays
in any browser offline, or loaded into the in-app player
(``mimforge.ui.playback.LessonPlayer``).

All content (step wording, table columns, graph labels, the derived
constant's formula) comes from the template and the pipeline run
that produced it. This module carries no practical-specific
knowledge: no apparatus names, no plotted relationship, no expected
value.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import PracticalTemplate, VerificationRun

# Default seconds a step stays on screen when the template gives no
# duration hint. Kept short enough for a classroom replay; the
# teacher can change it per step in template data.
DEFAULT_STEP_SECONDS = 8.0

# Cap on replay points stored in a package: a full-resolution track
# is thousands of points; the replay is a picture, not measurement
# data, so a uniform downsample is safe and keeps the HTML small.
MAX_REPLAY_POINTS = 600


# ------------------------------------------------------------------- data


@dataclass
class LessonStep:
    order: int
    title: str
    narration: str = ""
    expected_observation: str = ""
    check_question: str = ""
    safety_notes: list[str] = field(default_factory=list)
    duration_s: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "title": self.title,
            "narration": self.narration,
            "expected_observation": self.expected_observation,
            "check_question": self.check_question,
            "safety_notes": list(self.safety_notes),
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LessonStep":
        return cls(
            order=int(data["order"]),
            title=data["title"],
            narration=data.get("narration", ""),
            expected_observation=data.get("expected_observation", ""),
            check_question=data.get("check_question", ""),
            safety_notes=list(data.get("safety_notes", [])),
            duration_s=data.get("duration_s"),
        )


@dataclass
class LessonReplay:
    """Precomputed 2-D replay track: (t, x, y) points, already sampled.

    The player draws this polyline progressively; it never runs a
    physics engine. ``x_label`` / ``y_label`` are display strings
    from the template (for example a length in metres).
    """

    label: str
    sample_hz: float
    points: list[tuple[float, float, float]] = field(default_factory=list)
    x_label: str = "x"
    y_label: str = "y"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "sample_hz": self.sample_hz,
            "points": [[t, x, y] for t, x, y in self.points],
            "x_label": self.x_label,
            "y_label": self.y_label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LessonReplay":
        return cls(
            label=data["label"],
            sample_hz=float(data["sample_hz"]),
            points=[tuple(p) for p in data.get("points", [])],
            x_label=data.get("x_label", "x"),
            y_label=data.get("y_label", "y"),
        )

    def validate(self) -> None:
        if self.sample_hz <= 0:
            raise ValueError("replay sample rate must be positive")
        if len(self.points) < 2:
            raise ValueError("replay needs at least 2 points")
        prev_t = None
        for t, _, _ in self.points:
            if prev_t is not None and t < prev_t:
                raise ValueError("replay points must be in time order")
            prev_t = t

    @classmethod
    def from_points(
        cls,
        points: list[tuple[float, float, float]],
        *,
        label: str,
        sample_hz: float,
        x_label: str = "x",
        y_label: str = "y",
        max_points: int = MAX_REPLAY_POINTS,
    ) -> "LessonReplay":
        """Build a replay from a full-resolution track, downsampling
        uniformly when it exceeds ``max_points`` (endpoints kept)."""
        if len(points) > max_points:
            step = (len(points) - 1) / (max_points - 1)
            picked = [points[int(round(i * step))] for i in range(max_points)]
            points = picked
        return cls(
            label=label, sample_hz=sample_hz, points=list(points),
            x_label=x_label, y_label=y_label,
        )


@dataclass
class LessonTable:
    """A readings table: column definitions + row values.

    Column keys come from the template's observation spec; row keys
    must be a subset of the column keys (a row may legitimately omit
    a column that does not apply).
    """

    columns: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"columns": self.columns, "rows": self.rows}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LessonTable":
        return cls(
            columns=list(data.get("columns", [])),
            rows=list(data.get("rows", [])),
        )

    def validate(self) -> None:
        if not self.columns:
            raise ValueError("table needs at least one column")
        keys = {c["key"] for c in self.columns}
        for row in self.rows:
            unknown = set(row) - keys
            if unknown:
                raise ValueError(
                    f"table row has columns not in the spec: {sorted(unknown)}"
                )


@dataclass
class LessonGraph:
    """A fitted straight-line graph: plotted points + the fit line."""

    x_label: str
    y_label: str
    points: list[tuple[float, float]] = field(default_factory=list)
    slope: Optional[float] = None
    intercept: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_label": self.x_label,
            "y_label": self.y_label,
            "points": [[x, y] for x, y in self.points],
            "slope": self.slope,
            "intercept": self.intercept,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LessonGraph":
        return cls(
            x_label=data["x_label"],
            y_label=data["y_label"],
            points=[tuple(p) for p in data.get("points", [])],
            slope=data.get("slope"),
            intercept=data.get("intercept"),
            notes=data.get("notes", ""),
        )

    def validate(self) -> None:
        if len(self.points) < 2:
            raise ValueError("graph needs at least 2 plotted points")
        if self.slope is None or self.intercept is None:
            raise ValueError("graph needs a fitted slope and intercept")


@dataclass
class LessonPackage:
    """One complete, engine-free lesson, ready to play or export."""

    title: str
    subject: str
    template_id: str
    steps: list[LessonStep] = field(default_factory=list)
    syllabus_refs: list[str] = field(default_factory=list)
    table: Optional[LessonTable] = None
    graph: Optional[LessonGraph] = None
    replay: Optional[LessonReplay] = None
    outcome_summary: dict[str, str] = field(default_factory=dict)
    precautions: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("lesson needs a title")
        if not self.steps:
            raise ValueError("lesson needs at least one step")
        orders = [s.order for s in self.steps]
        if orders != sorted(orders) or len(set(orders)) != len(orders):
            raise ValueError("lesson steps must be in unique, ascending order")
        for step in self.steps:
            if not step.title.strip():
                raise ValueError("every lesson step needs a title")
            if step.duration_s is not None and step.duration_s <= 0:
                raise ValueError("step duration must be positive")
        if self.table is not None:
            self.table.validate()
        if self.graph is not None:
            self.graph.validate()
        if self.replay is not None:
            self.replay.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "subject": self.subject,
            "template_id": self.template_id,
            "steps": [s.to_dict() for s in self.steps],
            "syllabus_refs": list(self.syllabus_refs),
            "table": self.table.to_dict() if self.table else None,
            "graph": self.graph.to_dict() if self.graph else None,
            "replay": self.replay.to_dict() if self.replay else None,
            "outcome_summary": dict(self.outcome_summary),
            "precautions": list(self.precautions),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LessonPackage":
        return cls(
            title=data["title"],
            subject=data["subject"],
            template_id=data["template_id"],
            steps=[LessonStep.from_dict(s) for s in data.get("steps", [])],
            syllabus_refs=list(data.get("syllabus_refs", [])),
            table=LessonTable.from_dict(data["table"]) if data.get("table") else None,
            graph=LessonGraph.from_dict(data["graph"]) if data.get("graph") else None,
            replay=LessonReplay.from_dict(data["replay"]) if data.get("replay") else None,
            outcome_summary=dict(data.get("outcome_summary", {})),
            precautions=list(data.get("precautions", [])),
            provenance=dict(data.get("provenance", {})),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "LessonPackage":
        return cls.from_dict(json.loads(text))

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def total_seconds(self) -> float:
        return sum(
            s.duration_s if s.duration_s is not None else DEFAULT_STEP_SECONDS
            for s in self.steps
        )


# ------------------------------------------------------------ assembling


def build_lesson(
    template: PracticalTemplate,
    *,
    table: Optional[LessonTable] = None,
    graph: Optional[LessonGraph] = None,
    replay: Optional[LessonReplay] = None,
    outcome_summary: Optional[dict[str, str]] = None,
    verification_run: Optional[VerificationRun] = None,
    generated_by: str = "mimforge",
) -> LessonPackage:
    """Assemble a lesson package from a template and the pipeline
    outputs for one demonstration. Steps come from the template in
    order; the outcome summary is taken from the verification run
    when one is supplied (caller text overrides it)."""
    steps = [
        LessonStep(
            order=s.order,
            title=s.title,
            narration=s.narration,
            expected_observation=s.expected_observation,
            check_question=s.check_question,
            safety_notes=list(s.safety_notes),
            duration_s=s.duration_hint_s,
        )
        for s in sorted(template.steps, key=lambda s: s.order)
    ]
    summary: dict[str, str] = dict(outcome_summary or {})
    if verification_run is not None:
        summary.setdefault("verification_run", verification_run.id)
        summary.setdefault("verification_passed", str(verification_run.passed))
        if verification_run.outcome_result:
            summary.setdefault("outcome_result", verification_run.outcome_result)
        for key, value in verification_run.discrepancy_metrics.items():
            summary.setdefault(f"metric_{key}", f"{value:.4g}")
        if verification_run.adjustments:
            summary.setdefault(
                "adjustments", "; ".join(verification_run.adjustments)
            )
    package = LessonPackage(
        title=template.practical.title,
        subject=template.practical.subject,
        template_id=template.id,
        steps=steps,
        syllabus_refs=list(template.practical.syllabus_refs),
        table=table,
        graph=graph,
        replay=replay,
        outcome_summary=summary,
        precautions=list(template.precautions),
        provenance={
            "generated_by": generated_by,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "template_id": template.id,
            "engine": "precomputed-replay",
        },
    )
    package.validate()
    return package


# ------------------------------------------------------- HTML export


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _json_payload(package: LessonPackage) -> str:
    """The package as JSON for the in-page player. ``<`` is escaped
    so a stray ``</script>`` inside template text can never close
    the script block."""
    return json.dumps(package.to_dict(), ensure_ascii=True).replace("<", "\\u003c")


_CSS = """
:root { color-scheme: dark; }
body { background:#17191D; color:#D7DDE3; font-family:Consolas,'DejaVu Sans Mono',monospace; margin:0; padding:0; }
body::before { content:""; position:fixed; inset:0; pointer-events:none;
  background-image:linear-gradient(#262B31 1px,transparent 1px),linear-gradient(90deg,#262B31 1px,transparent 1px);
  background-size:24px 24px; opacity:.35; }
header { border-bottom:1px solid #343A42; padding:14px 20px; position:relative; }
header h1 { color:#00E5FF; font-size:18px; margin:0 0 4px; letter-spacing:1px; }
header .dim { color:#7A838D; font-size:12px; }
main { display:flex; gap:0; position:relative; }
nav { width:260px; border-right:1px solid #343A42; padding:12px; flex:none; }
nav h2, section h2 { color:#00E5FF; font-size:13px; letter-spacing:1px; }
nav ol { list-style:none; padding:0; margin:0; }
nav li { padding:8px; border:1px solid transparent; cursor:pointer; font-size:13px; }
nav li.active { border-color:#00E5FF; background:#20242A; }
nav li.done { color:#7A838D; }
section { flex:1; padding:16px 20px; min-width:0; }
section h2 { margin-top:0; }
.narration { font-size:15px; line-height:1.6; white-space:pre-wrap; }
.meta { color:#7A838D; font-size:13px; margin:10px 0; }
.meta b { color:#D7DDE3; }
.controls button { background:#20242A; color:#D7DDE3; border:1px solid #343A42;
  font:inherit; padding:8px 16px; margin-right:8px; cursor:pointer; }
.controls button:hover { border-color:#00E5FF; color:#00E5FF; }
.controls button:disabled { opacity:.4; cursor:default; }
table { border-collapse:collapse; margin:12px 0; font-size:13px; }
th, td { border:1px solid #343A42; padding:6px 10px; text-align:right; }
th { color:#00E5FF; text-align:left; }
canvas#replay { background:#20242A; border:1px solid #343A42; width:100%; max-width:640px; }
svg.graph { background:#20242A; border:1px solid #343A42; }
footer { border-top:1px solid #343A42; padding:10px 20px; color:#7A838D; font-size:12px; position:relative; }
"""

_JS = """
const DATA = __PAYLOAD__;
let idx = 0, playing = false, timer = null, replayAnim = null;
const stepEl = document.getElementById('step');
function showStep(i) {
  idx = i;
  const s = DATA.steps[i];
  document.getElementById('step-title').textContent = (i+1) + ' / ' + DATA.steps.length + ' — ' + s.title;
  document.getElementById('step-narration').textContent = s.narration || '(no narration)';
  document.getElementById('step-obs').textContent = s.expected_observation || '—';
  document.getElementById('step-check').textContent = s.check_question || '—';
  const notes = s.safety_notes || [];
  document.getElementById('step-safety').textContent = notes.length ? notes.join(' | ') : '—';
  document.querySelectorAll('nav li').forEach((li, j) => {
    li.classList.toggle('active', j === i);
    li.classList.toggle('done', j < i);
  });
  document.getElementById('prev').disabled = (i === 0);
  document.getElementById('next').disabled = (i === DATA.steps.length - 1);
  document.getElementById('status').textContent = playing ? 'STATUS: PLAYING' : 'STATUS: PAUSED — STEP ' + (i+1) + '/' + DATA.steps.length;
}
function stepSeconds(s) { return (s.duration_s != null && s.duration_s > 0) ? s.duration_s : 8; }
function play() {
  if (idx >= DATA.steps.length - 1 && !playing) { idx = -1; }
  playing = true;
  document.getElementById('play').disabled = true;
  document.getElementById('pause').disabled = false;
  next();
}
function next() {
  if (!playing) return;
  if (idx >= DATA.steps.length - 1) { stop(true); return; }
  showStep(idx + 1);
  timer = setTimeout(next, stepSeconds(DATA.steps[idx]) * 1000);
}
function pause() {
  playing = false; clearTimeout(timer);
  document.getElementById('play').disabled = false;
  document.getElementById('pause').disabled = true;
  showStep(idx);
}
function stop(finished) {
  playing = false; clearTimeout(timer);
  document.getElementById('play').disabled = false;
  document.getElementById('pause').disabled = true;
  document.getElementById('status').textContent = finished ? 'STATUS: FINISHED — LESSON COMPLETE' : 'STATUS: STOPPED';
  if (!finished) showStep(0);
}
function drawReplay(progress) {
  const cv = document.getElementById('replay');
  if (!cv || !DATA.replay) return;
  const ctx = cv.getContext('2d');
  const pts = DATA.replay.points;
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (!pts.length) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of pts) { minX = Math.min(minX, p[1]); maxX = Math.max(maxX, p[1]); minY = Math.min(minY, p[2]); maxY = Math.max(maxY, p[2]); }
  const pad = 20, sx = (cv.width - 2*pad) / Math.max(maxX - minX, 1e-9), sy = (cv.height - 2*pad) / Math.max(maxY - minY, 1e-9);
  const sc = Math.min(sx, sy);
  const X = (x) => pad + (x - minX) * sc, Y = (y) => cv.height - pad - (y - minY) * sc;
  ctx.strokeStyle = '#00E5FF'; ctx.lineWidth = 2; ctx.beginPath();
  const n = Math.max(2, Math.floor(pts.length * progress));
  ctx.moveTo(X(pts[0][1]), Y(pts[0][2]));
  for (let i = 1; i < n; i++) ctx.lineTo(X(pts[i][1]), Y(pts[i][2]));
  ctx.stroke();
  const last = pts[n-1];
  ctx.fillStyle = '#00E5FF'; ctx.beginPath(); ctx.arc(X(last[1]), Y(last[2]), 5, 0, 7); ctx.fill();
}
function playReplay() {
  if (!DATA.replay) return;
  const start = performance.now(), dur = 6000;
  cancelAnimationFrame(replayAnim);
  function frame(now) {
    const p = Math.min(1, (now - start) / dur);
    drawReplay(p);
    if (p < 1) replayAnim = requestAnimationFrame(frame);
  }
  replayAnim = requestAnimationFrame(frame);
}
document.getElementById('play').addEventListener('click', play);
document.getElementById('pause').addEventListener('click', pause);
document.getElementById('stop').addEventListener('click', () => stop(false));
document.getElementById('prev').addEventListener('click', () => { pause(); showStep(Math.max(0, idx - 1)); });
document.getElementById('next').addEventListener('click', () => { pause(); showStep(Math.min(DATA.steps.length - 1, idx + 1)); });
document.querySelectorAll('nav li').forEach((li, j) => li.addEventListener('click', () => { pause(); showStep(j); }));
const rp = document.getElementById('play-replay');
if (rp) rp.addEventListener('click', playReplay);
showStep(0);
drawReplay(1);
"""


def _table_html(table: LessonTable) -> str:
    head = "".join(
        f"<th>{_esc(c.get('label', c.get('key', '')))}"
        + (f" ({_esc(c['unit'])})" if c.get("unit") else "")
        + "</th>"
        for c in table.columns
    )
    body = ""
    for row in table.rows:
        body += "<tr>" + "".join(
            f"<td>{_esc(row.get(c['key'], ''))}</td>" for c in table.columns
        ) + "</tr>\n"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _graph_svg(graph: LessonGraph) -> str:
    xs = [p[0] for p in graph.points]
    ys = [p[1] for p in graph.points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    w, h, pad = 560, 320, 44

    def px(x: float) -> float:
        return pad + (x - min_x) / span_x * (w - 2 * pad)

    def py(y: float) -> float:
        return h - pad - (y - min_y) / span_y * (h - 2 * pad)

    circles = "".join(
        f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" fill="#00E5FF"/>'
        for x, y in graph.points
    )
    x0, x1 = min_x, max_x
    y0 = graph.slope * x0 + graph.intercept
    y1 = graph.slope * x1 + graph.intercept
    fit = (
        f'<line x1="{px(x0):.1f}" y1="{py(y0):.1f}" '
        f'x2="{px(x1):.1f}" y2="{py(y1):.1f}" stroke="#D7DDE3" stroke-width="2"/>'
    )
    return (
        f'<svg class="graph" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f"{fit}{circles}"
        f'<text x="{pad}" y="{h - 12}" fill="#7A838D" font-size="12">{_esc(graph.x_label)}</text>'
        f'<text x="8" y="{pad - 8}" fill="#7A838D" font-size="12">{_esc(graph.y_label)}</text>'
        f"</svg>"
        f'<p class="meta">Fitted line: slope {_esc(graph.slope)} · intercept {_esc(graph.intercept)}'
        + (f" · {_esc(graph.notes)}" if graph.notes else "")
        + "</p>"
    )


def export_html_lesson(package: LessonPackage, path: str | Path) -> Path:
    """Write the lesson as one self-contained HTML file.

    No external resources: no scripts, styles, fonts or images are
    fetched from anywhere. The file plays offline in any browser.
    Returns the written path.
    """
    package.validate()
    out = Path(path)
    steps_nav = "".join(
        f"<li>{_esc(i + 1)}. {_esc(s.title)}</li>"
        for i, s in enumerate(package.steps)
    )
    outcome = "".join(
        f"<p class='meta'><b>{_esc(k)}:</b> {_esc(v)}</p>"
        for k, v in package.outcome_summary.items()
    )
    table_html = _table_html(package.table) if package.table else ""
    graph_html = _graph_svg(package.graph) if package.graph else ""
    replay_html = ""
    if package.replay is not None:
        replay_html = (
            '<h2>REPLAY — PRECOMPUTED TRACK</h2>'
            f"<p class='meta'>{_esc(package.replay.label)} · "
            f"{len(package.replay.points)} points · "
            f"{_esc(package.replay.sample_hz)} Hz · "
            f"x: {_esc(package.replay.x_label)} · y: {_esc(package.replay.y_label)}</p>"
            '<canvas id="replay" width="640" height="360"></canvas><br>'
            '<div class="controls"><button id="play-replay" type="button">'
            "▶ REPLAY TRACK</button></div>"
        )
    precautions = "".join(
        f"<li>{_esc(p)}</li>" for p in package.precautions
    )
    refs = "".join(f"<li>{_esc(r)}</li>" for r in package.syllabus_refs)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(package.title)} — Mimforge lesson</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>{_esc(package.title)}</h1>
<div class="dim">{_esc(package.subject)} · TEMPLATE {_esc(package.template_id)} · {_esc(package.step_count)} STEPS · {_esc(round(package.total_seconds))} s</div>
</header>
<main>
<nav><h2>STEPS</h2><ol>{steps_nav}</ol></nav>
<section id="step">
<h2 id="step-title"></h2>
<div class="controls">
<button id="play" type="button">▶ PLAY</button>
<button id="pause" type="button" disabled>❚❚ PAUSE</button>
<button id="stop" type="button">■ STOP</button>
<button id="prev" type="button">◀ PREV</button>
<button id="next" type="button">NEXT ▶</button>
<span id="status" class="meta">STATUS: IDLE</span>
</div>
<p class="narration" id="step-narration"></p>
<p class="meta"><b>Expected observation:</b> <span id="step-obs"></span></p>
<p class="meta"><b>Check:</b> <span id="step-check"></span></p>
<p class="meta"><b>Safety:</b> <span id="step-safety"></span></p>
{replay_html}
<h2>READINGS</h2>
{table_html}
<h2>GRAPH</h2>
{graph_html}
<h2>OUTCOME</h2>
{outcome}
<h2>PRECAUTIONS</h2>
<ul>{precautions}</ul>
<h2>SYLLABUS REFERENCES</h2>
<ul>{refs}</ul>
</section>
</main>
<footer>Generated by Mimforge — lesson package {_esc(package.template_id)} · precomputed replay, no engine, no network. Provenance: {_esc(package.provenance.get('generated_by', ''))} · {_esc(package.provenance.get('generated_at', ''))}</footer>
<script type="application/json" id="lesson-data">{_json_payload(package)}</script>
<script>{_JS.replace('__PAYLOAD__', 'JSON.parse(document.getElementById("lesson-data").textContent)')}</script>
</body>
</html>
"""
    out.write_text(doc, encoding="utf-8")
    return out
