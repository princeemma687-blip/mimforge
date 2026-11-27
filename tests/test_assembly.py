"""Stage 3 assembly engine: the coupling sequence is generated
from the design + the parts database, and it is buildable by
construction.

Pins:
- the platform assembly table covers every designed part exactly
  once, with orders 1..N and only approaches the views animate;
- validation refuses a table that fits a part before its supports
  (the sequence can never ask a builder to bolt a beam to air);
- every step's card lines are the selected tier's BOM lines for
  that part, at the BOM's own prices -- a tier switch re-prices
  the cards, and the plan total is the tier BOM's total;
- fasteners come from the parts database's fasteners line;
- narration attaches through the Stage 2 speech layer with its
  plain-words label (a fake engine stands in for the voices).
"""

from __future__ import annotations

import dataclasses
import io
import wave

import pytest

from mimforge import speech
from mimforge.assembly import (
    build_assembly_plan,
    narrate_assembly_steps,
    validate_assembly,
)
from mimforge.bom import TIERS, PartsDB, generate_bom
from mimforge.design import (
    ASSEMBLY_TABLE,
    GantryParameters,
    build_gantry,
)

PARAMS = GantryParameters()


def _design():
    return build_gantry(PARAMS)


# ------------------------------------------------------------------ table


def test_table_covers_the_design_exactly_once():
    validate_assembly(_design())  # must not raise
    table_ids = [entry.part_id for entry in ASSEMBLY_TABLE]
    assert sorted(table_ids) == sorted(_design().part_ids)
    assert len(table_ids) == len(set(table_ids)) == 9
    assert sorted(e.order for e in ASSEMBLY_TABLE) == list(range(1, 10))


def test_sequence_is_buildable_by_construction():
    placed: set[str] = set()
    for entry in sorted(ASSEMBLY_TABLE, key=lambda e: e.order):
        assert all(req in placed for req in entry.requires), (
            f"{entry.part_id} is fitted before {entry.requires}"
        )
        placed.add(entry.part_id)


def test_validate_rejects_a_part_fitted_before_its_supports():
    swapped = []
    for entry in ASSEMBLY_TABLE:
        if entry.part_id == "top_beam":
            swapped.append(dataclasses.replace(entry, order=3))
        elif entry.part_id == "upright_left":
            swapped.append(dataclasses.replace(entry, order=5))
        else:
            swapped.append(entry)
    with pytest.raises(ValueError, match="before its supports"):
        validate_assembly(_design(), tuple(swapped))


def test_validate_rejects_a_missing_part():
    table = tuple(
        e for e in ASSEMBLY_TABLE if e.part_id != "sensor_bracket"
    )
    with pytest.raises(ValueError, match="never fits"):
        validate_assembly(_design(), table)


def test_validate_rejects_an_unknown_approach():
    table = tuple(
        dataclasses.replace(e, approach="teleport")
        if e.part_id == "carriage"
        else e
        for e in ASSEMBLY_TABLE
    )
    with pytest.raises(ValueError, match="unknown approach"):
        validate_assembly(_design(), table)


# ------------------------------------------------------------------- plan


def test_plan_steps_follow_the_pattern():
    plan = build_assembly_plan(PARAMS, "prototype")
    assert len(plan.steps) == 9
    for i, step in enumerate(plan.steps, start=1):
        assert step.index == i and step.total == 9
        assert step.text.startswith(f"Step {i} of 9: ")
        assert "You need: " in step.text
        assert step.narration.startswith(f"Step {i} of 9.")
        assert step.approach_text in step.narration


def test_step_cards_match_the_bom_for_every_tier():
    db = PartsDB()
    design = _design()
    for tier in TIERS:
        bom = generate_bom(db, tier, design.part_ids)
        plan = build_assembly_plan(PARAMS, tier, db=db, design=design)
        assert plan.total_ngn == bom.total_ngn
        bom_by_id = {line.part_id: line for line in bom.lines}
        union: set[str] = set()
        for step in plan.steps:
            assert step.bom_lines, f"step {step.part_id} has no materials"
            for line in step.bom_lines:
                union.add(line.part_id)
                expected = bom_by_id[line.part_id]
                assert line.unit_price_ngn == expected.unit_price_ngn
                assert line.line_total_ngn == expected.line_total_ngn
                # The line must genuinely trace to this step's part.
                assert step.part_id in db.parts[line.part_id].cad_part_ids
        cad_lines = {
            line.part_id
            for line in bom.lines
            if db.parts[line.part_id].cad_part_ids
        }
        assert union == cad_lines


def test_tier_switch_reprices_the_cards():
    proto = build_assembly_plan(PARAMS, "prototype")
    pro = build_assembly_plan(PARAMS, "professional")
    ind = build_assembly_plan(PARAMS, "industrial")
    assert (proto.total_ngn, pro.total_ngn, ind.total_ngn) == (
        69500,
        159000,
        359500,
    )
    carriage_proto = proto.step_for_part("carriage")
    carriage_pro = pro.step_for_part("carriage")
    assert carriage_proto.bom_lines[0].unit_price_ngn == 4500
    assert carriage_pro.bom_lines[0].unit_price_ngn == 22000


def test_fasteners_come_from_the_kit_line():
    plan = build_assembly_plan(PARAMS, "prototype")
    total_pieces = 0
    for step in plan.steps:
        if step.fastener_count:
            assert [line.part_id for line in step.fastener_lines] == [
                "fasteners"
            ]
            total_pieces += step.fastener_count
        else:
            assert step.fastener_lines == []
    assert total_pieces == sum(e.fastener_count for e in ASSEMBLY_TABLE) == 19


def test_the_pair_line_is_shared_and_marked():
    plan = build_assembly_plan(PARAMS, "prototype")
    left = plan.step_for_part("upright_left")
    right = plan.step_for_part("upright_right")
    assert left.shared and right.shared
    assert left.bom_lines[0].part_id == right.bom_lines[0].part_id
    assert "one purchase covers both" in left.need_text
    # ... and the plan total still counts the pair once.
    db = PartsDB()
    bom = generate_bom(db, "prototype", _design().part_ids)
    assert plan.total_ngn == bom.total_ngn


# --------------------------------------------------------------- narration


class _FakeEngine:
    id = "fake-engine"
    voice = "fake"

    def synthesize(self, text: str):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x40\x1f" * 2205)  # 0.1 s of tone
        return buffer.getvalue(), 0.1


def test_narration_attaches_labelled_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(speech, "default_engine", lambda: _FakeEngine())
    plan = build_assembly_plan(PARAMS, "prototype")
    report = narrate_assembly_steps(plan)
    assert report.ai_steps == 9
    for step in plan.steps:
        assert step.audio is not None
        assert step.audio.label == speech.AI_VOICE_LABEL
        assert step.audio.source == "ai"
