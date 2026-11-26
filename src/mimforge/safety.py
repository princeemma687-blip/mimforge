"""Safety kernel (plan Phase 1, step 1.4; security design 4.1/4.3).

Every motion command a generated controller can issue passes through
this kernel. The kernel enforces the controller-level caps from the
project's safety limits, keeps a monitored stop state, and logs every
decision. Generated code may only call the primitive API exposed here;
it can never command a motor directly, so even faulty or hostile
generated code cannot exceed the kernel's caps.

Rules, in order:
1. While the monitored stop is latched, every motion command is refused.
2. A commanded speed above the cap is clamped to the cap and logged.
3. A commanded force above the cap is refused outright (no motion) and
   logged, and the stop is latched -- a force violation is treated as a
   fault, not a rounding error. A command carrying a force when the
   safety limits set NO force cap is refused the same way (fail
   closed), and so is any command with a non-finite speed, force or
   duration -- NaN defeats comparisons, so it is treated as a fault,
   never as "within caps".
4. Every accepted, clamped, refused or stopped command is appended to
   the audit log, which is the safeguarding record for a run.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .models import MotionPrimitiveType, SafetyLimits


class CommandOutcome(str, Enum):
    ACCEPTED = "accepted"
    CLAMPED = "clamped"
    REFUSED = "refused"
    STOPPED = "stopped"
    RESET = "reset"


@dataclass(frozen=True)
class MotionCommand:
    """One motion request from generated controller code."""

    primitive: MotionPrimitiveType
    speed_mm_s: float = 0.0
    force_n: Optional[float] = None
    duration_s: Optional[float] = None
    target: str = ""


@dataclass
class AuditEntry:
    timestamp_s: float
    outcome: CommandOutcome
    primitive: str
    detail: str


@dataclass
class CommandResult:
    outcome: CommandOutcome
    speed_mm_s: float  # the speed the kernel will actually allow (0 if refused)
    detail: str


class SafetyKernel:
    """Enforces caps + monitored stop for one machine session."""

    def __init__(self, limits: Optional[SafetyLimits] = None) -> None:
        self.limits = limits or SafetyLimits()
        # The caps are the safety case: a nonsensical cap (negative,
        # zero, NaN, infinite) must fail loudly at startup, never
        # silently become an absent or inverted limit at run time.
        for name, value in (
            ("max_tool_speed_mm_s", self.limits.max_tool_speed_mm_s),
            ("max_force_n", self.limits.max_force_n),
            ("max_payload_kg", self.limits.max_payload_kg),
        ):
            if value is None:
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    f"safety limit {name} must be a positive finite "
                    f"number, got {value!r}"
                )
        self._stopped = False
        self._audit: list[AuditEntry] = []

    # -- state -----------------------------------------------------------
    @property
    def stopped(self) -> bool:
        return self._stopped

    def audit_log(self) -> list[AuditEntry]:
        return list(self._audit)

    def trigger_stop(self, reason: str = "monitored stop requested") -> None:
        """Latch the monitored stop (physical E-stop or on-screen stop)."""
        self._stopped = True
        self._log(CommandOutcome.STOPPED, "", f"stop latched: {reason}")

    def reset(self, operator: str = "") -> None:
        """Deliberate teacher reset. Motion never resumes automatically."""
        self._stopped = False
        self._log(
            CommandOutcome.RESET,
            "",
            f"stop reset by operator {operator!r}; motion re-armed deliberately",
        )

    # -- command path ----------------------------------------------------
    def execute(self, command: MotionCommand) -> CommandResult:
        """Validate one motion command against the caps. Never raises for
        a refused command -- refusal IS the result, and it is logged."""
        if self._stopped:
            result = CommandResult(
                CommandOutcome.STOPPED, 0.0, "refused: monitored stop is latched"
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        # Non-finite values defeat every comparison below (NaN is
        # neither above nor below any cap), so they are a fault in
        # their own right: refuse and latch, like a force violation.
        if (
            not math.isfinite(command.speed_mm_s)
            or (command.force_n is not None and not math.isfinite(command.force_n))
            or (
                command.duration_s is not None
                and not math.isfinite(command.duration_s)
            )
        ):
            self._stopped = True
            result = CommandResult(
                CommandOutcome.REFUSED,
                0.0,
                "refused: a non-finite speed, force or duration is a "
                "fault, not a motion; stop latched",
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        if command.speed_mm_s < 0:
            result = CommandResult(
                CommandOutcome.REFUSED, 0.0, "refused: negative speed is not a motion"
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        if command.force_n is not None and self.limits.max_force_n is None:
            # Fail closed: a force the project's safety case never
            # limited must not run. Generated controllers command
            # speed only, so this bites only faulty/hostile code.
            self._stopped = True
            result = CommandResult(
                CommandOutcome.REFUSED,
                0.0,
                "refused: the command carries a force but the safety "
                "limits set no force cap; stop latched",
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        if (
            self.limits.max_force_n is not None
            and command.force_n is not None
            and command.force_n > self.limits.max_force_n
        ):
            self._stopped = True
            result = CommandResult(
                CommandOutcome.REFUSED,
                0.0,
                f"refused: force {command.force_n} N exceeds cap "
                f"{self.limits.max_force_n} N; stop latched",
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        if command.speed_mm_s > self.limits.max_tool_speed_mm_s:
            result = CommandResult(
                CommandOutcome.CLAMPED,
                self.limits.max_tool_speed_mm_s,
                f"clamped: speed {command.speed_mm_s} mm/s exceeds cap "
                f"{self.limits.max_tool_speed_mm_s} mm/s",
            )
            self._log(result.outcome, command.primitive.value, result.detail)
            return result
        result = CommandResult(
            CommandOutcome.ACCEPTED, command.speed_mm_s, "accepted within caps"
        )
        self._log(result.outcome, command.primitive.value, result.detail)
        return result

    # -- internals -------------------------------------------------------
    def _log(self, outcome: CommandOutcome, primitive: str, detail: str) -> None:
        self._audit.append(
            AuditEntry(
                timestamp_s=time.monotonic(),
                outcome=outcome,
                primitive=primitive,
                detail=detail,
            )
        )


# Re-exported for callers that build commands from the generic schema.
__all__ = [
    "AuditEntry",
    "CommandOutcome",
    "CommandResult",
    "MotionCommand",
    "SafetyKernel",
]
