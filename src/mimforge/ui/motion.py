"""Motion layer state (Prince's direction, 2026-11-26): the shell
should feel alive -- a brief boot intro, panel transitions, a
scanning drafting canvas, a travelling dot on the design elevation,
count-up readouts -- but motion is a layer, never a load-bearing
wall.

Rules the whole UI follows:

* Qt-native only (timers, property animation, custom paint). No new
  dependencies, no web views.
* ``MIMFORGE_MOTION=off`` in the environment starts the app in
  reduced motion; the rail toggle (MOTION: FULL / REDUCED) flips it
  at runtime. Animated widgets consult :func:`motion_enabled` on
  every tick, so the toggle takes effect immediately.
* Nothing animated ever gates behaviour: with motion reduced, every
  panel shows its final state immediately. The offscreen test suite
  runs windows unshown, where animated widgets never start, and the
  click-path tests assert the same end states either way.
"""

from __future__ import annotations

import os

_reduced: bool | None = None


def motion_enabled() -> bool:
    """True when full motion is on. The environment variable is
    read once, lazily; the runtime toggle overrides it after."""
    global _reduced
    if _reduced is None:
        _reduced = os.environ.get("MIMFORGE_MOTION", "").strip().lower() == "off"
    return not _reduced


def set_motion_enabled(enabled: bool) -> None:
    """The rail toggle (and tests) flip motion at runtime."""
    global _reduced
    _reduced = not enabled
