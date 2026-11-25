"""End-to-end proof tests (experiments/pendulum_proof).

Runs the full synthetic pipeline once (module-scoped fixture):
synthetic videos -> centroid extraction -> readings table -> recovered
constant, in parallel with the physics simulation through the identical
table path, all wired through the generic core schema. Asserts both
recovered values land inside the tolerance band the template itself
carries (+/-5% of the expected value).

SYNTHETIC DATA ONLY, generated and processed in this environment --
these tests say nothing about real cameras or Windows (see
experiments/pendulum_proof/README.md).
"""

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from mimforge.models import ObservationKind  # noqa: E402
from experiments.pendulum_proof.proof import run_proof  # noqa: E402


@pytest.fixture(scope="module")
def proof(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("pendulum_proof")
    results = run_proof(out_dir)
    results["_out_dir"] = out_dir
    return results


def test_video_extraction_recovers_constant_within_band(proof):
    band = proof["band_percent_from_template"]
    err = proof["verification_run"]["discrepancy_metrics"][
        "video_recovered_percent_error"
    ]
    assert abs(err) <= band, f"video path error {err:+.2f}% outside +/-{band}%"


def test_simulation_recovers_constant_within_band(proof):
    band = proof["band_percent_from_template"]
    err = proof["verification_run"]["discrepancy_metrics"][
        "sim_recovered_percent_error"
    ]
    assert abs(err) <= band, f"simulation path error {err:+.2f}% outside +/-{band}%"


def test_verification_run_passed_and_records_engine(proof):
    run = proof["_objects"]["verification_run"]
    assert run.passed
    assert run.practical_id == "waec-physics-pendulum-g"
    # The engine that actually ran is on the record; if the fallback was
    # used, the reason must be recorded too -- never silent.
    assert proof["sim_engine"] in ("mujoco", "rk4-ode-fallback")
    if proof["sim_engine"] == "rk4-ode-fallback":
        assert proof["sim_engine_note"]


def test_demonstrations_carry_real_tracks_and_hashes(proof):
    video_dir = proof["_out_dir"] / "videos"
    truth = {r["length_m"]: r for r in proof["ground_truth_records"]}
    demos = proof["_objects"]["demonstrations"]
    assert len(demos) == len(truth)
    for demo in demos:
        length_m = float(demo.id.split("-L")[1].removesuffix("cm")) / 100.0
        video_file = video_dir / truth[length_m]["video_file"]
        assert demo.video_hash == hashlib.sha256(video_file.read_bytes()).hexdigest()
        track = demo.trajectories[0]
        assert len(track.points) > 100
        ts = [p[0] for p in track.points]
        assert ts == sorted(ts)


def test_tables_match_observation_spec_columns(proof):
    spec = proof["_objects"]["observation_spec"]
    assert spec.kind is ObservationKind.TABLE
    keys = [c.key for c in spec.columns]
    assert keys == proof["observation_spec_column_keys"]
    for row in proof["video_table"] + proof["sim_table"]:
        assert list(row.keys()) == keys


def test_per_length_periods_track_ground_truth(proof):
    """Each length's extracted period stays within 1.5% of the true
    period of the rendered motion (which itself carries the small
    amplitude effect, so this is not a small-angle-formula comparison)."""
    metrics = proof["verification_run"]["discrepancy_metrics"]
    assert metrics["video_max_period_error_percent"] < 1.5
    assert metrics["sim_max_period_error_percent"] < 1.5
