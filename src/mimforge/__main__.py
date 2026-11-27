"""Mimforge desktop application entry point.

``python -m mimforge`` launches the mission-control shell. The
packaged (PyInstaller) build uses the same entry point.

``python -m mimforge --self-test`` is the frozen-bundle gate added
after the 2026-11-26 launch crash (run #6: ``No module named
'scipy'`` on the user's laptop, because the PyInstaller spec
excluded a package build123d imports at module load). It imports
the FULL module graph -- every mimforge module plus every
third-party runtime package -- then constructs the real main
window offscreen and exits 0 printing ``SELF-TEST OK``. Any
missing module exits non-zero with the traceback, so CI can fail
the build BEFORE an installer is packaged (see the self-test step
in the Windows workflow).

The self-test also writes its full report (every probe line plus
the verdict) to ``self-test-report.txt`` in the current working
directory and then terminates with ``os._exit`` -- see
``_finish_self_test`` for why the verdict must not travel through
normal interpreter teardown.
"""

from __future__ import annotations

import os
import sys

# Every mimforge module, kept in step with the source tree by
# tests/test_frozen_bundle.py (which fails if a module file exists
# that is not listed here).
SELF_TEST_MODULES = [
    "mimforge",
    "mimforge.adjust",
    "mimforge.allowlist",
    "mimforge.assembly",
    "mimforge.bom",
    "mimforge.checker",
    "mimforge.codegen",
    "mimforge.config",
    "mimforge.delivery",
    "mimforge.design",
    "mimforge.discrepancy",
    "mimforge.dossier",
    "mimforge.episodes",
    "mimforge.firebase_auth",
    "mimforge.firebase_sync",
    "mimforge.models",
    "mimforge.narration",
    "mimforge.outcome",
    "mimforge.perception",
    "mimforge.playback",
    "mimforge.projects",
    "mimforge.resources",
    "mimforge.retarget",
    "mimforge.risk",
    "mimforge.safety",
    "mimforge.sam_tracker",
    "mimforge.selftest_flows",
    "mimforge.signing",
    "mimforge.simulation",
    "mimforge.speech",
    "mimforge.structuring",
    "mimforge.sync",
    "mimforge.templates",
    "mimforge.tempdirs",
    "mimforge.verification",
    "mimforge.ui",
    "mimforge.ui.assembly",
    "mimforge.ui.authoring",
    "mimforge.ui.deliver",
    "mimforge.ui.drawings",
    "mimforge.ui.icons",
    "mimforge.ui.machine_view",
    "mimforge.ui.main_window",
    "mimforge.ui.motion",
    "mimforge.ui.panels",
    "mimforge.ui.playback",
    "mimforge.ui.sam_picker",
    "mimforge.visuals",
    "mimforge.wiring",
]

# Third-party runtime packages the app depends on directly or one
# hop down (faster-whisper -> ctranslate2/av/tokenizers,
# build123d -> scipy/OCP). Importing them here is the point: a
# package missing from the frozen bundle fails the self-test even
# when the app's own imports of it are lazy.
SELF_TEST_PACKAGES = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtMultimedia",
    "PySide6.QtWidgets",
    "numpy",
    "scipy",
    "build123d",
    "OCP",
    "mujoco",
    "OpenGL",
    "cv2",
    "onnxruntime",
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "lib3mf",
    "cryptography",
]


SELF_TEST_REPORT = "self-test-report.txt"


def self_test(flows: bool = False) -> tuple[int, list[str]]:
    """Import the full graph and construct the main window.

    Offscreen Qt, a throwaway projects directory, no network, no
    Firebase, no user files. Returns ``(0, report)`` (printing
    ``SELF-TEST OK``) on success; prints the traceback and returns
    ``(1, report)`` on any failure. ``report`` is the plain-text
    lines of the whole run -- every flow-probe line plus the
    verdict -- which the entry point writes to
    ``self-test-report.txt`` before exiting (see
    ``_finish_self_test``).

    Gate v2 (Stage 0): in a FROZEN build the real-flow probes
    (``selftest_flows``) always run as part of ``--self-test`` --
    they exercise the bundled ffmpeg/ffprobe, SAM weights, Whisper
    model, Firebase config and sample clip with the OS PATH
    scrubbed, so a resource missing from the bundle fails the
    build here instead of on a user's machine. In a source
    checkout the probes run only when asked (``--self-test=flows``),
    because they need the packaging fetch step's ``bundled/``
    folder to exist.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import importlib
    import tempfile
    import traceback

    report: list[str] = ["Mimforge self-test report"]
    try:
        for name in SELF_TEST_MODULES + SELF_TEST_PACKAGES:
            importlib.import_module(name)
        from PySide6.QtWidgets import QApplication

        from mimforge.ui.main_window import MainWindow

        app = QApplication([])
        with tempfile.TemporaryDirectory(prefix="mimforge-selftest-") as tmp:
            window = MainWindow(projects_dir=os.path.join(tmp, "projects"))
            window.close()
        app.quit()
    except Exception:
        traceback.print_exc()
        report.extend(traceback.format_exc().rstrip().splitlines())
        print("SELF-TEST FAILED", flush=True)
        report.append("SELF-TEST FAILED")
        return 1, report
    if flows or getattr(sys, "frozen", False):
        from mimforge.selftest_flows import flows_main

        flow_lines: list[str] = []
        flow_code = flows_main(collect=flow_lines)
        report.extend(flow_lines)
        if flow_code != 0:
            print("SELF-TEST FAILED (flow probes)", flush=True)
            report.append("SELF-TEST FAILED (flow probes)")
            return 1, report
    print("SELF-TEST OK", flush=True)
    report.append("SELF-TEST OK")
    return 0, report


def _finish_self_test(code: int, report: list[str]) -> None:
    """Write the report file, flush, and hard-exit with ``code``.

    WHY os._exit (the teardown ghost, app edition, 2026-11-27):
    the self-test's verdict is decided and printed by the time
    this runs, but a NORMAL interpreter exit still has to tear
    down every native library the probes loaded -- Qt, MuJoCo/
    GLFW, OCP, onnxruntime, ctranslate2 -- and that teardown
    intermittently crashes AFTER the verdict, so the process
    reports a crash instead of its own result. Windows CI run
    46046846065: the frozen exe ran ~21 s and exited -1073740791
    (0xC0000409, fail-fast abort) with the step's generic "module
    is missing" wording the only trace. Local reproduction on a
    clean-room frozen build (8 consecutive runs): 7 of 8 printed
    all 27 FLOW OK lines and SELF-TEST OK, then died in teardown
    (3x SIGABRT -- stderr ends "pure virtual method called /
    terminate called without an active exception" -- 4x SIGSEGV);
    no run ever failed mid-probe. The root conftest.py carries
    the same fix for the pytest gate (run 46002741151) for the
    same reason.

    So: the full report goes to ``self-test-report.txt`` in the
    current working directory FIRST (a windowed exe's stdout
    reaches nobody on Windows -- the file is the evidence that
    survives), the streams are flushed, and os._exit carries the
    verdict code out directly. The OS reclaims the process image
    wholesale; no native destructor runs. This is SELF-TEST MODE
    ONLY -- the normal GUI entry (``run()``) keeps its ordinary
    exit path, and the report write is best-effort: if it fails,
    the exit code still carries the verdict, exactly as before.
    """
    try:
        with open(SELF_TEST_REPORT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(report) + "\n")
    except OSError:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


# Absolute import: PyInstaller runs this file as a top-level script,
# where a relative import has no parent package and fails. (Importing
# the module does not construct a QApplication, so the self-test can
# still choose the offscreen platform before any window exists.)
from mimforge.ui.main_window import run

if __name__ == "__main__":
    _args = sys.argv[1:]
    if "--self-test=flows" in _args:
        _finish_self_test(*self_test(flows=True))
    if "--self-test" in _args:
        _finish_self_test(*self_test())
    raise SystemExit(run())
