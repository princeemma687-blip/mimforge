import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

# ---------------------------------------------------------------------------
# Exit-code integrity -- the "ghost failure" fix (2026-11-27).
#
# WHY: on the Windows CI runner the suite printed a fully green summary
# (run 46002741151: "487 passed, 5 skipped, 3 warnings in 312.51s",
# timestamped 13:03:36.910Z) and python.exe STILL exited nonzero ~2.3 s
# later (PowerShell throw at 13:03:39.202Z) -- silently, with no
# traceback, during interpreter finalization. The same intermittent
# teardown segfault is known on the dev VM ("exit 139 after summary
# printed"). A native extension (GLFW/MuJoCo on a runner whose WGL
# driver "does not appear to support OpenGL" is the prime suspect;
# onnxruntime and Qt-multimedia are the other candidates) crashes while
# the interpreter tears it down, AFTER pytest has already decided and
# printed its verdict. The CI gate then judges the process's death,
# not the tests.
#
# WHAT: pytest_sessionfinish RECORDS pytest's own exit status (record
# only -- the terminal summary still prints normally from the reporter's
# own sessionfinish hook). pytest_unconfigure runs after every
# sessionfinish hook, i.e. after the summary is on the page; if a
# verdict was recorded it flushes the streams, terminates GLFW, and
# then os._exit()s with pytest's OWN recorded status, bypassing the
# native finalization that crashes. The gate keeps its exact meaning:
# green suite -> 0, any failure -> pytest's nonzero code, unchanged.
#
# The QApplication is deliberately NOT closed or deleted here: a
# marker-instrumented run of the heavy half of this suite (2026-11-27)
# showed the process segfaulting inside exactly that step (widget
# close / sip.delete) after the verdict -- Qt object destruction IS
# one of the native teardowns being bypassed. os._exit needs no
# destructors; the OS reclaims the whole process image at once.
#
# If NO verdict was recorded (usage error, collection aborted before
# sessionfinish), unconfigure does nothing and the process ends
# normally, so genuine harness errors keep their natural exit path.
# Nothing depends on post-unconfigure finalizers in the CI path:
# coverage is not used, and the app's tempdir finalizers are
# disposable-by-design (mimforge.tempdirs.remove_tree never raises and
# only sweeps disposable folders).
# ---------------------------------------------------------------------------

import gc
import os

import pytest

_recorded_exitstatus = None


def pytest_sessionfinish(session, exitstatus):
    global _recorded_exitstatus
    _recorded_exitstatus = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    if _recorded_exitstatus is None:
        # No verdict was ever decided -- let the process end normally.
        return
    code = _recorded_exitstatus

    def _flush():
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass

    _flush()

    # Orderly cleanup, every step guarded: nothing here may raise.
    # (GLFW termination was marker-verified to complete safely on the
    # heaviest part of the suite; see the note above for why no Qt
    # teardown is attempted.)
    try:
        glfw = sys.modules.get("glfw")
        if glfw is not None:
            glfw.terminate()
    except Exception:
        pass

    try:
        gc.collect()
    except Exception:
        pass

    _flush()
    os._exit(code)
