"""Full spec audit (2026-11-26): runtime profile validation."""

import pytest

from mimforge.config import FULL_PROFILE, LEAN_PROFILE, RuntimeProfile


def test_shipped_profiles_are_valid():
    assert LEAN_PROFILE.mode == "lean"
    assert FULL_PROFILE.mode == "full"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keyframe_stride": 0},
        {"keyframe_stride": -2},
        {"max_frames_in_memory": 0},
        {"speech_model": "  "},
    ],
)
def test_bad_profile_values_fail_at_construction(kwargs):
    with pytest.raises(ValueError):
        RuntimeProfile(**kwargs)
