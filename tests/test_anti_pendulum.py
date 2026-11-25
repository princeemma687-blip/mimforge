"""Anti-pendulum rule (docs/SCOPE_FREEZE.md): the first demonstration is
template DATA only. If any demo-specific term appears in a core module,
the generic design has leaked and the build fails.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "mimforge"

FORBIDDEN_TERMS = [
    "pendulum",
    "bob",
    "t\u00b2",  # T²
    "t^2",
    "9.81",
    "gravity",
    "fiducial",
    "retort",
    "4\u03c0\u00b2",  # 4π² (the demo's slope formula)
]


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
        text = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_TERMS:
            if term.lower() in text:
                failures.append(f"{path.name}: forbidden term {term!r}")
    assert not failures, (
        "Demo-specific terms leaked into core code:\n" + "\n".join(failures)
    )


def test_scan_actually_covers_core_modules():
    names = {p.name for p in core_files()}
    assert {"__init__.py", "models.py", "config.py"} <= names
