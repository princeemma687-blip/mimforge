"""The generic core schema loads, constructs and round-trips."""

from mimforge import (
    LEAN_PROFILE,
    ApparatusItem,
    Demonstration,
    MachineDesign,
    MotionPrimitive,
    MotionPrimitiveType,
    ObservationKind,
    ObservationSpec,
    Practical,
    SafetyCase,
    Step,
    VerificationRun,
)
from mimforge.templates import load_template


def test_generic_entities_construct_without_any_template():
    practical = Practical(
        id="generic-measure-volume",
        title="Measure the volume of a liquid",
        subject="Integrated Science",
        apparatus=[ApparatusItem(name="measuring cylinder")],
        outcome_spec="Recorded volume within tolerance of the true volume.",
    )
    step = Step(
        id="pour-and-read",
        order=1,
        title="Pour and read the level",
        motion_primitives=[
            MotionPrimitive(type=MotionPrimitiveType.POUR),
            MotionPrimitive(type=MotionPrimitiveType.READ),
        ],
    )
    demo = Demonstration(
        id="demo-1", practical_id=practical.id, video_hash="0" * 64
    )
    design = MachineDesign(platform_id="bench_gantry")
    run = VerificationRun(id="run-1", practical_id=practical.id)
    case = SafetyCase()

    assert practical.apparatus[0].name == "measuring cylinder"
    assert step.motion_primitives[0].type is MotionPrimitiveType.POUR
    assert demo.video_hash == "0" * 64
    assert design.platform_id == "bench_gantry"
    assert run.passed is False
    # Plan safety default: learner-reachable bench platforms are capped.
    assert case.limits.max_tool_speed_mm_s == 250.0
    assert case.signed_by_teacher is False  # export gate starts closed


def test_observation_spec_is_one_generic_type_for_all_formats():
    for kind in ObservationKind:
        spec = ObservationSpec(kind=kind)
        assert spec.kind is kind


def test_lean_profile_is_the_low_spec_default():
    assert LEAN_PROFILE.mode == "lean"
    assert LEAN_PROFILE.speech_model == "base"
    assert LEAN_PROFILE.segmentation_checkpoint == "tiny"
    assert LEAN_PROFILE.sequential_model_loading is True
    assert LEAN_PROFILE.prefer_gpu is False
    assert LEAN_PROFILE.keyframe_stride > 1


def test_template_loads_into_generic_schema():
    template = load_template("pendulum")
    assert template.practical.observation_spec is not None
    assert template.practical.observation_spec.kind is ObservationKind.TABLE
    assert len(template.steps) == 9
    orders = [s.order for s in template.steps]
    assert orders == sorted(orders)
    primitive_types = {
        mp.type for s in template.steps for mp in s.motion_primitives
    }
    assert MotionPrimitiveType.RELEASE in primitive_types
    assert MotionPrimitiveType.OSCILLATE in primitive_types
