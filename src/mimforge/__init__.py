"""Mimforge core engine.

Generic, practical-agnostic data models for demonstration-driven
teaching-machine design. This package contains ONLY generic entities:
every concrete practical enters the system as template *data* (see
``mimforge.templates``), never as special-case code. See
``docs/SCOPE_FREEZE.md`` for the separation rule this enforces.
"""

from .adjust import AdjustmentAttempt, AdjustmentResult, auto_adjust
from .allowlist import AllowlistReport, check_source
from .codegen import generate_control_panel, generate_controller
from .config import FULL_PROFILE, LEAN_PROFILE, RuntimeProfile
from .discrepancy import (
    DiscrepancyFinding,
    DiscrepancyReport,
    assess as assess_discrepancy,
)
from .models import (
    ApparatusItem,
    BomTierVariant,
    Demonstration,
    GraphSpec,
    HazardProfile,
    MachineDesign,
    MotionPrimitive,
    MotionPrimitiveType,
    ObservationColumn,
    ObservationKind,
    ObservationSpec,
    Practical,
    PracticalTemplate,
    SafetyCase,
    SafetyLimits,
    Step,
    ToleranceSpec,
    Trajectory,
    VerificationRun,
)
from .outcome import evaluate_derived, evaluate_formula, linear_fit
from .playback import (
    DEFAULT_STEP_SECONDS,
    LessonGraph,
    LessonPackage,
    LessonReplay,
    LessonStep,
    LessonTable,
    build_lesson,
    export_html_lesson,
)
from .projects import IntegrityError, Project, ProjectError, create_project, list_projects, open_project
from .simulation import SimResult, simulate_suspension
from .safety import (
    AuditEntry,
    CommandOutcome,
    CommandResult,
    MotionCommand,
    SafetyKernel,
)
from .signing import (
    PackageError,
    VerificationError,
    export_package,
    generate_keypair,
    load_verified_package,
    verify_package,
)

__version__ = "0.0.1"

__all__ = [
    "FULL_PROFILE",
    "LEAN_PROFILE",
    "AdjustmentAttempt",
    "AdjustmentResult",
    "AllowlistReport",
    "ApparatusItem",
    "AuditEntry",
    "BomTierVariant",
    "CommandOutcome",
    "CommandResult",
    "DEFAULT_STEP_SECONDS",
    "Demonstration",
    "DiscrepancyFinding",
    "DiscrepancyReport",
    "GraphSpec",
    "HazardProfile",
    "IntegrityError",
    "LessonGraph",
    "LessonPackage",
    "LessonReplay",
    "LessonStep",
    "LessonTable",
    "MachineDesign",
    "MotionCommand",
    "MotionPrimitive",
    "MotionPrimitiveType",
    "ObservationColumn",
    "ObservationKind",
    "ObservationSpec",
    "PackageError",
    "Practical",
    "PracticalTemplate",
    "Project",
    "ProjectError",
    "RuntimeProfile",
    "SafetyCase",
    "SafetyKernel",
    "SafetyLimits",
    "SimResult",
    "Step",
    "ToleranceSpec",
    "Trajectory",
    "VerificationError",
    "VerificationRun",
    "assess_discrepancy",
    "auto_adjust",
    "build_lesson",
    "check_source",
    "create_project",
    "evaluate_derived",
    "evaluate_formula",
    "export_html_lesson",
    "export_package",
    "generate_control_panel",
    "generate_controller",
    "generate_keypair",
    "linear_fit",
    "list_projects",
    "load_verified_package",
    "open_project",
    "simulate_suspension",
    "verify_package",
]
