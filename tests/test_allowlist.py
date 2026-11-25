"""Phase 4.1: the allow-list checker passes honest generated code and
fails every seeded malicious sample -- a network call, a direct motor
command, an OS command, dynamic execution, and private-attribute
access.
"""

from mimforge.allowlist import check_source

GOOD_CONTROLLER = '''
from mimforge.models import MotionPrimitiveType
from mimforge.safety import MotionCommand


def run(kernel):
    kernel.execute(MotionCommand(
        primitive=MotionPrimitiveType.TRANSLATE, speed_mm_s=60.0))
'''

GOOD_PANEL = '''
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget


class Panel(QWidget):
    def __init__(self):
        super().__init__()
        self.button = QPushButton("Release")
        self.button.clicked.connect(self.on_release)
        layout = QVBoxLayout(self)
        layout.addWidget(self.button)

    def on_release(self):
        self.button.setText("Released.")
'''

MALICIOUS = {
    "network import": (
        "import socket\nsocket.create_connection(('example.com', 80))",
        "socket",
    ),
    "network import from": (
        "from urllib.request import urlopen\nurlopen('http://example.com')",
        "urllib",
    ),
    "os command": ("import os\nos.system('id')", "os"),
    "subprocess": ("import subprocess\nsubprocess.run(['id'])", "subprocess"),
    "direct motor command": ("motor.set_speed(100)", "motor"),
    "dynamic execution eval": ("eval('1 + 1')", "eval"),
    "dynamic execution exec": ("exec('x = 1')", "exec"),
    "dynamic import": ("__import__('os').system('id')", "__import__"),
    "file access": ("open('/etc/passwd').read()", "open"),
    "private attribute": ("kernel.__dict__", "__dict__"),
    "unknown call": ("frobnicate(kernel)", "frobnicate"),
    "banned method": ("device.write_register(3, 1)", "write_register"),
}


def test_good_generated_code_passes():
    assert check_source(GOOD_CONTROLLER, "controller").passed
    assert check_source(GOOD_PANEL, "panel").passed


def test_controller_profile_rejects_qt_imports():
    report = check_source(GOOD_PANEL, "controller")
    assert not report.passed
    assert any("PySide6" in v for v in report.violations)


def test_every_malicious_sample_fails():
    for name, (source, needle) in MALICIOUS.items():
        report = check_source(source, "controller")
        assert not report.passed, f"{name}: unexpectedly passed"
        assert any(needle in v for v in report.violations), (
            f"{name}: no violation mentions {needle!r}: {report.violations}"
        )


def test_syntax_error_is_a_failure_not_a_crash():
    report = check_source("def broken(:\n", "controller")
    assert not report.passed
    assert "syntax error" in report.violations[0]


def test_unknown_profile_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        check_source(GOOD_CONTROLLER, "not-a-profile")
