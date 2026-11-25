"""Practical templates, stored as DATA.

A template is a JSON document describing one concrete practical in terms
of the generic core schema (``mimforge.models``). All practical-specific
content lives here and only here; the core engine never hard-codes it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import (
    ApparatusItem,
    GraphSpec,
    HazardProfile,
    MotionPrimitive,
    MotionPrimitiveType,
    ObservationColumn,
    ObservationKind,
    ObservationSpec,
    Practical,
    PracticalTemplate,
    Step,
    ToleranceSpec,
)

_HERE = Path(__file__).parent


def load_template_data(name: str = "pendulum") -> dict[str, Any]:
    """Load a template's raw JSON data by name."""
    path = _HERE / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def observation_spec_from_data(data: dict[str, Any]) -> ObservationSpec:
    """Build the generic ObservationSpec for a template's data block."""
    graph = None
    if data.get("graph_spec"):
        g = data["graph_spec"]
        graph = GraphSpec(
            x_quantity=g["x_quantity"],
            y_quantity=g["y_quantity"],
            form=g.get("form", "linear"),
            notes=g.get("notes", ""),
        )
    tol = data.get("tolerance", {})
    return ObservationSpec(
        kind=ObservationKind(data["kind"]),
        columns=[
            ObservationColumn(
                key=c["key"],
                label=c["label"],
                unit=c.get("unit", ""),
                precision=c.get("precision"),
            )
            for c in data.get("columns", [])
        ],
        derived_quantities=list(data.get("derived_quantities", [])),
        graph=graph,
        tolerance=ToleranceSpec(
            expected_value=tol.get("expected_value"),
            band_percent=tol.get("band_percent"),
            absolute_band=tol.get("absolute_band"),
        ),
        precision_notes=data.get("precision_notes", ""),
    )


def template_from_data(data: dict[str, Any]) -> PracticalTemplate:
    """Build a generic PracticalTemplate from template data."""
    p = data["practical"]
    hp = p.get("hazard_profile", {})
    practical = Practical(
        id=p["id"],
        title=p["title"],
        subject=p["subject"],
        syllabus_refs=list(p.get("syllabus_refs", [])),
        apparatus=[
            ApparatusItem(
                name=a["name"],
                quantity=a.get("quantity", 1),
                specification=a.get("specification", ""),
                consumable=a.get("consumable", False),
            )
            for a in p.get("apparatus", [])
        ],
        hazard_profile=HazardProfile(
            severity=hp.get("severity", "low"),
            hazards=list(hp.get("hazards", [])),
            notes=hp.get("notes", ""),
        ),
        outcome_spec=p.get("outcome_spec", ""),
        observation_spec=(
            observation_spec_from_data(data["observation_spec"])
            if data.get("observation_spec")
            else None
        ),
        template_id=data["template_id"],
    )
    steps = [
        Step(
            id=s["id"],
            order=s["order"],
            title=s["title"],
            narration=s.get("narration", ""),
            motion_primitives=[
                MotionPrimitive(type=MotionPrimitiveType(mp["type"]))
                for mp in s.get("motion_primitives", [])
            ],
            apparatus_refs=list(s.get("apparatus_refs", [])),
            expected_observation=s.get("expected_observation", ""),
            check_question=s.get("check_question", ""),
            safety_notes=list(s.get("safety_notes", [])),
        )
        for s in data.get("steps", [])
    ]
    return PracticalTemplate(
        id=data["template_id"],
        practical=practical,
        steps=steps,
        platform_id=data.get("platform_id", ""),
        precautions=list(data.get("precautions", [])),
    )


def load_template(name: str = "pendulum") -> PracticalTemplate:
    return template_from_data(load_template_data(name))
