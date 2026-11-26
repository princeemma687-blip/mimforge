"""Parametric bench-gantry platform library (plan Phase 3.1).

The platform is generic: a bench gantry is two uprights, a top beam, base
feet, a travelling carriage, a spool drum, a release gate and a sensor
bracket. Nothing here knows what the gantry will carry, what it
suspends, or what practical it serves -- those specifics live in
template data and in the caller-supplied parameters.

Geometry is built with build123d (Apache-2.0, see docs/SBOM.md) and
exported as STEP/STL. All dimensions are millimetres. Coordinate system:
X = span (left-right across the bench), Y = depth (front-back),
Z = up from the bench surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PLATFORM_ID = "bench_gantry"


@dataclass(frozen=True)
class GantryParameters:
    """All dimensions of one gantry configuration."""

    span_mm: float = 600.0  # outer-face to outer-face distance, uprights
    height_mm: float = 1100.0  # bench surface to top of uprights
    # (must clear the longest suspension length + the beam section)
    section_mm: float = 40.0  # square section of uprights and top beam
    base_depth_mm: float = 300.0  # foot length along Y
    foot_height_mm: float = 20.0
    carriage_width_mm: float = 120.0
    carriage_height_mm: float = 60.0
    spool_radius_mm: float = 25.0
    spool_length_mm: float = 60.0
    carriage_x_mm: float = 0.0  # carriage position along the beam
    # Range of suspension lengths this configuration serves, in mm.
    suspension_range_mm: tuple[float, float] = (500.0, 1000.0)

    def validate(self) -> None:
        """Reject nonsense before any CAD is built."""
        if self.span_mm <= 2 * self.section_mm:
            raise ValueError("span must exceed twice the section size")
        if self.height_mm <= 0 or self.section_mm <= 0:
            raise ValueError("height and section must be positive")
        for name in (
            "foot_height_mm",
            "carriage_width_mm",
            "carriage_height_mm",
            "spool_radius_mm",
            "spool_length_mm",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.base_depth_mm <= self.section_mm:
            raise ValueError("base depth must exceed the section size")
        if abs(self.carriage_x_mm) + self.carriage_width_mm / 2 > (
            self.span_mm / 2 - self.section_mm
        ):
            raise ValueError("carriage does not fit between the uprights")
        low, high = self.suspension_range_mm
        if not (0 < low < high <= self.height_mm):
            raise ValueError(
                "suspension range must sit inside (0, height]"
            )


@dataclass
class GantryPart:
    """One solid in the generated model, for BOM tracing."""

    part_id: str
    name: str
    material_note: str = ""


@dataclass
class GantryDesign:
    """A built gantry: its solid, its parts, and its parameters."""

    parameters: GantryParameters
    solid: object  # build123d Part/Compound; typed loosely to avoid
    # importing the heavy CAD kernel at module import time for callers
    # that only need the parameter types.
    parts: list[GantryPart] = field(default_factory=list)
    # The beam and upright sub-solids, kept unfused so measurements
    # can be read back from the geometry itself, not the parameters.
    beam_solid: object = None
    uprights_solid: object = None

    @property
    def part_ids(self) -> list[str]:
        return [p.part_id for p in self.parts]


def build_gantry(params: GantryParameters) -> GantryDesign:
    """Build the gantry solid from parameters. Units: mm."""
    from build123d import Box, Cylinder, Pos, Rot

    params.validate()
    s = params.section_mm
    half_span = params.span_mm / 2.0
    upright_x = half_span - s / 2.0
    h = params.height_mm

    uprights = (
        Pos(-upright_x, 0, h / 2) * Box(s, s, h)
        + Pos(upright_x, 0, h / 2) * Box(s, s, h)
    )
    beam = Pos(0, 0, h + s / 2) * Box(params.span_mm, s, s)
    feet = (
        Pos(-upright_x, 0, params.foot_height_mm / 2)
        * Box(s, params.base_depth_mm, params.foot_height_mm)
        + Pos(upright_x, 0, params.foot_height_mm / 2)
        * Box(s, params.base_depth_mm, params.foot_height_mm)
    )
    carriage = Pos(params.carriage_x_mm, 0, h - params.carriage_height_mm / 2) * Box(
        params.carriage_width_mm, s, params.carriage_height_mm
    )
    spool_z = h - params.carriage_height_mm - params.spool_radius_mm
    spool = Pos(params.carriage_x_mm, 0, spool_z) * Rot(90, 0, 0) * Cylinder(
        params.spool_radius_mm, params.spool_length_mm
    )
    gate = Pos(params.carriage_x_mm, 0, spool_z - params.spool_radius_mm - 10) * Box(
        30, 20, 20
    )
    sensor = Pos(half_span - s - 5, 0, h / 2) * Box(10, s, 80)

    solid = uprights + beam + feet + carriage + spool + gate + sensor
    parts = [
        GantryPart("upright_left", "Upright, left"),
        GantryPart("upright_right", "Upright, right"),
        GantryPart("top_beam", "Top beam"),
        GantryPart("foot_left", "Base foot, left"),
        GantryPart("foot_right", "Base foot, right"),
        GantryPart("carriage", "Travelling carriage"),
        GantryPart("spool_drum", "Spool drum"),
        GantryPart("release_gate", "Release gate"),
        GantryPart("sensor_bracket", "Sensor bracket"),
    ]
    return GantryDesign(
        parameters=params,
        solid=solid,
        parts=parts,
        beam_solid=beam,
        uprights_solid=uprights,
    )


@dataclass
class GantryMeasurements:
    """Key dimensions read back from the built solid (test T3.1)."""

    overall_span_mm: float
    overall_height_mm: float
    overall_depth_mm: float
    beam_length_mm: float
    upright_height_mm: float
    suspension_range_mm: tuple[float, float]


def measure_gantry(design: GantryDesign) -> GantryMeasurements:
    """Measure the built solid: overall dimensions from the fused
    solid's bounding box, beam length and upright height from the
    kept beam / upright sub-solids' own bounding boxes -- read
    back from the geometry, never echoed from the parameters (a
    design assembled by hand without sub-solids falls back to the
    overall extents for the beam and the parameter for the
    uprights, the only honest options left there)."""
    box = design.solid.bounding_box()
    size = box.size
    beam_length = (
        float(design.beam_solid.bounding_box().size.X)
        if design.beam_solid is not None
        else float(size.X)
    )
    upright_height = (
        float(design.uprights_solid.bounding_box().size.Z)
        if design.uprights_solid is not None
        else design.parameters.height_mm
    )
    return GantryMeasurements(
        overall_span_mm=float(size.X),
        overall_height_mm=float(size.Z),
        overall_depth_mm=float(size.Y),
        beam_length_mm=beam_length,
        upright_height_mm=upright_height,
        suspension_range_mm=design.parameters.suspension_range_mm,
    )


def export_cad(design: GantryDesign, path: str | Path) -> Path:
    """Export the solid as STEP (``.step``/``.stp``) or STL (``.stl``)."""
    from build123d import export_step, export_stl

    out = Path(path)
    suffix = out.suffix.lower()
    if suffix in (".step", ".stp"):
        export_step(design.solid, str(out))
    elif suffix == ".stl":
        export_stl(design.solid, str(out))
    else:
        raise ValueError(f"unsupported CAD export suffix: {suffix!r}")
    return out


def read_step_dimensions(path: str | Path) -> GantryMeasurements:
    """Re-import an exported STEP file and measure it (proves it opens)."""
    from build123d import import_step

    solid = import_step(str(path))
    box = solid.bounding_box()
    size = box.size
    return GantryMeasurements(
        overall_span_mm=float(size.X),
        overall_height_mm=float(size.Z),
        overall_depth_mm=float(size.Y),
        beam_length_mm=float(size.X),
        upright_height_mm=0.0,  # not recoverable from a bare STEP file
        suspension_range_mm=(0.0, 0.0),
    )
