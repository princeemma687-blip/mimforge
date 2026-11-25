"""Command-line entry: run the pendulum proof and print a summary.

Usage (from the repository root, project venv active):

    python experiments/pendulum_proof/run_proof.py [--out DIR]

Default output directory: experiments/pendulum_proof/output/
(synthetic videos, ground_truth.json, results.json).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from experiments.pendulum_proof.proof import run_proof  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "experiments" / "pendulum_proof" / "output",
    )
    args = parser.parse_args()

    results = run_proof(args.out)
    v = results["verification_run"]
    print("Mimforge pendulum proof (SYNTHETIC data, Linux VM)")
    print(f"  ground truth g        : {results['ground_truth_value']:.2f} m/s^2")
    print(
        f"  video extraction      : g = {results['video_fit']['recovered_value']:.3f} "
        f"({v['discrepancy_metrics']['video_recovered_percent_error']:+.2f}%)"
    )
    print(
        f"  simulation [{results['sim_engine']}]"
        f"{' ' * max(0, 10 - len(results['sim_engine']))}: g = "
        f"{results['sim_fit']['recovered_value']:.3f} "
        f"({v['discrepancy_metrics']['sim_recovered_percent_error']:+.2f}%)"
    )
    if results["sim_engine_note"]:
        print(f"  sim note              : {results['sim_engine_note']}")
    print(f"  acceptance band       : +/-{results['band_percent_from_template']}%")
    print(f"  verification          : {'PASS' if v['passed'] else 'FAIL'}")
    print(f"  results written to    : {args.out / 'results.json'}")
    return 0 if v["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
