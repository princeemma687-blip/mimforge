"""Mimforge core engine.

Generic, practical-agnostic data models for demonstration-driven
teaching-machine design. This package contains ONLY generic entities:
every concrete practical enters the system as template *data* (see
``mimforge.templates``), never as special-case code. See
``docs/SCOPE_FREEZE.md`` for the separation rule this enforces.
"""

from .config import FULL_PROFILE, LEAN_PROFILE, RuntimeProfile
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
from .projects import IntegrityError, Project, ProjectError, create_project, list_projects, open_project
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
    "ApparatusItem",
    "AuditEntry",
    "BomTierVariant",
    "CommandOutcome",
    "CommandResult",
    "Demonstration",
    "GraphSpec",
    "HazardProfile",
    "IntegrityError",
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
    "Step",
    "ToleranceSpec",
    "Trajectory",
    "VerificationError",
    "VerificationRun",
    "create_project",
    "export_package",
    "generate_keypair",
    "list_projects",
    "load_verified_package",
    "open_project",
    "verify_package",
]
