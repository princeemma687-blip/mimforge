"""Phase 1, safety kernel: caps enforced, stop latched, everything logged."""

from mimforge.models import MotionPrimitiveType, SafetyLimits
from mimforge.safety import CommandOutcome, MotionCommand, SafetyKernel


def test_over_speed_command_is_clamped_and_logged():
    kernel = SafetyKernel(SafetyLimits(max_tool_speed_mm_s=250.0))
    result = kernel.execute(
        MotionCommand(MotionPrimitiveType.TRANSLATE, speed_mm_s=900.0)
    )
    assert result.outcome == CommandOutcome.CLAMPED
    assert result.speed_mm_s == 250.0
    assert any(e.outcome == CommandOutcome.CLAMPED for e in kernel.audit_log())


def test_over_force_command_is_refused_and_latches_stop():
    kernel = SafetyKernel(SafetyLimits(max_tool_speed_mm_s=250.0, max_force_n=20.0))
    result = kernel.execute(
        MotionCommand(MotionPrimitiveType.GRASP, speed_mm_s=50.0, force_n=80.0)
    )
    assert result.outcome == CommandOutcome.REFUSED
    assert result.speed_mm_s == 0.0
    assert kernel.stopped is True
    # While stopped, even a legal command is refused.
    again = kernel.execute(
        MotionCommand(MotionPrimitiveType.TRANSLATE, speed_mm_s=10.0)
    )
    assert again.outcome == CommandOutcome.STOPPED


def test_estop_blocks_motion_until_deliberate_reset():
    kernel = SafetyKernel()
    kernel.trigger_stop("teacher pressed the panel stop")
    assert kernel.stopped is True
    refused = kernel.execute(
        MotionCommand(MotionPrimitiveType.RELEASE, speed_mm_s=10.0)
    )
    assert refused.outcome == CommandOutcome.STOPPED
    kernel.reset(operator="teacher")
    accepted = kernel.execute(
        MotionCommand(MotionPrimitiveType.RELEASE, speed_mm_s=10.0)
    )
    assert accepted.outcome == CommandOutcome.ACCEPTED
    assert accepted.speed_mm_s == 10.0


def test_legal_command_accepted_and_audit_is_complete():
    kernel = SafetyKernel()
    kernel.execute(MotionCommand(MotionPrimitiveType.HOLD, speed_mm_s=0.0))
    kernel.execute(MotionCommand(MotionPrimitiveType.ROTATE, speed_mm_s=100.0))
    log = kernel.audit_log()
    assert len(log) == 2
    assert all(e.outcome == CommandOutcome.ACCEPTED for e in log)


# ------------------------------------------- full spec audit (2026-11-26)

import pytest  # noqa: E402


def test_nan_speed_is_a_fault_not_within_caps():
    """NaN defeats every cap comparison; the kernel must refuse it
    and latch the stop instead of accepting it 'within caps'."""
    kernel = SafetyKernel(SafetyLimits(max_tool_speed_mm_s=250.0))
    result = kernel.execute(
        MotionCommand(
            primitive=MotionPrimitiveType.TRANSLATE,
            speed_mm_s=float("nan"),
        )
    )
    assert result.outcome is CommandOutcome.REFUSED
    assert kernel.stopped


def test_nan_force_and_infinite_duration_are_faults():
    kernel = SafetyKernel(
        SafetyLimits(max_tool_speed_mm_s=250.0, max_force_n=20.0)
    )
    result = kernel.execute(
        MotionCommand(
            primitive=MotionPrimitiveType.TRANSLATE,
            speed_mm_s=10.0,
            force_n=float("nan"),
        )
    )
    assert result.outcome is CommandOutcome.REFUSED
    kernel2 = SafetyKernel(SafetyLimits(max_tool_speed_mm_s=250.0))
    result2 = kernel2.execute(
        MotionCommand(
            primitive=MotionPrimitiveType.TRANSLATE,
            speed_mm_s=10.0,
            duration_s=float("inf"),
        )
    )
    assert result2.outcome is CommandOutcome.REFUSED


def test_force_without_a_configured_cap_fails_closed():
    """A default kernel has no force cap; a command carrying a
    force must be refused, not waved through unlimited."""
    kernel = SafetyKernel()
    result = kernel.execute(
        MotionCommand(
            primitive=MotionPrimitiveType.TRANSLATE,
            speed_mm_s=10.0,
            force_n=1_000_000_000.0,
        )
    )
    assert result.outcome is CommandOutcome.REFUSED
    assert kernel.stopped


def test_force_within_a_configured_cap_is_accepted():
    kernel = SafetyKernel(
        SafetyLimits(max_tool_speed_mm_s=250.0, max_force_n=20.0)
    )
    result = kernel.execute(
        MotionCommand(
            primitive=MotionPrimitiveType.TRANSLATE,
            speed_mm_s=10.0,
            force_n=10.0,
        )
    )
    assert result.outcome is CommandOutcome.ACCEPTED


@pytest.mark.parametrize(
    "limits",
    [
        SafetyLimits(max_tool_speed_mm_s=-10.0),
        SafetyLimits(max_tool_speed_mm_s=0.0),
        SafetyLimits(max_tool_speed_mm_s=float("nan")),
        SafetyLimits(max_force_n=-1.0),
        SafetyLimits(max_payload_kg=float("inf")),
    ],
)
def test_nonsensical_limits_fail_at_startup(limits):
    with pytest.raises(ValueError):
        SafetyKernel(limits)


def test_reset_is_logged_as_a_reset_not_an_acceptance():
    kernel = SafetyKernel()
    kernel.trigger_stop("test")
    kernel.reset(operator="teacher")
    outcomes = [entry.outcome for entry in kernel.audit_log()]
    assert outcomes[-1] is CommandOutcome.RESET
