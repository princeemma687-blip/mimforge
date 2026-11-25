"""Tiered bill of materials (plan Phase 3.2).

Prices are editable local-market estimates in naira, stored in the parts
database -- never hard-coded claims. Three tiers (plan section 5.1):
``prototype`` (prove the sequence in a classroom), ``professional``
(durable school rig), ``industrial`` (hardened, safety-relay path).
All tiers run the same generated controller logic and the same lesson;
tier changes materials, accuracy and durability, never the pedagogy.

Traceability rule: every BOM line traces to a CAD part id from
:mod:`mimforge.design` or to a declared consumable. Totals are always
recomputed from the database -- a price edit changes every tier that
uses the part.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TIERS = ("prototype", "professional", "industrial")


@dataclass
class Part:
    """One purchasable line in the parts database."""

    part_id: str
    name: str
    unit_price_ngn: float
    quantity: int = 1
    tiers: tuple[str, ...] = TIERS
    cad_part_ids: tuple[str, ...] = ()
    consumable: str = ""  # non-empty => declared consumable, not a CAD part

    def trace(self) -> str:
        """Where this line comes from: a CAD part or a consumable."""
        if self.cad_part_ids:
            return "cad:" + ",".join(self.cad_part_ids)
        if self.consumable:
            return "consumable:" + self.consumable
        return "untraced"


@dataclass
class BomLine:
    part_id: str
    name: str
    quantity: int
    unit_price_ngn: float
    line_total_ngn: float
    trace: str


@dataclass
class Bom:
    tier: str
    lines: list[BomLine] = field(default_factory=list)

    @property
    def total_ngn(self) -> float:
        return sum(line.line_total_ngn for line in self.lines)

    def untraced_lines(self) -> list[BomLine]:
        return [line for line in self.lines if line.trace == "untraced"]


def default_parts() -> list[Part]:
    """The Phase 3 parts database (editable estimates, NGN)."""
    return [
        # Frame -- one line per tier, same CAD parts, different material.
        Part("frame_uprights_proto", "Upright pair, MDF/plywood cut",
             8000, 1, ("prototype",), ("upright_left", "upright_right")),
        Part("frame_uprights_pro", "Upright pair, 2020 aluminium extrusion",
             24000, 1, ("professional",), ("upright_left", "upright_right")),
        Part("frame_uprights_ind", "Upright pair, anodised extrusion + steel",
             48000, 1, ("industrial",), ("upright_left", "upright_right")),
        Part("frame_beam_proto", "Top beam, MDF/plywood cut",
             5000, 1, ("prototype",), ("top_beam",)),
        Part("frame_beam_pro", "Top beam, 2020 aluminium extrusion",
             14000, 1, ("professional",), ("top_beam",)),
        Part("frame_beam_ind", "Top beam, anodised extrusion + steel",
             30000, 1, ("industrial",), ("top_beam",)),
        Part("frame_feet_proto", "Base feet pair, plywood",
             3000, 1, ("prototype",), ("foot_left", "foot_right")),
        Part("frame_feet_pro", "Base feet pair, extrusion + end plates",
             9000, 1, ("professional",), ("foot_left", "foot_right")),
        Part("frame_feet_ind", "Base feet pair, steel plate",
             20000, 1, ("industrial",), ("foot_left", "foot_right")),
        # Carriage + spool + release.
        Part("carriage_proto", "Carriage block, plywood + bushings",
             4500, 1, ("prototype",), ("carriage",)),
        Part("carriage_pro", "Carriage, extrusion + linear rail",
             22000, 1, ("professional",), ("carriage",)),
        Part("carriage_ind", "Carriage, machined + encoded drive",
             55000, 1, ("industrial",), ("carriage",)),
        Part("spool_proto", "Spool drum, 3D-printed PLA",
             2500, 1, ("prototype",), ("spool_drum",)),
        Part("spool_pro", "Spool drum, aluminium",
             8000, 1, ("professional",), ("spool_drum",)),
        Part("spool_ind", "Spool drum, steel + bearing",
             18000, 1, ("industrial",), ("spool_drum",)),
        Part("release_proto", "Release servo, SG90-class",
             4500, 1, ("prototype",), ("release_gate",)),
        Part("release_pro", "Release stepper + lead screw",
             18000, 1, ("professional",), ("release_gate",)),
        Part("release_ind", "Release, encoded motor",
             45000, 1, ("industrial",), ("release_gate",)),
        # Sensing + control + stop.
        Part("sensor_proto", "Timing camera, USB webcam",
             12000, 1, ("prototype",), ("sensor_bracket",)),
        Part("sensor_pro", "Timing sensor, optical fork",
             9500, 1, ("professional",), ("sensor_bracket",)),
        Part("sensor_ind", "Timing sensors, redundant pair",
             28000, 1, ("industrial",), ("sensor_bracket",)),
        Part("controller_proto", "Controller board, Arduino-class",
             15000, 1, ("prototype",), (),
             consumable="controller-board"),
        Part("controller_pro", "Controller board, microcontroller",
             28000, 1, ("professional",), (),
             consumable="controller-board"),
        Part("controller_ind", "Controller + safety relay",
             65000, 1, ("industrial",), (),
             consumable="controller-board"),
        Part("estop_proto", "Stop panel, latching switch + printed plate",
             6500, 1, ("prototype",), (),
             consumable="estop-panel"),
        Part("estop_pro", "Stop panel, enclosed",
             18000, 1, ("professional",), (),
             consumable="estop-panel"),
        Part("estop_ind", "Stop panel + safety relay",
             42000, 1, ("industrial",), (),
             consumable="estop-panel"),
        # Shared consumables (all tiers).
        Part("fasteners", "Fasteners kit (bolts, nuts, brackets)",
             5000, 1, TIERS, (), "fasteners-kit"),
        Part("suspension_line", "Suspension line, braided, 10 m",
             1500, 1, TIERS, (), "suspension-line"),
        Part("printed_scale", "Printed scale + labels",
             2000, 1, TIERS, (), "printed-scale"),
    ]


class PartsDB:
    """Editable parts database (JSON on disk, in-memory for tests)."""

    def __init__(self, parts: list[Part] | None = None):
        self.parts: dict[str, Part] = {
            p.part_id: p for p in (parts if parts is not None else default_parts())
        }

    def set_price(self, part_id: str, new_price_ngn: float) -> None:
        """Edit one price; every tier total recomputes from this DB."""
        if part_id not in self.parts:
            raise KeyError(f"unknown part: {part_id}")
        if new_price_ngn < 0:
            raise ValueError("price cannot be negative")
        old = self.parts[part_id]
        self.parts[part_id] = Part(
            part_id=old.part_id,
            name=old.name,
            unit_price_ngn=float(new_price_ngn),
            quantity=old.quantity,
            tiers=old.tiers,
            cad_part_ids=old.cad_part_ids,
            consumable=old.consumable,
        )

    def to_json(self) -> str:
        return json.dumps(
            [
                {
                    "part_id": p.part_id,
                    "name": p.name,
                    "unit_price_ngn": p.unit_price_ngn,
                    "quantity": p.quantity,
                    "tiers": list(p.tiers),
                    "cad_part_ids": list(p.cad_part_ids),
                    "consumable": p.consumable,
                }
                for p in self.parts.values()
            ],
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> "PartsDB":
        parts = []
        for row in json.loads(text):
            parts.append(
                Part(
                    part_id=row["part_id"],
                    name=row["name"],
                    unit_price_ngn=float(row["unit_price_ngn"]),
                    quantity=int(row.get("quantity", 1)),
                    tiers=tuple(row.get("tiers", TIERS)),
                    cad_part_ids=tuple(row.get("cad_part_ids", ())),
                    consumable=row.get("consumable", ""),
                )
            )
        return cls(parts)

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_json(), encoding="utf-8")
        return out

    @classmethod
    def load(cls, path: str | Path) -> "PartsDB":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def generate_bom(db: PartsDB, tier: str, cad_part_ids: list[str]) -> Bom:
    """Build one tier's BOM. Every line must trace to a CAD part or a
    declared consumable, and every CAD part must be covered by a line."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier!r} (expected one of {TIERS})")
    lines: list[BomLine] = []
    covered: set[str] = set()
    for part in db.parts.values():
        if tier not in part.tiers:
            continue
        trace = part.trace()
        if trace == "untraced":
            raise ValueError(f"part {part.part_id} has no trace (no CAD part, no consumable)")
        covered.update(part.cad_part_ids)
        lines.append(
            BomLine(
                part_id=part.part_id,
                name=part.name,
                quantity=part.quantity,
                unit_price_ngn=part.unit_price_ngn,
                line_total_ngn=part.unit_price_ngn * part.quantity,
                trace=trace,
            )
        )
    missing = [cid for cid in cad_part_ids if cid not in covered]
    if missing:
        raise ValueError(f"CAD parts with no BOM line for tier {tier}: {missing}")
    return Bom(tier=tier, lines=sorted(lines, key=lambda line: line.part_id))
