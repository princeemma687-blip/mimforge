"""Anti-pendulum rule (docs/SCOPE_FREEZE.md): the first demonstration is
template DATA only. If any demo-specific term appears in a core module,
the generic design has leaked and the build fails.

Alphabetic terms are matched as whole words: a naive substring scan
false-positives on ordinary identifiers (``QComboBox`` contains
``bob``), so word boundaries are required. Symbolic terms (``t^2``,
``9.81``) are matched as substrings -- they cannot hide inside an
innocent identifier.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "mimforge"

# Alphabetic terms: whole-word match only.
WORD_TERMS = [
    "pendulum",
    "bob",
    "gravity",
    "fiducial",
    "retort",
]

# Symbolic terms: substring match.
SUBSTRING_TERMS = [
    "t\u00b2",  # T²
    "t^2",
    "9.81",
    "4\u03c0\u00b2",  # 4π² (the demo's slope formula)
]


def scan_text(text: str) -> list[str]:
    """Return the forbidden terms found in ``text`` (lower-cased)."""
    lowered = text.lower()
    found = []
    for term in WORD_TERMS:
        # Bounded by anything that is not a letter: a snake_case
        # identifier (``load_bob_position``) is a leak, while the
        # letters inside a longer word (``QComboBox``) are not.
        if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", lowered):
            found.append(term)
    for term in SUBSTRING_TERMS:
        if term.lower() in lowered:
            found.append(term)
    return found


def core_files() -> list[Path]:
    files = []
    for path in SRC.rglob("*.py"):
        if "templates" in path.parts:
            continue  # template data + its loader are allowed specifics
        files.append(path)
    return files


def test_core_contains_no_demo_specific_terms():
    failures = []
    for path in core_files():
        for term in scan_text(path.read_text(encoding="utf-8")):
            failures.append(f"{path.name}: forbidden term {term!r}")
    assert not failures, (
        "Demo-specific terms leaked into core code:\n" + "\n".join(failures)
    )


def test_scan_actually_covers_core_modules():
    names = {p.name for p in core_files()}
    assert {"__init__.py", "models.py", "config.py"} <= names


def test_scan_catches_real_leaks_but_not_ordinary_identifiers():
    # A real leak, written as a word, is caught ...
    assert "bob" in scan_text("x = load_bob_position()")
    assert "pendulum" in scan_text("# the pendulum swings here")
    assert "9.81" in scan_text("g = 9.81")
    assert "t^2" in scan_text("y = t^2")
    # ... while an ordinary identifier that merely contains the
    # letters is not a leak.
    assert scan_text("from PySide6.QtWidgets import QComboBox") == []
    assert scan_text("self.length_selector = QComboBox()") == []
