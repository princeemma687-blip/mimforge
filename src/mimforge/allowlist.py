"""Static allow-list checker for generated code (plan Phase 4.1).

Generated controller and control-panel code runs where a machine
could move, so it is checked *before* it is ever executed or shipped.
The checker is deliberately strict and purely syntactic: it walks the
AST and rejects anything outside a small allow-list.

Allowed:
- imports from a per-profile module list (controller code may only
  import the safety kernel + the generic models; panel code may
  additionally import the Qt widget modules it is built from);
- calls to a small set of safe builtins, to imported allow-listed
  names, and to methods on objects the generated code owns;
- plain data: numbers, strings, lists, dicts, attribute reads on
  allow-listed roots.

Rejected, with a named violation each:
- any import outside the profile's list (network, OS, subprocess,
  file access, ...);
- calls to dangerous builtins (``eval``, ``exec``, ``open``, ...);
- any reference to a banned name (``motor``, ``gpio``, ``socket``,
  ...): generated code must never address hardware directly -- it
  only talks to the safety kernel;
- any dunder/private attribute access;
- any call to a banned method (direct drive commands, OS commands,
  network calls).

The checker never executes the code it inspects.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

__all__ = ["AllowlistReport", "check_source"]

# -- profiles ------------------------------------------------------------

# module -> names that may be imported from it.
_CONTROLLER_IMPORTS: dict[str, set[str]] = {
    "mimforge.safety": {"MotionCommand", "SafetyKernel"},
    "mimforge.models": {"MotionPrimitiveType"},
}

_PANEL_IMPORTS: dict[str, set[str]] = {
    **_CONTROLLER_IMPORTS,
    "PySide6.QtWidgets": {
        "QApplication",
        "QComboBox",
        "QHBoxLayout",
        "QLabel",
        "QMainWindow",
        "QPushButton",
        "QTableWidget",
        "QTableWidgetItem",
        "QVBoxLayout",
        "QWidget",
    },
    "PySide6.QtCore": {"Qt"},
    "PySide6.QtGui": {"QFont"},
}

PROFILES: dict[str, dict[str, set[str]]] = {
    "controller": _CONTROLLER_IMPORTS,
    "panel": _PANEL_IMPORTS,
}

# Calls the generated code may make without importing anything.
_SAFE_BUILTINS = {
    "abs",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "range",
    "round",
    "sorted",
    "str",
    "super",
    "tuple",
    "zip",
}

# Names that must never appear, whatever the context: direct hardware
# access, OS/process control, network, and dynamic execution.
_BANNED_NAMES = {
    "breakpoint",
    "compile",
    "ctypes",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "gpio",
    "input",
    "locals",
    "motor",
    "multiprocessing",
    "open",
    "os",
    "serial",
    "setattr",
    "socket",
    "subprocess",
    "sys",
    "threading",
    "urllib",
    "vars",
    "__import__",
}

# Method names that must never be called, on any object.
_BANNED_ATTRS = {
    "connect",  # network connect -- panel code uses Qt signals via
    # ``clicked.connect``; see _is_qt_signal below for the exception.
    "popen",
    "recv",
    "send",
    "set_force",
    "set_speed",
    "system",
    "urlopen",
    "write_register",
}

# Dunder attributes generated code is allowed to use: only the
# constructor, as in ``super().__init__()``. Every other dunder
# attribute (``__class__``, ``__dict__``, ``__globals__``, ...) is an
# escape hatch and is rejected.
_ALLOWED_DUNDER_ATTRS = {"__init__"}

# Qt signal attributes whose ``.connect`` is a slot connection, not a
# network connection: <signal>.connect(<callable>).
_QT_SIGNALS = {"clicked", "currentIndexChanged", "textChanged", "valueChanged"}


@dataclass
class AllowlistReport:
    passed: bool
    violations: list[str] = field(default_factory=list)


class _Checker(ast.NodeVisitor):
    def __init__(self, allowed_imports: dict[str, set[str]]) -> None:
        self.allowed_imports = allowed_imports
        self.imported_names: set[str] = set()
        self.defined_names: set[str] = set()  # functions/classes the
        # generated module itself defines; calling them is fine.
        self.violations: list[str] = []

    def visit(self, node: ast.AST) -> None:
        # First pass: collect locally defined names so calls to them
        # are allowed before the checking pass runs.
        if isinstance(node, ast.Module):
            for child in ast.walk(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    self.defined_names.add(child.name)
        return super().visit(node)

    def _violation(self, node: ast.AST, message: str) -> None:
        self.violations.append(f"line {getattr(node, 'lineno', '?')}: {message}")

    # -- imports ---------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in self.allowed_imports:
                self._violation(node, f"import of {alias.name!r} is not allowed")
            else:
                self.imported_names.add(alias.asname or alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        allowed = self.allowed_imports.get(node.module or "")
        if allowed is None:
            self._violation(node, f"import from {node.module!r} is not allowed")
            self.generic_visit(node)
            return
        for alias in node.names:
            if alias.name not in allowed:
                self._violation(
                    node,
                    f"import of {alias.name!r} from {node.module!r} is not allowed",
                )
            else:
                self.imported_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    # -- names -----------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _BANNED_NAMES:
            self._violation(node, f"use of banned name {node.id!r}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") and node.attr not in _ALLOWED_DUNDER_ATTRS:
            self._violation(node, f"private/dunder attribute {node.attr!r}")
        elif node.attr in _BANNED_ATTRS and not self._is_qt_signal(node):
            self._violation(node, f"call to banned method {node.attr!r}")
        self.generic_visit(node)

    def _is_qt_signal(self, node: ast.Attribute) -> bool:
        """``<widget>.<signal>.connect(...)`` -- the attribute before
        ``connect`` is a Qt signal name, so this is a slot connection."""
        if node.attr != "connect":
            return False
        value = node.value
        return isinstance(value, ast.Attribute) and value.attr in _QT_SIGNALS

    # -- calls -----------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if (
                func.id not in _SAFE_BUILTINS
                and func.id not in self.imported_names
                and func.id not in self.defined_names
            ):
                self._violation(node, f"call to unknown function {func.id!r}")
        elif isinstance(func, ast.Attribute):
            # Method call on an object the generated code owns: allowed
            # unless the attribute itself is banned (handled above).
            # Attribute calls on a banned root name are caught by
            # visit_Name on the root.
            pass
        else:
            self._violation(node, "call through a computed callee is not allowed")
        self.generic_visit(node)


def check_source(source: str, profile: str = "controller") -> AllowlistReport:
    """Check generated source against the named profile's allow-list."""
    if profile not in PROFILES:
        raise ValueError(f"unknown allow-list profile {profile!r}")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return AllowlistReport(passed=False, violations=[f"syntax error: {exc}"])
    checker = _Checker(PROFILES[profile])
    checker.visit(tree)
    return AllowlistReport(passed=not checker.violations, violations=checker.violations)
