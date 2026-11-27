"""End-to-end video proofs for the static library practicals, at
reduced size for the suite: synthetic demonstration clips are
rendered, tracked by the app's improved colour tracker, fitted
through each template's own analysis chain, and verified. The
full-size runs and their scorecard live in
``experiments/library_proof`` (docs/PRACTICALS_LIBRARY.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

pytest.importorskip("cv2", reason="OpenCV not installed")

from experiments.library_proof import hooke_proof, moments_proof  # noqa: E402


def test_hooke_video_proof_recovers_the_spring_constant(tmp_path):
    entry = hooke_proof.run(
        tmp_path / "hooke", fps=20, duration=3.2, stride=2
    )
    assert entry["verification_passed"]
    assert abs(entry["error_percent_vs_truth"]) <= entry["band_percent"]
    assert entry["tracker"]["min_measured_coverage"] >= 0.9


def test_moments_video_proof_recovers_the_unknown_mass(tmp_path):
    entry = moments_proof.run(
        tmp_path / "moments", fps=20, duration=3.2, stride=2
    )
    assert entry["verification_passed"]
    assert abs(entry["error_percent_vs_truth"]) <= entry["band_percent"]
    assert entry["tracker"]["min_measured_coverage"] >= 0.9
