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
