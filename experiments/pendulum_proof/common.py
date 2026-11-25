"""Shared numerics for the pendulum proof: period estimation from a
zero-crossing series, the readings-table build, and the slope/constant
recovery. Both the video-extraction path and the simulation path use
these exact functions -- that identity is the point of the proof.
"""

from __future__ import annotations

import numpy as np

G_TRUTH = 9.81  # m/s^2 -- the value the synthetic world is built with
LENGTHS_M = [0.90, 0.80, 0.70, 0.60, 0.50]  # the template's length set
AMPLITUDE_DEG = 8.0  # release angle: small, WAEC-style, but not infinitesimal
N_OSCILLATIONS_TIMED = 20  # the practical times 20 oscillations per row


def small_angle_period(length_m: float, g: float = G_TRUTH) -> float:
    """T = 2*pi*sqrt(L/g) -- the formula the practical itself uses."""
    return 2.0 * np.pi * np.sqrt(length_m / g)


def upward_crossing_times(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Times at which y crosses zero going upward, linearly interpolated
    between samples so the estimate is not quantised to the sample grid."""
    idx = np.where((y[:-1] < 0.0) & (y[1:] >= 0.0))[0]
    if idx.size == 0:
        return np.empty(0)
    frac = -y[idx] / (y[idx + 1] - y[idx])
    return t[idx] + frac * (t[idx + 1] - t[idx])


def period_from_crossings(crossings: np.ndarray) -> tuple[float, np.ndarray]:
    """Mean period and the individual intervals between upward crossings."""
    intervals = np.diff(crossings)
    if intervals.size == 0:
        raise ValueError("fewer than two upward crossings: no period")
    return float(intervals.mean()), intervals


def split_period_estimates(intervals: np.ndarray) -> tuple[float, float]:
    """Two period estimates from the first and second halves of the
    crossing intervals -- the extraction analogue of timing the same run
    twice (t1 and t2 in the readings table)."""
    if intervals.size < 2:
        only = float(intervals.mean())
        return only, only
    half = intervals.size // 2
    return float(intervals[:half].mean()), float(intervals[half:].mean())


def build_table_rows(lengths_m, period_pairs) -> list[dict]:
    """Build readings-table rows keyed exactly like the template's
    ObservationSpec columns, rounded to the template's precisions.

    period_pairs: per length, (period_a, period_b) in seconds -- two
    timing estimates, as the practical takes t1 and t2 for 20
    oscillations and averages them.
    """
    rows = []
    for length_m, (period_a, period_b) in zip(lengths_m, period_pairs):
        t1 = N_OSCILLATIONS_TIMED * period_a
        t2 = N_OSCILLATIONS_TIMED * period_b
        mean_t = 0.5 * (t1 + t2)
        period = mean_t / N_OSCILLATIONS_TIMED
        rows.append(
            {
                "L_cm": round(100.0 * length_m, 1),
                "L_m": round(length_m, 3),
                "t1_s": round(t1, 1),
                "t2_s": round(t2, 1),
                "mean_t_s": round(mean_t, 1),
                "T_s": round(period, 2),
                "T2_s2": round(period * period, 2),
            }
        )
    return rows


def recover_from_table(rows: list[dict]) -> dict:
    """Fit the straight line to the table's (L, T^2) values and recover
    the constant from the slope -- the identical deduction the practical
    (and the plan's worked example) performs."""
    lengths = np.array([r["L_m"] for r in rows], dtype=float)
    t2 = np.array([r["T2_s2"] for r in rows], dtype=float)
    slope, intercept = np.polyfit(lengths, t2, 1)
    g = 4.0 * np.pi**2 / slope
    fitted = slope * lengths + intercept
    residuals_percent = 100.0 * (t2 - fitted) / fitted
    return {
        "slope_s2_per_m": float(slope),
        "intercept_s2": float(intercept),
        "recovered_value": float(g),
        "residuals_percent": [float(r) for r in residuals_percent],
        "max_abs_residual_percent": float(np.max(np.abs(residuals_percent))),
    }


def percent_error(value: float, truth: float = G_TRUTH) -> float:
    return 100.0 * (value - truth) / truth
