"""Step-by-step coupling (next-stage plan, Stage 3): the BUILD IT
sequence, generated from the design itself.

The sequence is *generated*, not authored: the platform assembly
table in :mod:`mimforge.design` says in what order the designed
parts are fitted, how each travels into place, what must already
stand before it, and what fastens it; the parts database
(:mod:`mimforge.bom`) says what each step's materials are called
and what they cost in the selected tier. Change the design or a
price and the sequence's cards follow, because nothing here is a
second copy of that data.

Buildability is proved, not assumed: :func:`validate_assembly`
walks the sequence in order and refuses a table in which a part
is fitted before the parts it stands on. Every designed part
appears exactly once -- a part the table forgot fails the build
here, in tests, and in the Gate v2 probe, never silently in the
player.

Narration reuses the Stage 2 speech layer: the steps are shimmed
through a lesson package so the coupling sequence is rendered by
the same engines, with the same per-step fallback and the same
plain-words voice labels, at BUILD IT open time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .bom import Bom, BomLine, PartsDB, generate_bom
from .design import (
    APPROACH_TEXT,
    ASSEMBLY_TABLE,
    AssemblyEntry,
    GantryDesign,
    GantryParameters,
    build_gantry,
)

__all__ = [
    "AssemblyPlan",
    "AssemblyStep",
    "build_assembly_plan",
    "narrate_assembly_steps",
    "validate_assembly",
]


def _money(value: float) -> str:
    return f"₦{value:,.0f}"


# ------------------------------------------------------------------ steps


@dataclass
class AssemblyStep:
    """One coupling step: one designed part, fitted once.

    ``bom_lines`` are the selected tier's purchasable lines that
    ARE this part (traced through the BOM's CAD part ids);
    ``fastener_lines`` are the consumable lines that fasten it,
    with ``fastener_count`` pieces used at this step. A line that
    covers several designed parts (a pair sold as one line) is
    listed on each of its parts' steps and marked ``shared`` --
    it is still one purchase, and the plan's total is always the
    tier BOM's own total, never a sum over steps.
    """

    index: int  # 1-based, in fitting order
    total: int
    part_id: str
    part_name: str
    action: str
    approach: str
    approach_text: str
    requires: tuple[str, ...] = ()
    fastener_count: int = 0
    bom_lines: list[BomLine] = field(default_factory=list)
    fastener_lines: list[BomLine] = field(default_factory=list)
    shared: bool = False
    audio: object = None  # speech.StepAudio once narrated

    @property
    def need_text(self) -> str:
        """The step's shopping line: what the builder picks up
        before starting this step, with the tier's prices."""
        items: list[str] = []
        for line in self.bom_lines:
            note = " (one purchase covers both)" if self.shared else ""
            items.append(
                f"{line.name} ×{line.quantity} — {_money(line.line_total_ngn)}{note}"
            )
        for line in self.fastener_lines:
            items.append(
                f"{line.name} — use {self.fastener_count} pieces "
                f"(kit {_money(line.line_total_ngn)}, shared across steps)"
            )
        return "; ".join(items) if items else "nothing to buy — it is already on the bench"

    @property
    def text(self) -> str:
        """The full step instruction, in the plan's pattern."""
        return (
            f"Step {self.index} of {self.total}: {self.action}. "
            f"You need: {self.need_text}."
        )

    @property
    def narration(self) -> str:
        """What the voice reads for this step: the instruction,
        with the approach named so a builder listening with their
        hands full hears how the part travels."""
        return (
            f"Step {self.index} of {self.total}. {self.action}. "
            f"The part is {self.approach_text}. "
            f"You need: {self.need_text}."
        )

    @property
    def lines_total_ngn(self) -> float:
        """This step's own materials at the tier's prices (the
        fasteners kit is a shared purchase and is not summed in --
        it is priced on the card as a kit, once)."""
        return sum(line.line_total_ngn for line in self.bom_lines)


@dataclass
class AssemblyPlan:
    """A whole coupling sequence for one design at one tier."""

    params: GantryParameters
    tier: str
    steps: list[AssemblyStep] = field(default_factory=list)
    bom: Optional[Bom] = None

    @property
    def total_ngn(self) -> float:
        """The build's materials total: the tier BOM's own total
        (a shared line is one purchase, counted once)."""
        return self.bom.total_ngn if self.bom is not None else 0.0

    def step_for_part(self, part_id: str) -> AssemblyStep:
        for step in self.steps:
            if step.part_id == part_id:
                return step
        raise KeyError(f"no assembly step for part {part_id!r}")


# -------------------------------------------------------------- validation


def validate_assembly(
    design: GantryDesign,
    table: tuple[AssemblyEntry, ...] = ASSEMBLY_TABLE,
) -> None:
    """Prove a table against a built design: every designed part
    appears exactly once, orders are 1..N in fitting order, every
    approach is one the views can animate, and the sequence is
    buildable -- a part is never fitted before the parts it
    requires. Raises ValueError naming the first defect found."""
    part_ids = design.part_ids
    seen: list[str] = []
    for entry in table:
        if entry.part_id in seen:
            raise ValueError(f"assembly table fits {entry.part_id!r} twice")
        seen.append(entry.part_id)
    missing = [pid for pid in part_ids if pid not in seen]
    if missing:
        raise ValueError(f"assembly table never fits: {missing}")
    extra = [pid for pid in seen if pid not in part_ids]
    if extra:
        raise ValueError(f"assembly table fits parts the design lacks: {extra}")
    ordered = sorted(table, key=lambda e: e.order)
    if [e.order for e in ordered] != list(range(1, len(table) + 1)):
        raise ValueError("assembly orders must run 1..N with no gaps")
    placed: set[str] = set()
    for entry in ordered:
        if entry.approach not in APPROACH_TEXT:
            raise ValueError(
                f"part {entry.part_id!r}: unknown approach {entry.approach!r}"
            )
        unmet = [req for req in entry.requires if req not in placed]
        if unmet:
            raise ValueError(
                f"part {entry.part_id!r} is fitted before its supports: {unmet}"
            )
        placed.add(entry.part_id)


# -------------------------------------------------------------- generation


def build_assembly_plan(
    params: GantryParameters,
    tier: str,
    db: PartsDB | None = None,
    design: GantryDesign | None = None,
) -> AssemblyPlan:
    """Generate the coupling sequence for one design at one tier.

    The step for a part carries the tier's BOM lines traced to
    that part (so a tier switch re-prices every card from the
    same database the Design panel reads), and the consumable
    lines the table says fasten it."""
    design = design if design is not None else build_gantry(params)
    validate_assembly(design)
    db = db if db is not None else PartsDB()
    bom = generate_bom(db, tier, design.part_ids)
    by_part: dict[str, list[BomLine]] = {}
    for line in bom.lines:
        traced = _line_cad_parts(db, line)
        for cad_id in traced:
            by_part.setdefault(cad_id, []).append(line)
    by_id = {line.part_id: line for line in bom.lines}
    names = {part.part_id: part.name for part in design.parts}
    ordered = sorted(ASSEMBLY_TABLE, key=lambda e: e.order)
    total = len(ordered)
    steps: list[AssemblyStep] = []
    for entry in ordered:
        lines = list(by_part.get(entry.part_id, []))
        shared = any(len(_line_cad_parts(db, line)) > 1 for line in lines)
        fastener_lines = [
            by_id[fid] for fid in entry.fastener_bom_ids if fid in by_id
        ]
        steps.append(
            AssemblyStep(
                index=entry.order,
                total=total,
                part_id=entry.part_id,
                part_name=names.get(entry.part_id, entry.part_id),
                action=entry.action,
                approach=entry.approach,
                approach_text=APPROACH_TEXT[entry.approach],
                requires=tuple(entry.requires),
                fastener_count=entry.fastener_count,
                bom_lines=lines,
                fastener_lines=fastener_lines,
                shared=shared,
            )
        )
    return AssemblyPlan(params=params, tier=tier, steps=steps, bom=bom)


def _line_cad_parts(db: PartsDB, line: BomLine) -> tuple[str, ...]:
    """The CAD part ids a BOM line traces to (via the parts DB)."""
    part = db.parts.get(line.part_id)
    return tuple(part.cad_part_ids) if part is not None else ()


# --------------------------------------------------------------- narration


def narrate_assembly_steps(plan: AssemblyPlan, *, progress=None):
    """Render the coupling steps' voices through the Stage 2
    speech layer (preferred engine, per-step fallback, plain-words
    labels) and attach the audio to the steps. Returns the speech
    layer's report. Silent-safe exactly like a lesson: a step no
    engine can render simply stays silent and keeps its text."""
    from . import speech
    from .playback import LessonPackage, LessonStep

    shim = LessonPackage(
        title="Assembly — step-by-step coupling",
        subject="Machine assembly",
        template_id="assembly",
        steps=[
            LessonStep(
                order=step.index,
                title=step.action,
                narration=step.narration,
            )
            for step in plan.steps
        ],
    )
    report = speech.attach_narration(shim, progress=progress)
    audio_by_order = {step.order: step.audio for step in shim.steps}
    for step in plan.steps:
        step.audio = audio_by_order.get(step.index)
    return report
