"""Shared test fixtures.

The Phase-2 perception/narration tests run against the pendulum
proof's synthetic reference clips. Those clips are generated
artefacts (``*.mp4`` is gitignored -- the repo's snapshot push cannot
carry binaries), so a clean checkout does not have them. This session
fixture regenerates any missing clip with the experiment's own
generator (~3 s for all five lengths) so the suite is self-contained
on any machine, exactly like the narration test re-fetches its speech
sample when the fixture is absent.
"""

from pathlib import Path

import pytest

VIDEOS_DIR = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)
_LENGTHS_CM = (50, 60, 70, 80, 90)


@pytest.fixture(scope="session", autouse=True)
def _reference_clips():
    missing = [
        cm
        for cm in _LENGTHS_CM
        if not (VIDEOS_DIR / f"demo_L{cm:03d}cm.mp4").is_file()
    ]
    if missing:
        from experiments.pendulum_proof.generate_video import generate_all

        generate_all(VIDEOS_DIR)
    yield
