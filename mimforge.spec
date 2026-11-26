# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Mimforge (plan Phase 6.2).

Build on Windows with ``setup\\build-windows.ps1``. A Linux build from
the same spec is a smoke test only -- the shipped installer is the
Windows one built by Inno Setup from the ``dist/Mimforge`` folder.

Onedir (not onefile): PySide6/Qt and the OCCT kernel are LGPL, so
their libraries ship as separate files next to the executable with
the licence notices (see docs/SBOM.md), not baked into one blob.
"""

import base64
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller

# Windowed on Windows (no console window behind the GUI); console on
# other platforms so a smoke-test build can print diagnostics.
WINDOWED = sys.platform == "win32"

# The app icon binaries (mimforge.ico, icon_256.png) travel as base64
# text (assets/branding/*.b64) because the snapshot route that
# publishes this repository carries UTF-8 text only. Materialise the
# real files before Analysis/EXE reference them below; where they
# already exist (a local checkout) they are refreshed with identical
# bytes. The vector source is assets/branding/logo_c.svg.
_BRANDING = SPEC_DIR / "assets" / "branding"
for _icon_name in ("mimforge.ico", "icon_256.png"):
    _b64_file = _BRANDING / f"{_icon_name}.b64"
    if _b64_file.is_file():
        (_BRANDING / _icon_name).write_bytes(
            base64.decodebytes(_b64_file.read_bytes())
        )

datas = [
    (str(SPEC_DIR / "src" / "mimforge" / "templates" / "*.json"),
     "mimforge/templates"),
    (str(SPEC_DIR / "src" / "mimforge" / "templates" / "*.xml"),
     "mimforge/templates"),
    (str(SPEC_DIR / "LICENSE"), "."),
    (str(SPEC_DIR / "docs" / "SBOM.md"), "docs"),
    # App icon (logo C "Machine Frame", picked by the owner 2026-11-25):
    # bundled so the frozen app can set its window icon at runtime; the
    # matching mimforge.ico is the EXE icon below.
    (str(SPEC_DIR / "assets" / "branding" / "icon_256.png"),
     "assets/branding"),
]

# Stage 0 (2026-11-26): the bundled runtime resources staged by
# setup/fetch_bundled_assets.py into the repo-local bundled/ folder
# -- ffmpeg/ffprobe (+ shared libraries + LGPL notices), the SAM
# 2.1 weights, the Whisper base model, the generated Firebase
# config, and the self-test sample clip. They ship under
# mimforge_resources/ and mimforge.resources resolves them there.
# When bundled/ is absent (a source checkout that never ran the
# fetch step) the app simply reports those features NOT SET UP;
# the frozen Gate v2 self-test fails such a build on purpose.
_BUNDLED_ROOT = SPEC_DIR / "bundled"
if _BUNDLED_ROOT.is_dir():
    for _res_path in sorted(_BUNDLED_ROOT.rglob("*")):
        if _res_path.is_file():
            _res_rel = _res_path.relative_to(_BUNDLED_ROOT)
            datas.append(
                (
                    str(_res_path),
                    str(Path("mimforge_resources") / _res_rel.parent),
                )
            )

binaries = []
hiddenimports = [
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
    "mimforge.structuring",
    "mimforge.sync",
    "mimforge.templates",
    "mimforge.verification",
    "mimforge.ui.authoring",
    "mimforge.ui.deliver",
    "mimforge.ui.main_window",
    "mimforge.ui.motion",
    "mimforge.ui.panels",
    "mimforge.ui.playback",
    "mimforge.ui.sam_picker",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "numpy",
    "scipy",
    "cv2",
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "lib3mf",
    "huggingface_hub",
    "onnxruntime",
    "cryptography",
    "build123d",
    "OCP",
    "mujoco",
]

# Native/data-heavy runtime packages ship libraries, data files and
# lazily-imported submodules that Analysis does not pick up from
# imports alone; collect each whole package. scipy is here because
# build123d imports it at module load -- the 2026-11-26 run #6
# launch crash was scipy missing from the bundle while every test
# passed in the dev venv. tests/test_frozen_bundle.py guards this
# list against the app's real import graph.
for _pkg in (
    "mujoco",
    "build123d",
    "OCP",
    "scipy",
    "onnxruntime",
    "ctranslate2",
    "faster_whisper",
    "av",
    "tokenizers",
    # build123d.mesher does `from lib3mf import Lib3MF` at module
    # load and lib3mf loads its native binary by path; found by the
    # frozen self-test right after the scipy fix (same crash class,
    # one import later).
    "lib3mf",
):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(  # noqa: F821 - PyInstaller DSL
    [str(SPEC_DIR / "src" / "mimforge" / "__main__.py")],
    pathex=[str(SPEC_DIR / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # NEVER exclude a package that is installed as part of the
    # resolved dependency set: build123d imports scipy at module
    # load, and this list previously excluded scipy (and PIL),
    # which crashed run #6 on launch on the user's laptop
    # (2026-11-26) while the whole test suite passed in the venv.
    # tkinter/matplotlib stay excluded: nothing in the import
    # graph uses them (guarded by tests/test_frozen_bundle.py).
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821 - PyInstaller DSL

exe = EXE(  # noqa: F821 - PyInstaller DSL
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mimforge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not WINDOWED,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / "assets" / "branding" / "mimforge.ico"),
)

coll = COLLECT(  # noqa: F821 - PyInstaller DSL
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mimforge",
)
