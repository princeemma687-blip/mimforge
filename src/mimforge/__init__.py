"""Mimforge core engine.

Generic, practical-agnostic data models for demonstration-driven
teaching-machine design. This package contains ONLY generic entities:
every concrete practical enters the system as template *data* (see
``mimforge.templates``), never as special-case code. See
``docs/SCOPE_FREEZE.md`` for the separation rule this enforces.
"""

import os as _os
import sys as _sys

# MuJoCo locks its GL backend at import time, so the choice must be
# made before anything imports it -- this package init is the one
# place guaranteed to run first. On headless Linux (no display),
# pick a software backend so the machine view (Stage 1) can render
# offscreen; on Windows and on any machine with a display, MuJoCo's
# own default is left alone. An explicit MUJOCO_GL from the
# environment always wins.
#
# Backend choice on headless Linux. Source checkout: OSMesa --
# proven with this project's dev/test environment. Frozen build:
# never OSMesa -- its backend imports PyOpenGL at MuJoCo import
# time, and PyOpenGL's platform loader cannot bind its library
# inside a PyInstaller bundle (found by the Stage 1 clean-room
# self-test: `import mujoco` itself failed). A frozen build tries
# EGL instead (MuJoCo's EGL binding loads libEGL directly, no
# PyOpenGL); where EGL cannot initialise either, MuJoCo's default
# stands, the renderer probe reports unavailable, and the machine
# view falls back to its canvas -- the designed behaviour.
if (
    not _os.environ.get("MUJOCO_GL")
    and _sys.platform.startswith("linux")
    and not _os.environ.get("DISPLAY")
):
    if getattr(_sys, "frozen", False):
        try:
            import ctypes as _ctypes

            _ctypes.CDLL("libEGL.so.1")
            _os.environ["MUJOCO_GL"] = "egl"
        except OSError:
            pass
    else:
        _os.environ["MUJOCO_GL"] = "osmesa"

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
