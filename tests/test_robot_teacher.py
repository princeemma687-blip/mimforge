"""Stage 4 full pass: the ROBOT TEACHER.

Prince's finished-app definition (2026-11-27): the app creates
the robot, with the outline and drawing of it, with simulation
of it doing the practical -- and the presentation must not read
as an abstract swinging apparatus: a standing robot at the
apparatus performs and teaches.

Pins:
- the robot is generic geometry derived from the design's own
  dimensions, constant across practicals, with zero
  practical-specific terms (the anti-pendulum scan covers the
  core separately);
- the inverse-kinematics pose is exact: segment lengths hold,
  the hand lands on the target when it is reachable, an
  unreachable target clamps along its own direction, and the
  elbow trails;
- the timeline poses the robot from the lesson's action cues:
  it holds the load before release, opens its grip through the
  release, points while readings are taken, and a resting
  timeline holds forever;
- the render model carries the robot's four axes and its gripper
  lands on the solved hand position;
- the 2D fallback draws the robot (and draws nothing in its
  region when the robot is absent -- the drawing-level negative
  control), the Design elevation shows it dimensioned, and the
  production dossier carries its drawing;
- the Gate robot check fails when the robot is secretly absent
  or secretly unhidable (negative controls);
- the sample treatment reaches the remaining panels: every
  action button carries a vector icon, prose surfaces read in
  the grotesque, and the record button's icon follows its state.
"""

from __future__ import annotations

import math

import pytest

from mimforge import dossier, risk, visuals
from mimforge.assembly import build_assembly_plan
from mimforge.bom import TIERS, PartsDB, generate_bom
from mimforge.delivery import (
    build_assessment,
    fingerprint_design,
    generate_checked_code,
)
from mimforge.design import GantryParameters, build_gantry
from mimforge.models import MotionPrimitiveType
from mimforge.playback import (
    LessonPackage,
    LessonReplay,
    LessonStep,
    build_lesson,
)
from mimforge.simulation import simulate_suspension
from mimforge.templates import load_template, load_template_data

PARAMS = GantryParameters()
TEMPLATE = load_template_data("pendulum")  # a template, as data
TEMPLATE_OBJ = load_template("pendulum")  # the same, as an object


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


# ----------------------------------------------------------
# Geometry: layout and inverse kinematics
# ----------------------------------------------------------


def _shoulder(layout) -> tuple[float, float, float]:
    return (
        layout.shoulder_x_m,
        layout.shoulder_y_m,
        layout.shoulder_z_m,
    )


def test_robot_layout_derives_from_the_design():
    layout = visuals.robot_layout(PARAMS)
    # Beside the machine, never inside its span.
    assert layout.station_x_m > PARAMS.span_mm / 2000.0
    assert layout.height_m == pytest.approx(
        0.92 * PARAMS.height_mm / 1000.0, abs=1e-9
    )
    assert 0 < layout.shoulder_z_m < layout.height_m
    # The station must let the arm reach the carriage at centre:
    # shoulder to mid-travel load position within full reach.
    state = visuals.MachineTimeline.rest(PARAMS).state_at(0.0)
    dx = state.carriage_x_m - layout.shoulder_x_m
    dz = (state.pivot_z_m - state.length_m) - layout.shoulder_z_m
    assert math.hypot(dx, dz) < layout.upper_arm_m + (
        layout.forearm_m + layout.gripper_m
    )


def test_hold_pose_hand_lands_exactly_on_the_load():
    timeline = visuals.MachineTimeline.rest(PARAMS)
    state = timeline.state_at(0.0)
    pose = timeline.robot_state_at(0.0)
    assert pose.action == "hold"
    assert pose.grip_open == 0.0
    # The load hangs at the state's swing angle from the pivot.
    load = (
        state.carriage_x_m + state.length_m * math.sin(state.swing_rad),
        0.0,
        state.pivot_z_m - state.length_m * math.cos(state.swing_rad),
    )
    assert pose.hand_m == pytest.approx(load, abs=1e-9)
    # A resting timeline holds forever -- it never lets go.
    assert timeline.robot_state_at(3600.0).action == "hold"


def test_ik_segments_are_exact_and_the_elbow_trails():
    layout = visuals.robot_layout(PARAMS)
    sx, sy, sz = _shoulder(layout)
    for target in (
        (0.22, 0.0, 0.38),
        (0.1, 0.0, 0.5),
        (0.3, 0.1, 0.3),
        (0.0, 0.0, 0.55),
    ):
        pose = visuals.solve_robot_pose(layout, target, 0.0, "hold")
        ex, ey, ez = pose.elbow_m
        hx, hy, hz = pose.hand_m
        assert math.dist((sx, sy, sz), (ex, ey, ez)) == pytest.approx(
            layout.upper_arm_m, abs=1e-9
        )
        reach = layout.forearm_m + layout.gripper_m
        assert math.dist((ex, ey, ez), (hx, hy, hz)) == pytest.approx(
            reach, abs=1e-9
        )
        assert (hx, hy, hz) == pytest.approx(target, abs=1e-9)
        # The elbow trails: projected onto the shoulder-to-hand
        # direction, it never reaches further than the hand.
        ux, uy = hx - sx, hy - sy
        norm = math.hypot(ux, uy)
        if norm > 1e-9:
            elbow_along = ((ex - sx) * ux + (ey - sy) * uy) / norm
            assert elbow_along <= norm + 1e-9


def test_unreachable_target_clamps_along_its_direction():
    layout = visuals.robot_layout(PARAMS)
    sx, _sy, sz = _shoulder(layout)
    target = (sx - 3.0, 0.0, sz + 3.0)
    pose = visuals.solve_robot_pose(layout, target, 0.5, "adjust")
    full = layout.upper_arm_m + layout.forearm_m + layout.gripper_m
    assert math.dist(_shoulder(layout), pose.hand_m) == pytest.approx(
        full * 0.999, abs=1e-6
    )
    # Collinear with the intended direction.
    vx, vz = target[0] - sx, target[2] - sz
    hx, hz = pose.hand_m[0] - sx, pose.hand_m[2] - sz
    assert vx * hz == pytest.approx(vz * hx, abs=1e-6)


def test_primitive_mapping_covers_every_primitive_generically():
    for primitive in MotionPrimitiveType:
        action = visuals.robot_action_for_primitive(primitive.value)
        assert action in visuals.ROBOT_ACTIONS
    assert visuals.robot_action_for_primitive("release") == "release"
    assert visuals.robot_action_for_primitive("read") == "point"
    assert visuals.robot_action_for_primitive("nonsense") == "watch"


def _prong_gap(outline) -> float:
    (ax, _az), _a2 = outline["gripper"][0]
    (bx, _bz), _b2 = outline["gripper"][1]
    return abs(bx - ax)


def test_robot_outline_is_one_consistent_drawing():
    layout = visuals.robot_layout(PARAMS)
    closed = visuals.robot_outline(layout, _pose("hold", 0.0))
    opened = visuals.robot_outline(layout, _pose("release", 1.0))
    assert len(closed["rects"]) == 6  # foot, legs, pelvis, torso, neck, head
    assert closed["height_m"] == pytest.approx(layout.height_m)
    assert closed["station_x_m"] == pytest.approx(layout.station_x_m)
    assert len(closed["arm"]) == 3  # shoulder, elbow, hand
    # The prongs spread as the grip opens.
    assert _prong_gap(opened) > _prong_gap(closed)


def _pose(action: str, grip: float) -> visuals.RobotState:
    layout = visuals.robot_layout(PARAMS)
    return visuals.solve_robot_pose(
        layout, (0.0, 0.0, 0.35), grip, action
    )


# ----------------------------------------------------------
# Timeline behaviour: hold, release, point
# ----------------------------------------------------------


def _sim_result():
    return simulate_suspension(
        PARAMS, length_m=0.75, release_deg=20.0, world_constant=9.81
    )


def _sim_timeline():
    return visuals.MachineTimeline.from_sim_track(
        _sim_result().track_points(), PARAMS
    )


def _sim_replay() -> LessonReplay:
    return LessonReplay.from_points(
        _sim_result().track_points(),
        label="simulated track, L = 0.75 m",
        sample_hz=200.0,
        x_label="x (m)",
        y_label="y (m)",
    )


def test_release_opens_the_grip_and_retracts_the_hand():
    timeline = _sim_timeline()
    release_t = timeline.release_time_s
    at_release = timeline.robot_state_at(release_t)
    mid = timeline.robot_state_at(release_t + 0.15)
    after = timeline.robot_state_at(release_t + 0.45)
    assert at_release.grip_open == pytest.approx(0.0, abs=1e-9)
    assert mid.action == "release"
    assert 0.0 < mid.grip_open < 1.0
    assert after.action == "point"
    assert after.grip_open == pytest.approx(0.2)
    # Retraction: the hand ends nearer its own shoulder than the
    # load it let go of.
    layout = visuals.robot_layout(PARAMS)
    shoulder = _shoulder(layout)
    state = timeline.state_at(release_t)
    load = (
        state.carriage_x_m + state.length_m * math.sin(state.swing_rad),
        0.0,
        state.pivot_z_m - state.length_m * math.cos(state.swing_rad),
    )
    assert math.dist(shoulder, mid.hand_m) < math.dist(shoulder, load)


def test_segments_override_the_gate_derivation():
    timeline = _sim_timeline()
    timeline.action_segments = (
        (0.0, 1.0, "adjust"),
        (1.0, 6.0, "watch"),
    )
    assert timeline.robot_state_at(0.5).action == "adjust"
    # Inside the swing the gate derivation would say point; the
    # lesson's own cues win.
    assert timeline.robot_state_at(3.0).action == "watch"


# ----------------------------------------------------------
# Lesson cue sheet: steps carry their actions
# ----------------------------------------------------------


def test_lesson_steps_carry_their_primitives():
    lesson = build_lesson(TEMPLATE_OBJ)
    assert lesson.steps[0].motion_primitives == ["translate", "hold"]
    assert lesson.steps[2].motion_primitives == ["release", "oscillate"]
    assert lesson.steps[-1].motion_primitives == []
    restored = LessonPackage.from_dict(lesson.to_dict())
    assert restored.steps[2].motion_primitives == ["release", "oscillate"]


def _player_lesson():
    return build_lesson(TEMPLATE_OBJ, replay=_sim_replay())


def test_player_builds_the_action_cue_sheet(app):
    from mimforge.ui.playback import LessonPlayer

    player = LessonPlayer()
    player.load_lesson(_player_lesson())
    timeline = player.machine_view.timeline
    assert timeline is not None
    actions = [a for _s, _e, a in timeline.action_segments]
    assert actions == [
        "adjust", "hold",        # set the length
        "adjust", "point",       # time ten swings (setup + read)
        "release", "watch",      # release and swing
        "point",                 # record the period
        "adjust", "release", "watch", "point",  # repeat, shorter
        "point", "point", "point",
        "watch",                 # the closing step has no action
    ]
    # During the release step's release cue, the robot releases.
    step_share = timeline.duration_s / 9
    pose = timeline.robot_state_at(2 * step_share + 0.1)
    assert pose.action == "release"
    player.close()


def test_player_without_primitives_keeps_gate_derivation(app):
    from mimforge.ui.playback import LessonPlayer

    steps = [LessonStep(order=0, title="Only step", narration="Words.")]
    lesson = LessonPackage(
        title="Generic",
        subject="Generic",
        template_id="generic",
        steps=steps,
        replay=_sim_replay(),
    )
    player = LessonPlayer()
    player.load_lesson(lesson)
    timeline = player.machine_view.timeline
    assert timeline is not None
    assert timeline.action_segments == []
    assert timeline.robot_state_at(0.0).action == "hold"
    player.close()


# ----------------------------------------------------------
# Render model: the robot's body is really there
# ----------------------------------------------------------


def test_render_model_robot_gripper_lands_on_the_solved_hand():
    mujoco = pytest.importorskip("mujoco")
    xml = visuals.build_render_xml(PARAMS, length_m=0.75)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    timeline = visuals.MachineTimeline.rest(PARAMS)
    state = timeline.state_at(0.0)
    pose = timeline.robot_state_at(0.0)
    data.qpos[0] = state.carriage_x_m
    data.qpos[3] = state.swing_rad
    data.qpos[4] = pose.yaw_rad
    data.qpos[5] = pose.shoulder_rad
    data.qpos[6] = pose.elbow_rad
    data.qpos[7] = -0.02 * pose.grip_open
    mujoco.mj_forward(model, data)
    base = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_GEOM, "robot_gripper_base"
    )
    base_pos = data.geom_xpos[base]
    # The gripper base is centred half a gripper-length behind
    # the grasp point the solver solved for -- the model's hand
    # IS the solver's hand.
    layout0 = visuals.robot_layout(PARAMS)
    assert math.dist(tuple(base_pos), pose.hand_m) == pytest.approx(
        layout0.gripper_m / 2, abs=0.01
    )
    finger = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_GEOM, "robot_finger_fixed"
    )
    assert math.dist(tuple(data.geom_xpos[finger]), pose.hand_m) < 0.05
    head = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "robot_head")
    head_pos = data.geom_xpos[head]
    assert head_pos[0] == pytest.approx(layout0.station_x_m, abs=0.02)
    assert head_pos[2] > 0.9 * layout0.height_m


@pytest.mark.skipif(
    not visuals.renderer_available(), reason="no GL renderer here"
)
def test_gate_robot_check_passes_and_its_controls_fail():
    from mimforge.selftest_flows import _robot_render_check

    def real(show_robot: bool):
        return visuals.MachineRenderer(
            PARAMS, width=320, height=240, show_robot=show_robot
        )

    ok, detail = _robot_render_check(real)
    assert ok, detail

    def secretly_absent(_show_robot: bool):
        return visuals.MachineRenderer(
            PARAMS, width=320, height=240, show_robot=False
        )

    ok, _detail = _robot_render_check(secretly_absent)
    assert not ok, "a robot-less build must fail the robot check"

    def secretly_unhidable(_show_robot: bool):
        return visuals.MachineRenderer(
            PARAMS, width=320, height=240, show_robot=True
        )

    ok, _detail = _robot_render_check(secretly_unhidable)
    assert not ok, "an unhidable robot defeats the A/B control"


def test_robot_frame_delta_of_identical_frames_is_zero():
    import numpy as np

    from mimforge.selftest_flows import _robot_frame_delta

    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert _robot_frame_delta(frame, frame) == (0, 0.0)


# ----------------------------------------------------------
# Drawings: fallback canvas, Design elevation, dossier
# ----------------------------------------------------------

_ROBOT_PIXELS = {(0x8A, 0x92, 0x9A), (0x00, 0xE5, 0xFF), (0xD9, 0x4D, 0x33)}
_ROBOT_STEEL = (0x8A, 0x92, 0x9A)


def _region_robot_pixels(image, x_lo: float, x_hi: float) -> int:
    count = 0
    width, height = image.width(), image.height()
    for x in range(int(width * x_lo), int(width * x_hi)):
        for y in range(0, height, 2):
            if image.pixelColor(x, y).getRgb()[:3] in _ROBOT_PIXELS:
                count += 1
    return count


def _colour_stats(image, colours) -> tuple[int, float]:
    """(count, mean x as a fraction of width) of pixels in
    ``colours`` -- position evidence that survives any aspect
    ratio the offscreen layout happens to choose."""
    count = 0
    sum_x = 0
    width, height = image.width(), image.height()
    for x in range(width):
        for y in range(0, height, 2):
            if image.pixelColor(x, y).getRgb()[:3] in colours:
                count += 1
                sum_x += x
    if count == 0:
        return 0, 0.0
    return count, (sum_x / count) / width


def test_fallback_canvas_draws_the_robot_and_the_control_is_clean(app):
    from mimforge.ui.machine_view import MachineViewWidget

    widget = MachineViewWidget(force_fallback=True)
    widget.resize(1000, 700)
    timeline = visuals.MachineTimeline.rest(PARAMS)
    widget.set_timeline(timeline, "PROBE")
    widget.render_frame_now()
    assert widget.current_robot_state is not None
    assert widget.current_robot_state.action == "hold"
    image = widget.canvas.grab().toImage()
    # The robot's steel appears, standing right of centre (the
    # machine's own steel is a different grey; its accent mass
    # hangs at the carriage, left of the robot's station).
    count, mean_x = _colour_stats(image, {_ROBOT_STEEL})
    assert count > 10
    assert mean_x > 0.55
    # Negative control: the same scene with no robot drawn.
    state = timeline.state_at(0.0)
    widget.canvas.set_scene(state, PARAMS, "front", robot=None)
    image = widget.canvas.grab().toImage()
    count, _mean_x = _colour_stats(image, {_ROBOT_STEEL})
    assert count == 0
    widget.close()


def test_design_elevation_shows_the_robot_dimensioned(app):
    from mimforge.ui.panels import GantryElevationView

    view = GantryElevationView()
    view.set_params(PARAMS)
    view.resize(900, 900)
    image = view.grab().toImage()
    # Robot station region at this size: x in [0.65, 0.76].
    assert _region_robot_pixels(image, 0.65, 0.76) > 5
    view.close()


def test_assembly_canvas_stands_the_robot_at_the_machine(app):
    from mimforge.ui.assembly import AssemblyCanvas

    plan = build_assembly_plan(PARAMS, "prototype")
    canvas = AssemblyCanvas()
    canvas.set_scene(plan, 0, 1.0)
    canvas.resize(1000, 600)
    image = canvas.grab().toImage()
    # The robot's steel stands right of the machine's span.
    count, mean_x = _colour_stats(image, {_ROBOT_STEEL})
    assert count > 5
    assert mean_x > 0.55
    canvas.close()


def test_dossier_carries_the_robot_drawing():
    doc = _dossier()
    assert "THE ROBOT TEACHER" in doc
    assert "ROBOT TEACHER — FRONT, AS DESIGNED" in doc
    assert "ROBOT — FRONT ELEVATION" in doc
    svg = dossier.robot_outline_svg(PARAMS)
    assert "ROBOT" in svg
    layout = visuals.robot_layout(PARAMS)
    assert f"{round(layout.height_m * 1000)}" in svg


def _dossier() -> str:
    assessment = build_assessment(TEMPLATE)
    assessment.design_fingerprint = fingerprint_design(PARAMS)
    risk.sign(assessment, "Ada Teacher")
    part_ids = build_gantry(PARAMS).part_ids
    tier_boms = {
        tier: generate_bom(PartsDB(), tier, part_ids) for tier in TIERS
    }
    return dossier.build_dossier_html(
        project_title="Bench",
        template_data=TEMPLATE,
        params=PARAMS,
        tier_boms=tier_boms,
        assessment=assessment,
        code=generate_checked_code(TEMPLATE, PARAMS),
        images={},
    )


# ----------------------------------------------------------
# Sample treatment across the remaining panels
# ----------------------------------------------------------


def test_every_icon_renders_and_differs(app):
    from mimforge.ui.icons import ICON_NAMES, make_icon

    seen: dict[bytes, str] = {}
    for name in ICON_NAMES:
        image = make_icon(name, 64).pixmap(64, 64).toImage()
        filled = 0
        blob = bytearray()
        for x in range(64):
            for y in range(64):
                alpha = image.pixelColor(x, y).alpha()
                if alpha > 0:
                    filled += 1
                blob.append(alpha)
        assert filled > 30, name
        key = bytes(blob)
        assert key not in seen, f"{name} renders like {seen.get(key)}"
        seen[key] = name


class _StubHost:
    design_params = PARAMS

    def run_assembly(self):
        pass

    def export_cad(self, _kind):
        pass

    def run_verification(self):
        pass

    def auto_adjust(self):
        pass

    def run_trajectory_replay(self):
        pass

    def export_package(self):
        pass

    def export_production_document(self):
        pass

    def generate_code(self):
        pass

    def sign_assessment(self, _name):
        pass


def _assert_icon(button, name: str) -> None:
    assert not button.icon().isNull(), name


def _icon_bytes(button) -> bytes:
    image = button.icon().pixmap(18, 18).toImage()
    return bytes(image.bits())


def test_panels_carry_the_icon_set(app):
    from mimforge.ui.assembly import AssemblyPlayer
    from mimforge.ui.authoring import AuthoringPanel
    from mimforge.ui.deliver import DeliverPanel
    from mimforge.ui.panels import DesignPanel, SimulatePanel

    author = AuthoringPanel()
    for button in (
        author.import_button, author.transcript_button,
        author.voice_attach_button, author.voice_record_button,
        author.voice_remove_button, author.approve_button,
        author.reject_button, author.build_lesson_button,
    ):
        _assert_icon(button, button.text())
    # The record icon follows the recording state.
    idle = _icon_bytes(author.voice_record_button)
    author.set_recording(True)
    assert _icon_bytes(author.voice_record_button) != idle
    author.set_recording(False)
    assert _icon_bytes(author.voice_record_button) == idle

    host = _StubHost()
    design = DesignPanel(host)
    for button in (
        design.build_it_button, design.export_step_button,
        design.export_stl_button,
    ):
        _assert_icon(button, button.text())
    simulate = SimulatePanel(host)
    for button in (
        simulate.run_button, simulate.adjust_button, simulate.replay_button,
    ):
        _assert_icon(button, button.text())
    deliver = DeliverPanel(host)
    for button in (
        deliver.sign_button, deliver.export_button,
        deliver.production_button, deliver.generate_button,
    ):
        _assert_icon(button, button.text())

    player = AssemblyPlayer()
    player.set_plan(build_assembly_plan(PARAMS, "prototype"))
    for button in (
        player.back_button, player.prev_button, player.play_button,
        player.pause_button, player.next_button, player.reset_button,
    ):
        _assert_icon(button, button.text())
    player.close()


def test_prose_surfaces_read_in_the_grotesque(app):
    from mimforge.ui.authoring import AuthoringPanel
    from mimforge.ui.deliver import DeliverPanel
    from mimforge.ui.main_window import mono_font, prose_font

    author = AuthoringPanel()
    assert author.editor.font().families() == prose_font(10).families()
    assert author.editor.font().families() != mono_font(10).families()
    assert author.step_title.font().families() == prose_font(
        11, bold=True
    ).families()
    # The source/status readout stays mono -- it is data, not prose.
    assert author.meta_label.font().families() == mono_font(9).families()

    deliver = DeliverPanel(_StubHost())
    assert deliver.assessment_view.font().families() == prose_font(
        10
    ).families()
    # The controller code stays mono.
    assert deliver.code_view.font().families() == mono_font(10).families()
