"""Generic core schema for Mimforge (plan section 1.5).

Only generic entities live here. A concrete practical -- any subject, any
syllabus -- is expressed as *data* conforming to these types (a
``PracticalTemplate``), never as code in this module. One
``ObservationSpec`` type deliberately covers every recording format the
target syllabuses use: readings tables, test/observation/inference
tables, drawings with magnification, and identification tables.

Standard library only (dataclasses + enum): no third-party dependency is
needed to load, validate or exchange the schema.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional


class MotionPrimitiveType(enum.Enum):
    """The generic vocabulary of machine actions a step can require."""

    REACH = "reach"
    GRASP = "grasp"
    RELEASE = "release"
    POUR = "pour"
    ROTATE = "rotate"
    TRANSLATE = "translate"
    HOLD = "hold"
    OSCILLATE = "oscillate"
    READ = "read"
    CUT = "cut"
    HEAT = "heat"
    MIX = "mix"


class ObservationKind(enum.Enum):
    """The generic recording formats an outcome can take."""

    TABLE = "table"
    TEST_OBSERVATION_INFERENCE = "test_observation_inference"
    DRAWING = "drawing"
    IDENTIFICATION = "identification"
    MEASUREMENT = "measurement"


@dataclass
class ApparatusItem:
    name: str
    quantity: int = 1
    specification: str = ""
    consumable: bool = False


@dataclass
class HazardProfile:
    """Subject-agnostic hazard summary carried by practicals and cases."""

    severity: str = "low"  # low | medium | high (free text by design)
    hazards: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class MotionPrimitive:
    type: MotionPrimitiveType
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trajectory:
    """A timed 2-D track extracted from a demonstration (t, x, y)."""

    label: str
    points: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class Demonstration:
    id: str
    practical_id: str
    video_hash: str  # SHA-256 of the untouched original recording
    trajectories: list[Trajectory] = field(default_factory=list)
    transcript: str = ""
    keyframes: list[str] = field(default_factory=list)


@dataclass
class Step:
    id: str
    order: int
    title: str
    narration: str = ""
    motion_primitives: list[MotionPrimitive] = field(default_factory=list)
    apparatus_refs: list[str] = field(default_factory=list)
    expected_observation: str = ""
    check_question: str = ""
    safety_notes: list[str] = field(default_factory=list)
    duration_hint_s: Optional[float] = None


@dataclass
class ObservationColumn:
    key: str
    label: str
    unit: str = ""
    precision: Optional[int] = None  # decimal places, where prescribed


@dataclass
class GraphSpec:
    x_quantity: str
    y_quantity: str
    form: str = "linear"  # linear | curve | ... (template-defined)
    notes: str = ""


@dataclass
class ToleranceSpec:
    """Expected outcome + the band inside which it earns credit."""

    expected_value: Optional[float] = None
    band_percent: Optional[float] = None
    absolute_band: Optional[float] = None


@dataclass
class ObservationSpec:
    """What a learner must record, and how it is processed and judged."""

    kind: ObservationKind
    columns: list[ObservationColumn] = field(default_factory=list)
    derived_quantities: list[str] = field(default_factory=list)
    graph: Optional[GraphSpec] = None
    tolerance: ToleranceSpec = field(default_factory=ToleranceSpec)
    precision_notes: str = ""


@dataclass
class Practical:
    id: str
    title: str
    subject: str
    syllabus_refs: list[str] = field(default_factory=list)
    apparatus: list[ApparatusItem] = field(default_factory=list)
    hazard_profile: HazardProfile = field(default_factory=HazardProfile)
    outcome_spec: str = ""
    observation_spec: Optional[ObservationSpec] = None
    template_id: str = ""


@dataclass
class PracticalTemplate:
    """One concrete practical, as data: a practical + its steps."""

    id: str
    practical: Practical
    steps: list[Step] = field(default_factory=list)
    platform_id: str = ""
    precautions: list[str] = field(default_factory=list)


@dataclass
class BomTierVariant:
    tier: str  # prototype | professional | industrial
    description: str = ""


@dataclass
class MachineDesign:
    platform_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    end_effectors: list[str] = field(default_factory=list)
    bom_tier_variants: list[BomTierVariant] = field(default_factory=list)
    cad_ref: str = ""
    controller_ref: str = ""


@dataclass
class VerificationRun:
    id: str
    practical_id: str
    sim_trajectory_ref: str = ""
    discrepancy_metrics: dict[str, float] = field(default_factory=dict)
    outcome_result: str = ""
    passed: bool = False
    adjustments: list[str] = field(default_factory=list)


@dataclass
class SafetyLimits:
    """Controller-enforced caps. Defaults follow the plan's safety design:
    a bench platform reachable by learners is speed-capped in the
    controller itself, not merely in the authoring app."""

    max_tool_speed_mm_s: float = 250.0
    max_force_n: Optional[float] = None
    max_payload_kg: Optional[float] = None
    notes: str = ""


@dataclass
class SafetyCase:
    hazard_profile: HazardProfile = field(default_factory=HazardProfile)
    limits: SafetyLimits = field(default_factory=SafetyLimits)
    interlocks: list[str] = field(default_factory=list)
    risk_assessment: str = ""
    signed_by_teacher: bool = False
    package_signature: str = ""
