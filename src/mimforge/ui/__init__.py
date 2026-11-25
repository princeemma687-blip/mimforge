"""Mimforge desktop shell (plan Phase 1, step 1.1).

Design rule (binding, owner 2026-11-25): every UI surface is
ARCHITECTURAL, TECHY, PREMIUM -- blueprint-style elevations with
dimension lines, drafting grid, dark charcoal with one electric accent,
mono type for measurements and code, mission-control control panels.
Never a plain or default-looking UI.

The one electric accent is cyan; the E-stop control is the single
safety-signal exception (signal red outline, as a stop control must
read as a stop at a glance).
"""

from .main_window import MainWindow

__all__ = ["MainWindow"]
