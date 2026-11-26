"""Stage 1 -- the living machine: view model, renderer, fallback,
and the Playback/Simulate surfaces presenting the machine.

The view model is tested as pure data (track in, machine state
out). The renderer is tested with real offscreen frames when a GL
backend exists on the machine running the suite, and the canvas
fallback is tested everywhere -- the fallback is a designed
behaviour, so it must work even where 3D does.
"""

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mimforge import visuals  # noqa: E402
from mimforge.design import GantryParameters, build_gantry  # noqa: E402
from mimforge.playback import LessonPackage, LessonReplay, LessonStep  # noqa: E402
from mimforge.retarget import RetargetResult  # noqa: E402

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.ui.machine_view import MachineViewWidget  # noqa: E402
from mimforge.ui.panels import SimulatePanel  # noqa: E402
from mimforge.ui.playback import LessonPlayer  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


PARAMS = GantryParameters()


def _sim_points(n=41, duration=4.0, length=0.9, amp=0.2):
    """A swing track in the simulation frame: (t, x, y) metres
    relative to the pivot, y negative downward."""
    points = []
    for i in range(n):
        t = duration * i / (n - 1)
        angle = amp * math.cos(2 * math.pi * t / 2.0)
        points.append((t, length * math.sin(angle), -length * math.cos(angle)))
    return points


# ------------------------------------------------------------- view model


def test_timeline_from_sim_track_interpolates_the_swing():
    timeline = visuals.MachineTimeline.from_sim_track(_sim_points(), PARAMS)
    assert timeline.duration_s == pytest.approx(4.0)
    start = timeline.state_at(0.0)
    assert start.swing_rad == pytest.approx(0.2)
    assert start.length_m == pytest.approx(0.9)
    assert start.carriage_x_m == pytest.approx(0.0)
    # A quarter period in, the load crosses the bottom of its arc.
    middle = timeline.state_at(0.5)
    assert middle.swing_rad == pytest.approx(0.0, abs=0.02)
    assert middle.mass_z_m == pytest.approx(
        PARAMS.height_mm / 1000.0 - 0.9, abs=0.01
    )
    # Out-of-range times clamp to the ends, never extrapolate.
    assert timeline.state_at(-5.0).t_s == 0.0
    assert timeline.state_at(99.0).t_s == 4.0


def test_timeline_gate_opens_at_release_and_stays_open():
    timeline = visuals.MachineTimeline.from_sim_track(_sim_points(), PARAMS)
    assert timeline.state_at(0.0).gate_open == 0.0
    assert timeline.state_at(0.15).gate_open == pytest.approx(0.5)
    assert timeline.state_at(2.0).gate_open == 1.0


def test_timeline_from_retarget_points_follows_the_recorded_path():
    travel = PARAMS.span_mm - 2 * PARAMS.section_mm - PARAMS.carriage_width_mm
    low, _high = PARAMS.suspension_range_mm
    points = [(0.0, 0.0, 0.0), (1.0, travel / 2, 100.0), (2.0, travel, 0.0)]
    timeline = visuals.MachineTimeline.from_retarget_points(points, PARAMS)
    centre = timeline.state_at(1.0)
    assert centre.carriage_x_m == pytest.approx(0.0)
    assert centre.length_m == pytest.approx((low + 100.0) / 1000.0)
    left = timeline.state_at(0.0)
    assert left.carriage_x_m == pytest.approx(-travel / 2000.0)
    assert left.length_m == pytest.approx(low / 1000.0)
    assert "DEMONSTRATION" in timeline.label


def test_rest_timeline_holds_the_machine_at_its_gate():
    timeline = visuals.MachineTimeline.rest(PARAMS)
    state = timeline.state_at(0.0)
    assert state.gate_open == 0.0
    assert state.swing_rad > 0.1  # displaced, held -- visibly a swing machine
    assert timeline.duration_s == pytest.approx(1.0)


def test_part_layout_matches_the_cad_part_set():
    layout = visuals.part_layout(PARAMS)
    assert [p.part_id for p in layout] == build_gantry(PARAMS).part_ids
    for part in layout:
        assert part.exploded_center_mm != part.center_mm


def test_render_model_has_the_four_actuated_axes():
    mujoco = pytest.importorskip("mujoco")
    xml = visuals.build_render_xml(PARAMS, length_m=0.9)
    model = mujoco.MjModel.from_xml_string(xml)
    assert model.nq == 4  # carriage, spool, gate, swing
    names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i)
        for i in range(model.njnt)
    ]
    assert names == ["carriage_x", "spool_rot", "gate_x", "swing"]


# --------------------------------------------------------------- renderer


@pytest.mark.skipif(
    not visuals.renderer_available(), reason="no GL renderer on this machine"
)
def test_renderer_frames_are_alive_distinct_and_fast_enough():
    renderer = visuals.MachineRenderer(PARAMS, width=320, height=240)
    try:
        timeline = visuals.MachineTimeline.from_sim_track(_sim_points(), PARAMS)
        state = timeline.state_at(1.0)
        frames = {v: renderer.render(state, v) for v in ("front", "side", "top")}
        for frame in frames.values():
            assert visuals.frame_is_alive(frame)
        assert not (frames["front"] == frames["side"]).all()
        assert not (frames["front"] == frames["top"]).all()
        # A moved machine must produce a different picture.
        moved = renderer.render(timeline.state_at(1.6), "front")
        assert not (moved == frames["front"]).all()
        median = renderer.measure_median_frame_ms(state, frames=10)
        assert median < 250.0  # generous bound; the probe reports the real number
    finally:
        renderer.close()


# ----------------------------------------------------------------- widget


def test_widget_falls_back_cleanly_and_switches_views(app):
    widget = MachineViewWidget(force_fallback=True)
    try:
        assert widget.using_fallback
        widget.render_frame_now()
        assert widget.pages.currentIndex() == 1  # canvas performance
        widget.set_view("internals")
        assert widget.current_view == "internals"
        assert widget.pages.currentIndex() == 2
        widget.set_view("side")
        assert widget.pages.currentIndex() == 1
        with pytest.raises(ValueError):
            widget.set_view("orbit")
    finally:
        widget.close()


def test_widget_transport_and_seek(app):
    widget = MachineViewWidget(force_fallback=True)
    try:
        timeline = visuals.MachineTimeline.from_sim_track(_sim_points(), PARAMS)
        widget.set_timeline(timeline, "TRACK")
        assert widget.timeline.label == "TRACK"
        widget.play()
        assert widget.is_playing
        widget.advance_time(1.0)
        assert widget.current_time == pytest.approx(1.0)
        widget.pause()
        widget.advance_time(1.0)  # paused: the clock does not move
        assert widget.current_time == pytest.approx(1.0)
        widget.seek_fraction(0.5)
        assert widget.current_time == pytest.approx(2.0)
        widget.seek_fraction(2.0)  # clamps to the end
        assert widget.current_time == pytest.approx(4.0)
        widget.play()  # at the end, play restarts from the top
        assert widget.current_time == pytest.approx(0.0)
        widget.stop()
        assert not widget.is_playing
        assert widget.current_time == pytest.approx(0.0)
    finally:
        widget.close()


def test_widget_finishes_and_signals(app):
    widget = MachineViewWidget(force_fallback=True)
    try:
        timeline = visuals.MachineTimeline.from_sim_track(
            _sim_points(n=5, duration=0.5), PARAMS
        )
        widget.set_timeline(timeline)
        seen = []
        widget.finished.connect(lambda: seen.append(True))
        widget.play()
        widget.advance_time(1.0)
        assert seen == [True]
        assert not widget.is_playing
    finally:
        widget.close()


# ---------------------------------------------------------------- surfaces


def _lesson(replay: LessonReplay | None) -> LessonPackage:
    return LessonPackage(
        title="A lesson",
        subject="Physics",
        template_id="generic",
        steps=[
            LessonStep(order=1, title="Set up", duration_s=4.0),
            LessonStep(order=2, title="Run", duration_s=4.0),
            LessonStep(order=3, title="Read", duration_s=4.0),
        ],
        replay=replay,
    )


def test_playback_machine_follows_the_lesson_clock(app):
    replay = LessonReplay.from_points(
        _sim_points(), label="SIMULATION TRACK", sample_hz=10.0,
        x_label="x (m)", y_label="y (m)",
    )
    player = LessonPlayer()
    try:
        player.load_lesson(_lesson(replay), PARAMS)
        assert player.machine_view.timeline.label == "SIMULATION TRACK"
        assert player.machine_view.timeline.duration_s == pytest.approx(4.0)
        # Step 2 of 3, half-way through it: the machine sits at
        # (1 + 0.5) / 3 of its track.
        player._on_step_picked(1)
        player._step_elapsed = 2.0
        player._sync_machine()
        assert player.machine_view.current_time == pytest.approx(2.0)
    finally:
        player.close()


def test_playback_machine_uses_the_demonstration_frame_when_labelled(app):
    replay = LessonReplay.from_points(
        [(0.0, 0.0, 0.0), (1.0, 200.0, 100.0), (2.0, 400.0, 0.0)],
        label="MACHINE FOLLOWING YOUR RECORDED DEMONSTRATION",
        sample_hz=2.0, x_label="carriage (mm)", y_label="drop (mm)",
    )
    player = LessonPlayer()
    try:
        player.load_lesson(_lesson(replay), PARAMS)
        timeline = player.machine_view.timeline
        assert timeline.state_at(1.0).length_m == pytest.approx(0.6)
    finally:
        player.close()


def test_simulate_panel_shows_the_machine_performing_a_trajectory(app):
    class _Host:
        def current_params(self):
            return PARAMS

        def run_verification(self):
            pass

        def run_auto_adjust(self):
            pass

        def run_trajectory_replay(self):
            pass

    panel = SimulatePanel(_Host())
    try:
        result = RetargetResult(
            points=[(0.0, 0.0, 0.0), (1.0, 200.0, 100.0), (2.0, 400.0, 0.0)],
            feasible_percent=100.0, total_points=3,
        )
        replay = LessonReplay.from_points(
            result.points, label="DEMONSTRATION TRACK", sample_hz=2.0,
            x_label="carriage (mm)", y_label="drop (mm)",
        )
        panel.show_trajectory(result, replay)
        timeline = panel.machine_view.timeline
        assert timeline.duration_s == pytest.approx(2.0)
        assert timeline.state_at(1.0).length_m == pytest.approx(0.6)
        panel.show_project("P")
        assert panel.machine_view.timeline.label.startswith("AT REST")
    finally:
        panel.close()
