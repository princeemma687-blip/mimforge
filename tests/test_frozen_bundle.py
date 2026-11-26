"""Frozen-bundle guards (2026-11-26 launch crash).

Run #6 crashed on the user's laptop with ``No module named
'scipy'``: build123d imports scipy at module load, scipy was in
the dev venv (so all 295 tests passed), but ``mimforge.spec``
listed scipy in its PyInstaller ``excludes`` and nothing collected
it into the bundle. These tests pin the packaging to the app's
real import graph so the whole class of failure -- a runtime
package missing from the frozen bundle -- fails HERE, in the
suite, instead of on a user's machine:

- every runtime package is covered by the spec (collect_all or
  hiddenimports), and none is excluded;
- scipy specifically is collect_all'd, not excluded, and declared
  in pyproject (removing it from the spec fails these tests);
- the AST import scan of ``src/mimforge`` stays inside the
  maintained RUNTIME_PACKAGES list (a new third-party import
  forces a packaging decision);
- ``__main__``'s self-test module list matches the source tree;
- ``python -m mimforge --self-test`` runs green as a subprocess.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SPEC = ROOT / "mimforge.spec"

# Maintained from the import scan of src/mimforge (direct imports
# plus the one-hop runtime needs of the lazy paths). Value = how
# mimforge.spec must cover the package:
#   "collect_all"  -- native libs / data files / lazy submodules
#                     require collecting the whole package;
#   "hiddenimport" -- a hiddenimports entry (PyInstaller's bundled
#                     hook handles its native parts).
RUNTIME_PACKAGES = {
    "PySide6": "hiddenimport",
    "numpy": "hiddenimport",
    "scipy": "collect_all",
    "build123d": "collect_all",
    "OCP": "collect_all",
    "mujoco": "collect_all",
    "cv2": "hiddenimport",
    "onnxruntime": "collect_all",
    "faster_whisper": "collect_all",
    "ctranslate2": "collect_all",
    "av": "collect_all",
    "tokenizers": "collect_all",
    # build123d.mesher imports lib3mf at module load; lib3mf loads
    # its native binary by path, so the whole package must ship.
    "lib3mf": "collect_all",
    "huggingface_hub": "hiddenimport",
    "cryptography": "hiddenimport",
}


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _spec_collect_all() -> set[str]:
    """Package names in the spec's ``for _pkg in (...): collect_all`` loop."""
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            names = {
                elt.value
                for elt in node.iter.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
            body = ast.dump(node)
            if "collect_all" in body and names:
                return names
    raise AssertionError("no collect_all loop found in mimforge.spec")


def _spec_hiddenimports() -> set[str]:
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "hiddenimports" for t in node.targets
        ):
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    raise AssertionError("no hiddenimports list found in mimforge.spec")


def _spec_excludes() -> set[str]:
    for node in ast.walk(_spec_tree()):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "excludes" and isinstance(kw.value, ast.List):
                    return {
                        elt.value
                        for elt in kw.value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)
                    }
    raise AssertionError("no excludes list found in mimforge.spec")


def _covered(name: str, hiddenimports: set[str]) -> bool:
    return any(h == name or h.startswith(name + ".") for h in hiddenimports)


def test_every_runtime_package_is_covered_by_the_spec():
    collect = _spec_collect_all()
    hidden = _spec_hiddenimports()
    for pkg, how in RUNTIME_PACKAGES.items():
        if how == "collect_all":
            assert pkg in collect, (
                f"{pkg} must be collect_all'd in mimforge.spec "
                "(native/data-carrying runtime package)"
            )
        else:
            assert _covered(pkg, hidden) or pkg in collect, (
                f"{pkg} must appear in the spec's hiddenimports"
            )


def test_no_runtime_package_is_excluded():
    excludes = _spec_excludes()
    for pkg in RUNTIME_PACKAGES:
        assert pkg not in excludes, (
            f"{pkg} is a runtime package but mimforge.spec excludes it -- "
            "that is exactly the 2026-11-26 scipy launch crash"
        )


def test_scipy_is_collected_and_declared():
    """The named regression: removing scipy from the spec fails here."""
    assert "scipy" in _spec_collect_all()
    assert "scipy" not in _spec_excludes()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"scipy' in pyproject, "scipy must be a declared dependency"


def _third_party_imports() -> set[str]:
    stdlib = set(sys.stdlib_module_names)
    found: set[str] = set()
    for path in (SRC / "mimforge").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
            ):
                mods = [node.module]
            for mod in mods:
                top = mod.split(".")[0]
                if top not in stdlib and top != "mimforge":
                    found.add(top)
    return found


def test_import_graph_stays_inside_runtime_packages():
    imported = _third_party_imports()
    unlisted = imported - set(RUNTIME_PACKAGES)
    assert not unlisted, (
        f"src/mimforge imports {sorted(unlisted)} which are not in "
        "RUNTIME_PACKAGES -- add them here AND cover them in mimforge.spec"
    )


def test_self_test_module_list_matches_source_tree():
    main_py = ast.parse((SRC / "mimforge" / "__main__.py").read_text(encoding="utf-8"))
    listed: set[str] | None = None
    for node in ast.walk(main_py):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SELF_TEST_MODULES"
            for t in node.targets
        ):
            listed = {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    assert listed is not None, "SELF_TEST_MODULES not found in __main__.py"

    expected: set[str] = set()
    for path in (SRC / "mimforge").rglob("*.py"):
        if path.name == "__main__.py":
            continue  # the entry point itself; it runs the self-test
        parts = list(path.relative_to(SRC).parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]
        expected.add(".".join(parts))
    assert listed == expected, (
        f"SELF_TEST_MODULES drifted from the source tree: "
        f"missing={sorted(expected - listed)} extra={sorted(listed - expected)}"
    )


def test_self_test_subprocess_passes():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["MIMFORGE_MOTION"] = "off"
    proc = subprocess.run(
        [sys.executable, "-m", "mimforge", "--self-test"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"--self-test exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    assert "SELF-TEST OK" in proc.stdout
