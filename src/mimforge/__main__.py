"""Mimforge desktop application entry point.

``python -m mimforge`` launches the mission-control shell. The
packaged (PyInstaller) build uses the same entry point.
"""

from __future__ import annotations

# Absolute import: PyInstaller runs this file as a top-level script,
# where a relative import has no parent package and fails.
from mimforge.ui.main_window import run

if __name__ == "__main__":
    raise SystemExit(run())
