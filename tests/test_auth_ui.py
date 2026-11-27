"""Sign-in surface + live-sync gating (2026-11-26), driven through
the real widgets offscreen.

The transport is a fake that speaks the real Identity Toolkit and
Firestore wire shapes for BOTH the auth client (injected at the
window's documented factory seam) and the Firestore backend (whose
default opener resolves to ``urllib.request.urlopen`` at call time,
patched here). Everything between the widgets and that transport --
the panel, the window's gating, the backend's per-user layout -- is
the real code.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.firebase_auth import FirebaseAuthClient  # noqa: E402
from mimforge.ui.main_window import MainWindow  # noqa: E402
from test_auth import FakeFirebase  # noqa: E402  (tests run top-level)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _write_env(tmp_path) -> Path:
    env_file = tmp_path / "sync.env"
    env_file.write_text(
        "FIREBASE_API_KEY=<redacted>\n"
        "FIREBASE_PROJECT_ID=test-project\n",
        encoding="utf-8",
    )
    return env_file


def _window(tmp_path, fake: FakeFirebase, **kwargs) -> MainWindow:
    def auth_factory(config, session_path):
        return FirebaseAuthClient(
            config, session_path=session_path, opener=fake
        )

    return MainWindow(
        projects_dir=tmp_path / "projects",
        auth_client_factory=auth_factory,
        **kwargs,
    )


def _type_credentials(window: MainWindow) -> None:
    panel = window.projects_panel
    panel.email_edit.setText("teacher@school.ng")
    panel.password_edit.setText("secret1")


def test_signed_out_by_default_and_app_fully_usable(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(tmp_path / "absent.env"))
    window = _window(tmp_path, FakeFirebase())
    panel = window.projects_panel
    assert panel.auth_status_label.text() == "ACCOUNT: NOT SIGNED IN"
    # Sign-in with no settings is a plain status, not a crash...
    _type_credentials(window)
    panel.sign_in_button.click()
    assert "NOT SET UP" in panel.auth_status_label.text()
    # ...and the app itself never needed the account.
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText("Morning Class")
    panel.create_button.click()
    assert window.current_project is not None


def test_create_account_sign_in_and_sign_out(app, tmp_path, monkeypatch):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(_write_env(tmp_path)))
    fake = FakeFirebase()
    window = _window(tmp_path, fake)
    panel = window.projects_panel
    _type_credentials(window)
    panel.create_account_button.click()
    assert (
        panel.auth_status_label.text()
        == "ACCOUNT: SIGNED IN AS teacher@school.ng"
    )
    assert window.signed_in_email == "teacher@school.ng"
    # The password is not left sitting in the box.
    assert panel.password_edit.text() == ""
    panel.sign_out_button.click()
    assert panel.auth_status_label.text() == "ACCOUNT: NOT SIGNED IN"
    assert window.signed_in_email is None


def test_wrong_password_is_plain_words(app, tmp_path, monkeypatch):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(_write_env(tmp_path)))
    fake = FakeFirebase()
    window = _window(tmp_path, fake)
    panel = window.projects_panel
    _type_credentials(window)
    panel.create_account_button.click()
    panel.sign_out_button.click()
    panel.email_edit.setText("teacher@school.ng")
    panel.password_edit.setText("wrong-pass")
    panel.sign_in_button.click()
    status = panel.auth_status_label.text()
    assert "DOES NOT MATCH" in status
    assert "INVALID_PASSWORD" not in status  # never the raw code
    assert window.signed_in_email is None


def test_sync_toggle_requires_sign_in(app, tmp_path, monkeypatch):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(_write_env(tmp_path)))
    window = _window(tmp_path, FakeFirebase())
    panel = window.projects_panel
    panel.sync_button.click()
    assert not window.sync_on
    assert "NOT SIGNED IN" in panel.sync_status_label.text()
    assert panel.sync_button.text() == "SYNC: OFF"


def test_signed_in_sync_round_trips_through_the_widgets(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(_write_env(tmp_path)))
    fake = FakeFirebase()
    # The Firestore backend's default opener is urlopen; route it
    # to the same fake transport the auth client uses.
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=None: fake(request)
    )
    window = _window(tmp_path, fake)
    panel = window.projects_panel
    _type_credentials(window)
    panel.create_account_button.click()
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText("Synced Class")
    panel.create_button.click()
    project = window.current_project
    assert project is not None
    panel.sync_button.click()
    assert window.sync_on
    status = panel.sync_status_label.text()
    assert "PROJECT DETAILS SENT" in status
    assert "SYNCED" in status
    # The document landed in the signed-in user's own subtree.
    expected = f"users/uid-1/sync/projects__{project.project_id}"
    assert expected in fake.documents
    # Signing out turns sync off with the account.
    panel.sign_out_button.click()
    assert not window.sync_on
    assert "SYNC: OFF" in panel.sync_status_label.text()


def test_session_restores_in_a_new_window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(_write_env(tmp_path)))
    fake = FakeFirebase()
    first = _window(tmp_path, fake)
    _type_credentials(first)
    first.projects_panel.create_account_button.click()
    assert first.signed_in_email == "teacher@school.ng"
    second = _window(tmp_path, fake)
    assert (
        second.projects_panel.auth_status_label.text()
        == "ACCOUNT: SIGNED IN AS teacher@school.ng"
    )
    assert second.signed_in_email == "teacher@school.ng"
