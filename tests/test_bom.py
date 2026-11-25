"""Phase 3.2 tests: tiered BOM (plan test T3.2)."""

import pytest

from mimforge.bom import TIERS, PartsDB, generate_bom
from mimforge.design import GantryParameters, build_gantry


def _design_part_ids() -> list[str]:
    return build_gantry(GantryParameters()).part_ids


def test_three_tier_totals_ordered_and_positive():
    db = PartsDB()
    totals = {tier: generate_bom(db, tier, _design_part_ids()).total_ngn for tier in TIERS}
    assert all(total > 0 for total in totals.values())
    assert totals["prototype"] < totals["professional"] < totals["industrial"]


def test_every_line_traces_to_cad_part_or_consumable():
    db = PartsDB()
    for tier in TIERS:
        bom = generate_bom(db, tier, _design_part_ids())
        assert bom.untraced_lines() == []
        assert all(
            line.trace.startswith(("cad:", "consumable:"))
            for line in bom.lines
        )


def test_price_change_updates_every_tier_total():
    db = PartsDB()
    before = {tier: generate_bom(db, tier, _design_part_ids()).total_ngn for tier in TIERS}
    db.set_price("fasteners", 6000)  # shared consumable, all three tiers
    after = {tier: generate_bom(db, tier, _design_part_ids()).total_ngn for tier in TIERS}
    for tier in TIERS:
        assert after[tier] == before[tier] + 1000


def test_missing_cad_coverage_is_an_error():
    db = PartsDB()
    # Drop the sensor lines: the sensor bracket then has no BOM line.
    db.parts = {
        pid: part
        for pid, part in db.parts.items()
        if not pid.startswith("sensor_")
    }
    with pytest.raises(ValueError, match="sensor_bracket"):
        generate_bom(db, "prototype", _design_part_ids())


def test_parts_db_json_round_trip(tmp_path):
    db = PartsDB()
    db.set_price("fasteners", 6000)
    path = db.save(tmp_path / "parts.json")
    reloaded = PartsDB.load(path)
    assert reloaded.parts["fasteners"].unit_price_ngn == 6000
    assert generate_bom(reloaded, "prototype", _design_part_ids()).total_ngn == (
        generate_bom(db, "prototype", _design_part_ids()).total_ngn
    )


def test_unknown_tier_and_part_rejected():
    db = PartsDB()
    with pytest.raises(ValueError):
        generate_bom(db, "deluxe", _design_part_ids())
    with pytest.raises(KeyError):
        db.set_price("no-such-part", 100)
    with pytest.raises(ValueError):
        db.set_price("fasteners", -5)
