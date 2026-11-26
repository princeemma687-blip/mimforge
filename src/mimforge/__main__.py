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
    "mimforge.bom",
    "mimforge.checker",
    "mimforge.codegen",
    "mimforge.config",
    "mimforge.delivery",
    "mimforge.design",
    "mimforge.discrepancy",
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
    "mimforge.verification",
    "mimforge.ui",
    "mimforge.ui.authoring",
    "mimforge.ui.deliver",
    "mimforge.ui.machine_view",
    "mimforge.ui.main_window",
    "mimforge.ui.motion",
    "mimforge.ui.panels",
    "mimforge.ui.playback",
    "mimforge.ui.sam_picker",
    "mimforge.visuals",
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


def self_test(flows: bool = False) -> int:
    """Import the full graph and construct the main window.

    Offscreen Qt, a throwaway projects directory, no network, no
    Firebase, no user files. Returns 0 (printing ``SELF-TEST OK``)
    on success; prints the traceback and returns 1 on any failure.

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
        print("SELF-TEST FAILED", flush=True)
        return 1
    if flows or getattr(sys, "frozen", False):
        from mimforge.selftest_flows import flows_main

        if flows_main() != 0:
            print("SELF-TEST FAILED (flow probes)", flush=True)
            return 1
    print("SELF-TEST OK", flush=True)
    return 0


# Absolute import: PyInstaller runs this file as a top-level script,
# where a relative import has no parent package and fails. (Importing
# the module does not construct a QApplication, so the self-test can
# still choose the offscreen platform before any window exists.)
from mimforge.ui.main_window import run

if __name__ == "__main__":
    _args = sys.argv[1:]
    if "--self-test=flows" in _args:
        raise SystemExit(self_test(flows=True))
    if "--self-test" in _args:
        raise SystemExit(self_test())
    raise SystemExit(run())
