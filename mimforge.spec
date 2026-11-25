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

binaries = []
hiddenimports = [
    "mimforge",
    "mimforge.adjust",
    "mimforge.allowlist",
    "mimforge.bom",
    "mimforge.codegen",
    "mimforge.config",
    "mimforge.design",
    "mimforge.discrepancy",
    "mimforge.models",
    "mimforge.narration",
    "mimforge.outcome",
    "mimforge.perception",
    "mimforge.playback",
    "mimforge.projects",
    "mimforge.risk",
    "mimforge.safety",
    "mimforge.signing",
    "mimforge.simulation",
    "mimforge.structuring",
    "mimforge.sync",
    "mimforge.templates",
    "mimforge.ui.authoring",
    "mimforge.ui.main_window",
    "mimforge.ui.playback",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "numpy",
    "cv2",
    "faster_whisper",
    "ctranslate2",
    "av",
    "cryptography",
    "build123d",
    "OCP",
    "mujoco",
]

# MuJoCo ships native libraries + model data that Analysis does not
# pick up from imports alone; collect the whole package.
for _pkg in ("mujoco", "build123d", "OCP"):
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
    excludes=["tkinter", "matplotlib", "scipy", "PIL"],
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
