"""Shared helpers for the library proofs: the template's tracker
prompt, settled-position extraction from a track, the coverage
record, and the machine-design stage evidence."""

from __future__ import annotations

import numpy as np

from mimforge.perception import (
    ColourPrompt,
    TrackResult,
    coverage_summary,
    track_object,
)

#: The stride the app itself imports demonstrations with
#: (``config.LEAN_PROFILE.keyframe_stride``). The proofs track at
#: the app's own sampling so their coverage numbers are the app's
#: numbers, not a laboratory stride's.
APP_STRIDE = 5


def prompt_from_template(data: dict) -> ColourPrompt:
    """The colour prompt a template carries for its filmed marker."""
    t = data["tracking"]
    return ColourPrompt(
        name=str(t.get("name", "object")),
        bgr_low=tuple(t["bgr_low"]),
        bgr_high=tuple(t["bgr_high"]),
        min_pixels=int(t.get("min_pixels", 20)),
    )


def track(path, data: dict, stride: int = APP_STRIDE) -> TrackResult:
    return track_object(path, prompt_from_template(data), stride=stride)


def settled_position(
    track: TrackResult, axis: str, tail_fraction: float = 0.35
) -> float:
    """The tracked object's settled coordinate: the median of the
    MEASURED (never bridged) positions over the last part of the
    track, when the demonstration has come to rest."""
    values = track.xs if axis == "x" else track.ys
    measured = (
        np.ones(len(values), dtype=bool)
        if track.bridged is None
        else ~np.asarray(track.bridged, dtype=bool)
    )
    if len(track.times) == 0:
        raise ValueError("empty track")
    span = float(track.times[-1] - track.times[0])
    cut = float(track.times[0]) + (1.0 - tail_fraction) * span
    tail = measured & (track.times >= cut)
    if int(np.count_nonzero(tail)) < 3:
        tail = measured
    if int(np.count_nonzero(tail)) == 0:
        raise ValueError("track has no measured points")
    return float(np.median(values[tail]))


def coverage_record(track: TrackResult) -> dict:
    """The honest coverage numbers for one tracked clip."""
    return {
        "measured_coverage": round(float(track.measured_coverage), 4),
        "coverage_incl_bridged": round(float(track.coverage), 4),
        "frames_examined": int(track.frames_total),
        "frames_measured": int(track.frames_measured),
        "summary": coverage_summary(track),
    }


def design_evidence(data: dict) -> dict:
    """Run the machine-design stage for one template: build the
    platform design, price the BOM at every tier, lay out the
    control panel from the template's own control list, and
    generate the panel code. Returns the recorded facts."""
    from mimforge.bom import TIERS, PartsDB, generate_bom
    from mimforge.codegen import generate_control_panel
    from mimforge.design import GantryParameters, build_gantry
    from mimforge.wiring import build_panel_layout

    design = build_gantry(GantryParameters())
    db = PartsDB()
    totals = {
        tier: generate_bom(db, tier, design.part_ids).total_ngn
        for tier in TIERS
    }
    layout = build_panel_layout(data)
    panel_src = generate_control_panel(data)
    return {
        "platform_id": data.get("platform_id", ""),
        "design_parts": len(design.part_ids),
        "bom_totals_ngn": {k: float(v) for k, v in totals.items()},
        "panel_controls": len(layout.controls),
        "panel_control_ids": [c.control_id for c in layout.controls],
        "panel_code_chars": len(panel_src),
    }
