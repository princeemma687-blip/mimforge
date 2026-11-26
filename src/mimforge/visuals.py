"""Visualisation layer (next-stage plan, Stage 1): the living machine.

This module is the Qt-free half of the machine view. It turns
design parameters plus a performance track into *machine states*
(the view model), builds a render-oriented MuJoCo model of the
designed platform -- carriage, spool drum, release gate and the
suspended load, all actuated kinematically from those states --
and renders frames with MuJoCo's renderer when a GL backend is
available on the machine.

Nothing here steps physics: the motion comes from data the app
already trusts (the simulation track, or the retargeted
demonstration track), and this layer only *shows* it. The renderer
is driven kinematically, so the world-acceleration option is never
exercised and the model omits it entirely.

Generic by construction: inputs are ``GantryParameters`` and timed
tracks; outputs are states and pixels. If rendering is unavailable
(driver, frozen bundle, headless box), :func:`renderer_available`
says so and the UI falls back to the 2.5D canvas performance view
-- this module never raises at import time and never lets a
rendering failure escape into the shell.
"""

from __future__ import annotations

import bisect
import math
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np

from .design import GantryParameters

__all__ = [
    "VIEWS",
    "MachineRenderer",
    "MachineState",
    "MachineTimeline",
    "PartPlacement",
    "frame_is_alive",
    "part_layout",
    "renderer_available",
]

#: Camera presets: name -> (azimuth_deg, elevation_deg).
VIEWS: dict[str, tuple[float, float]] = {
    "front": (90.0, -10.0),
    "side": (0.0, -8.0),
    "top": (90.0, -88.0),
}

_GATE_RAMP_S = 0.3  # seconds for the release gate to travel open
_REST_SWING_RAD = 0.30  # held displacement shown for a resting machine


# ------------------------------------------------------------------ states


@dataclass(frozen=True)
class MachineState:
    """One instant of the machine, in metres and radians.

    ``carriage_x_m`` is the carriage centre along the beam (world
    X, 0 = beam centre); the pivot hangs under the carriage at the
    design's full height; the load sits ``length_m`` from the pivot
    at ``swing_rad`` from straight-down. ``gate_open`` is 0..1.
    """

    t_s: float
    carriage_x_m: float
    swing_rad: float
    length_m: float
    gate_open: float
    pivot_z_m: float

    @property
    def mass_x_m(self) -> float:
        return self.carriage_x_m + self.length_m * math.sin(self.swing_rad)

    @property
    def mass_z_m(self) -> float:
        return self.pivot_z_m - self.length_m * math.cos(self.swing_rad)


@dataclass
class MachineTimeline:
    """A sampled performance: machine states over time.

    Built from a track the app already produced; ``state_at``
    interpolates linearly between samples (angles included -- the
    tracks are densely sampled, so linear interpolation is the
    honest rendering of the data, not a smoothing of it).
    """

    samples: list[MachineState] = field(default_factory=list)
    label: str = ""
    release_time_s: float = 0.0

    # ---------------------------------------------------------- builders

    @classmethod
    def rest(cls, params: GantryParameters) -> "MachineTimeline":
        """The machine at rest, held at its gate: one still state."""
        low, high = params.suspension_range_mm
        state = MachineState(
            t_s=0.0,
            carriage_x_m=params.carriage_x_mm / 1000.0,
            swing_rad=_REST_SWING_RAD,
            length_m=(low + high) / 2000.0,
            gate_open=0.0,
            pivot_z_m=params.height_mm / 1000.0,
        )
        return cls(samples=[state, MachineState(**{**state.__dict__, "t_s": 1.0})],
                   label="AT REST — NO PERFORMANCE LOADED", release_time_s=float("inf"))

    @classmethod
    def from_sim_track(
        cls,
        points: list[tuple[float, float, float]],
        params: GantryParameters,
    ) -> "MachineTimeline":
        """From a simulation track: (t, x, y) metres relative to the
        pivot, y negative downward (``SimResult.track_points``)."""
        if len(points) < 2:
            raise ValueError("a performance needs at least 2 track points")
        pivot_z = params.height_mm / 1000.0
        carriage_x = params.carriage_x_mm / 1000.0
        samples = []
        for t, x, y in points:
            samples.append(
                MachineState(
                    t_s=float(t),
                    carriage_x_m=carriage_x,
                    swing_rad=math.atan2(float(x), -float(y)),
                    length_m=math.hypot(float(x), float(y)),
                    gate_open=0.0,  # filled by _with_gate below
                    pivot_z_m=pivot_z,
                )
            )
        timeline = cls(samples=samples, label="SIMULATION TRACK",
                       release_time_s=samples[0].t_s)
        return timeline._with_gate()

    @classmethod
    def from_retarget_points(
        cls,
        points: list[tuple[float, float, float]],
        params: GantryParameters,
    ) -> "MachineTimeline":
        """From retargeted demonstration points: (t, x_mm, y_mm) in
        the machine frame -- x along the carriage travel, y the
        drop below the suspension range's top (``RetargetResult``).
        The carriage follows the recorded path's x; the load hangs
        at the recorded drop, so the tool point traces the path."""
        from .retarget import workspace_envelope

        if len(points) < 2:
            raise ValueError("a performance needs at least 2 track points")
        travel_mm, _drop_mm = workspace_envelope(params)
        low, high = params.suspension_range_mm
        pivot_z = params.height_mm / 1000.0
        samples = []
        for t, x_mm, y_mm in points:
            length_m = min(max(low + float(y_mm), low), high) / 1000.0
            samples.append(
                MachineState(
                    t_s=float(t),
                    carriage_x_m=(float(x_mm) - travel_mm / 2.0) / 1000.0,
                    swing_rad=0.0,
                    length_m=length_m,
                    gate_open=0.0,
                    pivot_z_m=pivot_z,
                )
            )
        timeline = cls(
            samples=samples,
            label="DEMONSTRATION TRACK — MACHINE FOLLOWING THE RECORDING",
            release_time_s=samples[0].t_s,
        )
        return timeline._with_gate()

    # ------------------------------------------------------------ access

    @property
    def duration_s(self) -> float:
        if not self.samples:
            return 0.0
        return max(0.0, self.samples[-1].t_s - self.samples[0].t_s)

    @property
    def start_s(self) -> float:
        return self.samples[0].t_s if self.samples else 0.0

    def _with_gate(self) -> "MachineTimeline":
        """Fill each sample's gate opening from the release time:
        shut before release, travelling for a short ramp, open
        after -- the release is an event, shown as one."""
        out = []
        for s in self.samples:
            if math.isinf(self.release_time_s):
                gate = 0.0
            else:
                frac = (s.t_s - self.release_time_s) / _GATE_RAMP_S
                gate = min(1.0, max(0.0, frac))
            out.append(MachineState(**{**s.__dict__, "gate_open": gate}))
        self.samples = out
        return self

    def state_at(self, t_s: float) -> MachineState:
        """The machine state at an absolute track time (clamped)."""
        if not self.samples:
            raise ValueError("empty timeline has no states")
        times = [s.t_s for s in self.samples]
        if t_s <= times[0]:
            return self.samples[0]
        if t_s >= times[-1]:
            return self.samples[-1]
        idx = bisect.bisect_right(times, t_s) - 1
        a, b = self.samples[idx], self.samples[idx + 1]
        span = b.t_s - a.t_s
        frac = 0.0 if span <= 0 else (t_s - a.t_s) / span

        def lerp(x: float, y: float) -> float:
            return x + (y - x) * frac

        return MachineState(
            t_s=float(t_s),
            carriage_x_m=lerp(a.carriage_x_m, b.carriage_x_m),
            swing_rad=lerp(a.swing_rad, b.swing_rad),
            length_m=lerp(a.length_m, b.length_m),
            gate_open=lerp(a.gate_open, b.gate_open),
            pivot_z_m=a.pivot_z_m,
        )


# ------------------------------------------------------------------ layout


@dataclass(frozen=True)
class PartPlacement:
    """Where one designed part sits, assembled and exploded.

    Centres and sizes in millimetres, in the design's own frame
    (X span, Y depth, Z up). ``exploded_center_mm`` separates the
    parts along plain mechanical directions so the internals view
    can show the machine taken apart with every part labelled.
    """

    part_id: str
    name: str
    center_mm: tuple[float, float, float]
    size_mm: tuple[float, float, float]
    exploded_center_mm: tuple[float, float, float]


def part_layout(params: GantryParameters) -> list[PartPlacement]:
    """Placements for the platform's parts, mirroring the solids
    ``design.build_gantry`` fuses (same ids, same names, same
    centres) -- the internals view draws from this, so what it
    labels is what the CAD and the materials list contain."""
    params.validate()
    s = params.section_mm
    half_span = params.span_mm / 2.0
    upright_x = half_span - s / 2.0
    h = params.height_mm
    spool_z = h - params.carriage_height_mm - params.spool_radius_mm
    gate_z = spool_z - params.spool_radius_mm - 10.0
    cx = params.carriage_x_mm
    spread = 90.0  # mm of separation in the exploded presentation

    def placed(pid, name, center, size, explode):
        ex = tuple(c + e for c, e in zip(center, explode))
        return PartPlacement(pid, name, center, size, ex)

    return [
        placed("upright_left", "Upright, left",
               (-upright_x, 0, h / 2), (s, s, h), (-spread, 0, 0)),
        placed("upright_right", "Upright, right",
               (upright_x, 0, h / 2), (s, s, h), (spread, 0, 0)),
        placed("top_beam", "Top beam",
               (0, 0, h + s / 2), (params.span_mm, s, s), (0, 0, spread)),
        placed("foot_left", "Base foot, left",
               (-upright_x, 0, params.foot_height_mm / 2),
               (s, params.base_depth_mm, params.foot_height_mm),
               (-spread, 0, -spread / 2)),
        placed("foot_right", "Base foot, right",
               (upright_x, 0, params.foot_height_mm / 2),
               (s, params.base_depth_mm, params.foot_height_mm),
               (spread, 0, -spread / 2)),
        placed("carriage", "Travelling carriage",
               (cx, 0, h - params.carriage_height_mm / 2),
               (params.carriage_width_mm, s, params.carriage_height_mm),
               (0, spread, spread / 2)),
        placed("spool_drum", "Spool drum",
               (cx, 0, spool_z),
               (params.spool_length_mm, params.spool_radius_mm * 2,
                params.spool_radius_mm * 2),
               (0, 2 * spread, spread / 2)),
        placed("release_gate", "Release gate",
               (cx, 0, gate_z), (30, 20, 20), (0, 3 * spread, spread / 2)),
        placed("sensor_bracket", "Sensor bracket",
               (half_span - s - 5, 0, h / 2), (10, s, 80),
               (2 * spread, 0, 0)),
    ]


# ------------------------------------------------------------------ render


def _ensure_gl_backend() -> None:
    """Backstop for the GL backend choice: the real selection
    happens in the package init (it must precede any MuJoCo
    import); this only mirrors it for a caller that somehow
    reaches the renderer first. Headless Linux prefers EGL --
    see the package init for why OSMesa is frozen-unsafe."""
    if os.environ.get("MUJOCO_GL"):
        return
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        if getattr(sys, "frozen", False):
            try:
                import ctypes

                ctypes.CDLL("libEGL.so.1")
                os.environ["MUJOCO_GL"] = "egl"
            except OSError:
                pass
        else:
            os.environ["MUJOCO_GL"] = "osmesa"


_RENDER_XML = """<mujoco model="mimforge_machine_view">
  <option timestep="0.001"/>
  <worldbody>
    <geom type="plane" size="4 4 0.1" pos="0 0 -0.021" rgba="0.07 0.07 0.08 1"/>
    <geom type="box" size="{bench_half_x} 0.26 0.01" pos="0 0 -0.01"
          rgba="0.13 0.14 0.16 1"/>
    <geom type="box" size="{section_half} {section_half} {upright_half_height}"
          pos="{upright_x} 0 {upright_half_height}" rgba="0.42 0.46 0.52 1"/>
    <geom type="box" size="{section_half} {section_half} {upright_half_height}"
          pos="-{upright_x} 0 {upright_half_height}" rgba="0.42 0.46 0.52 1"/>
    <geom type="box" size="{section_half} {base_half_depth} {foot_half_height}"
          pos="{upright_x} 0 {foot_half_height}" rgba="0.36 0.39 0.44 1"/>
    <geom type="box" size="{section_half} {base_half_depth} {foot_half_height}"
          pos="-{upright_x} 0 {foot_half_height}" rgba="0.36 0.39 0.44 1"/>
    <geom type="box" size="{beam_half} {section_half} {section_half}"
          pos="0 0 {beam_z}" rgba="0.42 0.46 0.52 1"/>
    <geom type="box" size="0.005 {section_half} 0.04"
          pos="{sensor_x} 0 {sensor_z}" rgba="0.55 0.58 0.62 1"/>
    <body pos="{carriage_x} 0 0">
      <joint name="carriage_x" type="slide" axis="1 0 0"
             range="-{travel_half} {travel_half}"/>
      <geom type="box"
            size="{carriage_half_x} {section_half} {carriage_half_height}"
            pos="0 0 {carriage_z}" rgba="0.0 0.55 0.65 1"/>
      <body pos="0 0 {spool_z}">
        <joint name="spool_rot" type="hinge" axis="0 1 0"/>
        <geom type="cylinder" size="{spool_radius} {spool_half_length}"
              euler="1.5707963 0 0" rgba="0.75 0.6 0.25 1"/>
      </body>
      <body pos="0 0 {gate_z}">
        <joint name="gate_x" type="slide" axis="1 0 0" range="0 0.06"/>
        <geom type="box" size="0.015 0.01 0.01" rgba="0.85 0.3 0.2 1"/>
      </body>
      <body pos="0 0 {pivot_z}">
        <joint name="swing" type="hinge" axis="0 1 0" range="-1.2 1.2"/>
        <geom name="line" type="cylinder" size="0.0016 {line_half}"
              pos="0 0 -{line_half}" rgba="0.8 0.8 0.8 1"/>
        <geom name="mass" type="sphere" size="0.021"
              pos="0 0 -{length}" rgba="0.0 0.9 1.0 1"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""

# qpos layout of the render model, in XML body order.
_Q_CARRIAGE, _Q_SPOOL, _Q_GATE, _Q_SWING = 0, 1, 2, 3


def build_render_xml(params: GantryParameters, *, length_m: float) -> str:
    """The render model for one design at one suspension length.

    The line and load are baked at ``length_m``; the renderer
    re-sizes them per frame through the model's own arrays, so a
    performance whose length changes never rebuilds the model.
    Kinematic only -- the model is posed, never stepped."""
    params.validate()
    if length_m <= 0:
        raise ValueError("suspension length must be positive")
    s_mm = params.section_mm
    height_m = params.height_mm / 1000.0
    spool_z = (
        params.height_mm
        - params.carriage_height_mm
        - params.spool_radius_mm
    ) / 1000.0
    gate_z = spool_z - (params.spool_radius_mm + 10.0) / 1000.0
    travel_half = (
        params.span_mm / 2.0 - s_mm - params.carriage_width_mm / 2.0
    ) / 1000.0
    return _RENDER_XML.format(
        bench_half_x=params.span_mm / 2000.0 + 0.15,
        section_half=s_mm / 2000.0,
        upright_half_height=height_m / 2.0,
        upright_x=(params.span_mm - s_mm) / 2000.0,
        base_half_depth=params.base_depth_mm / 2000.0,
        foot_half_height=params.foot_height_mm / 2000.0,
        beam_half=params.span_mm / 2000.0,
        beam_z=height_m + s_mm / 2000.0,
        sensor_x=(params.span_mm / 2.0 - s_mm - 5.0) / 1000.0,
        sensor_z=height_m / 2.0,
        carriage_x=params.carriage_x_mm / 1000.0,
        travel_half=max(travel_half, 0.01),
        carriage_half_x=params.carriage_width_mm / 2000.0,
        carriage_half_height=params.carriage_height_mm / 2000.0,
        carriage_z=height_m - params.carriage_height_mm / 2000.0,
        spool_z=spool_z,
        spool_radius=params.spool_radius_mm / 1000.0,
        spool_half_length=params.spool_length_mm / 2000.0,
        gate_z=gate_z,
        pivot_z=height_m,
        line_half=length_m / 2.0,
        length=length_m,
    )


def frame_is_alive(frame: np.ndarray) -> bool:
    """A rendered frame carries a scene, not a blank field: more
    than a handful of distinct colours and some lit pixels."""
    if frame is None or frame.size == 0:
        return False
    colours = np.unique(frame.reshape(-1, frame.shape[-1]), axis=0)
    return len(colours) > 6 and int(frame.max()) > 0


class MachineRenderer:
    """Poses the render model from machine states and renders
    frames offscreen. Construction raises on any GL/model failure;
    callers use :func:`renderer_available` or catch and fall back.
    """

    def __init__(
        self,
        params: GantryParameters,
        *,
        width: int = 640,
        height: int = 480,
        length_m: float | None = None,
    ) -> None:
        _ensure_gl_backend()
        import mujoco

        self._mujoco = mujoco
        self.params = params
        if length_m is None:
            low, high = params.suspension_range_mm
            length_m = (low + high) / 2000.0
        xml = build_render_xml(params, length_m=length_m)
        self._model = mujoco.MjModel.from_xml_string(xml)
        self._data = mujoco.MjData(self._model)
        self._line_id = mujoco.mj_name2id(
            self._model, mujoco.mjtObj.mjOBJ_GEOM, "line"
        )
        self._mass_id = mujoco.mj_name2id(
            self._model, mujoco.mjtObj.mjOBJ_GEOM, "mass"
        )
        self._width, self._height = int(width), int(height)
        self._renderer = mujoco.Renderer(self._model, self._height, self._width)
        self._camera = mujoco.MjvCamera()
        height_m = params.height_mm / 1000.0
        span_m = params.span_mm / 1000.0
        self._camera.lookat[:] = [0.0, 0.0, height_m * 0.46]
        self._camera.distance = 1.5 * max(span_m, height_m) + 0.4
        self.last_frame_ms = 0.0

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    # ------------------------------------------------------------ posing

    def _pose(self, state: MachineState) -> None:
        mujoco = self._mujoco
        data = self._data
        base_x = self.params.carriage_x_mm / 1000.0
        data.qpos[_Q_CARRIAGE] = state.carriage_x_m - base_x
        spool_r = self.params.spool_radius_mm / 1000.0
        data.qpos[_Q_SPOOL] = state.length_m / max(spool_r, 1e-6)
        data.qpos[_Q_GATE] = 0.045 * state.gate_open
        data.qpos[_Q_SWING] = state.swing_rad
        # The line and the load follow the state's length through
        # the model's own arrays -- no rebuild, ever.
        self._model.geom_size[self._line_id] = (
            0.0016,
            state.length_m / 2.0,
            0.0,
        )
        self._model.geom_pos[self._line_id] = (0.0, 0.0, -state.length_m / 2.0)
        self._model.geom_pos[self._mass_id] = (0.0, 0.0, -state.length_m)
        mujoco.mj_forward(self._model, data)

    # ----------------------------------------------------------- render

    def render(self, state: MachineState, view: str = "front") -> np.ndarray:
        """One RGB frame of the machine in ``state`` from ``view``
        (a key of :data:`VIEWS`). Records the frame's cost in
        ``last_frame_ms`` -- the number the adaptive pacing and the
        Gate v2 probe report, measured, never estimated."""
        if view not in VIEWS:
            raise ValueError(f"unknown view {view!r}; expected one of {sorted(VIEWS)}")
        azimuth, elevation = VIEWS[view]
        self._camera.azimuth = azimuth
        self._camera.elevation = elevation
        started = time.perf_counter()
        self._pose(state)
        self._renderer.update_scene(self._data, self._camera)
        frame = self._renderer.render()
        self.last_frame_ms = (time.perf_counter() - started) * 1000.0
        return frame

    def measure_median_frame_ms(
        self, state: MachineState, frames: int = 15, view: str = "front"
    ) -> float:
        """Median render cost over ``frames`` renders of one state."""
        costs = []
        for _ in range(max(1, frames)):
            self.render(state, view)
            costs.append(self.last_frame_ms)
        costs.sort()
        return costs[len(costs) // 2]

    def close(self) -> None:
        try:
            self._renderer.close()
        except Exception:
            pass


_AVAILABLE: bool | None = None


def renderer_available() -> bool:
    """Probe once: can this machine build the render model and
    produce a living frame, offscreen, right now? The answer is
    cached for the process -- GL backends do not come and go."""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        probe = MachineRenderer(
            GantryParameters(), width=96, height=72
        )
        frame = probe.render(
            MachineTimeline.rest(GantryParameters()).state_at(0.0), "front"
        )
        _AVAILABLE = frame_is_alive(frame)
        probe.close()
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE
