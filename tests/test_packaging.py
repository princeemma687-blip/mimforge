"""Phase 6.2, packaging: the entry point, console script, PyInstaller
spec and installer script are present and consistent. (The actual
binary build is a manual step -- see docs/PACKAGING.md -- because it
takes minutes and needs the full dependency set.)"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_main_entry_point_runs_the_window():
    from mimforge.ui.main_window import run

    assert callable(run)
    import mimforge.__main__ as entry

    assert entry.run is run


def test_console_script_declared_in_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'mimforge = "mimforge.ui.main_window:run"' in text


def test_pyinstaller_spec_covers_the_app():
    spec = (ROOT / "mimforge.spec").read_text(encoding="utf-8")
    assert "__main__.py" in spec
    assert "mimforge/templates" in spec
    assert "collect_all" in spec and "mujoco" in spec
    assert "COLLECT" in spec  # onedir, not onefile (LGPL libraries separate)
    assert "LICENSE" in spec
    for module in (
        "mimforge.playback",
        "mimforge.simulation",
        "mimforge.design",
        "mimforge.ui.playback",
    ):
        assert module in spec


def test_installer_script_references_the_build_output():
    iss = (ROOT / "setup" / "mimforge.iss").read_text(encoding="utf-8")
    assert r"..\dist\Mimforge\*" in iss
    assert "Mimforge.exe" in iss
    assert "LicenseFile=..\\LICENSE" in iss


def test_build_script_gates_on_the_full_test_suite():
    script = (ROOT / "setup" / "build-windows.ps1").read_text(encoding="utf-8")
    assert "pytest -q" in script
    assert "pyinstaller" in script
    assert "mimforge.iss" in script
    # The suite must run BEFORE the build, and a failure must stop it.
    assert script.index("pytest -q") < script.index("pyinstaller --noconfirm")


def test_packaging_doc_records_what_was_verified_where():
    doc = (ROOT / "docs" / "PACKAGING.md").read_text(encoding="utf-8")
    assert "not run here" in doc
    assert "Prince's laptop step" in doc
    assert "FFmpeg is not bundled" in doc


@pytest.mark.skipif(sys.platform == "win32", reason="Windows-only check")
def test_spec_is_windowed_only_on_windows():
    spec = (ROOT / "mimforge.spec").read_text(encoding="utf-8")
    assert 'WINDOWED = sys.platform == "win32"' in spec
