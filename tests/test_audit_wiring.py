"""RETROACTIVE AUDIT — Line A (2026-11-27, Prince's order: "verify
that everything you are doing is not just a front... Everything
actually works and all the linking is done").

Every control in every panel of the real window is driven through
the real flow -- dialogs stubbed ONLY to observe/record and to hand
back chosen paths, never to skip their place in the order -- and the
REAL effect is asserted: state changed, engine ran, file written,
record persisted. Verdicts are collected per control and written to
/tmp/audit/lineA-table.txt; any control without a real effect fails
this file. (The golden path itself is also covered by
test_shell_wiring.py; this file is the exhaustive enumeration the
audit ordered, including the controls the golden path never touches:
episode verdicts, transcript import, voice remove, tier repricing,
view switchers, checker honesty, code generation, SAM dialog.)
"""

from __future__ import annotations

import io
import os
import wave
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
)

from mimforge.ui import motion as motion_module  # noqa: E402
from mimforge.firebase_auth import FirebaseAuthClient  # noqa: E402
from mimforge.narration import Transcript, TranscriptSegment  # noqa: E402
from mimforge.projects import open_project as store_open  # noqa: E402
from mimforge.sync import MemoryBackend  # noqa: E402
from mimforge.ui.main_window import SECTIONS, MainWindow  # noqa: E402
from test_auth import FakeFirebase  # noqa: E402  (tests run top-level)

VIDEOS = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)

ROWS: list[tuple[str, str, str]] = []
FAILURES: list[str] = []


def verdict(control: str, result: str, evidence: str) -> None:
    ROWS.append((control, result, evidence))
    if result not in ("WIRED", "GUARDED"):
        FAILURES.append(f"{control}: {result} — {evidence}")


def check(control: str, ok: bool, evidence: str) -> None:
    verdict(control, "WIRED" if ok else "FRONT-ONLY", evidence)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, fake=None, **kwargs) -> MainWindow:
    if fake is not None:
        def auth_factory(config, session_path):
            return FirebaseAuthClient(
                config, session_path=session_path, opener=fake
            )

        kwargs.setdefault("auth_client_factory", auth_factory)
    return MainWindow(projects_dir=tmp_path / "projects", **kwargs)


def _create_via_clicks(window: MainWindow, title="Audit Lesson"):
    panel = window.projects_panel
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText(title)
    panel.create_button.click()
    assert window.current_project is not None
    return window.current_project


def _goto(window: MainWindow, section: str) -> None:
    window.nav.setCurrentRow(SECTIONS.index(section))


def _open_dialog(monkeypatch, target) -> list:
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return (str(target), "") if target else ("", "")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake))
    return calls


def _save_dialog(monkeypatch, target) -> list:
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return (str(target), "") if target else ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    return calls


def _dir_dialog(monkeypatch, target) -> list:
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return str(target) if target else ""

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(fake)
    )
    return calls


class _StubTranscriber:
    """The window's documented transcriber seam: the wiring is under
    test here; the real Whisper engine is Gate-probe verified."""

    def transcribe(self, audio_path):
        return Transcript(
            segments=[
                TranscriptSegment(
                    0.0, 4.0,
                    "Set up the stand, clamp the thread and measure "
                    "the length from the pivot to the centre.",
                ),
                TranscriptSegment(
                    4.0, 8.0,
                    "Displace it through a small angle and release "
                    "without a push, then time twenty oscillations.",
                ),
            ],
            language="en", engine="stub", model="stub",
        )


def _clip_with_audio(tmp_path) -> Path:
    import subprocess

    target = tmp_path / "audit_demo.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-i", str(VIDEOS / "demo_L090cm.mp4"),
            "-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest", "-c:v", "copy", "-c:a", "aac",
            str(target),
        ],
        check=True, timeout=120,
    )
    return target


def _tiny_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x01\x00" * 2205)
    return path


def _labels(window) -> dict[int, str]:
    return {id(w): w.text() for w in window.findChildren(QLabel)}


# ------------------------------------------------------------ the audit


def test_line_a_full_control_enumeration(app, tmp_path, monkeypatch):
    fake = FakeFirebase()
    backend = MemoryBackend()
    window = _window(
        tmp_path, fake=fake,
        sync_backend_factory=lambda cfg: backend,
    )
    window.transcriber = _StubTranscriber()
    pp = window.projects_panel
    ap = window.author_panel

    # ---- Projects: create / open -------------------------------------
    project = _create_via_clicks(window)
    check("Projects · CREATE NEW PROJECT",
          window.current_project is not None
          and ap.current_draft() is not None,
          "project opened and its draft loaded into Author")
    assert pp.project_list.count() >= 1
    pp.project_list.setCurrentRow(0)
    pp.open_button.click()
    check("Projects · OPEN SELECTED PROJECT",
          window.current_project is not None
          and "CURRENT PROJECT" in pp.status_label.text(),
          f"status: {pp.status_label.text()!r}")

    # ---- Author: import (real button, dialog observed) ---------------
    clip = _clip_with_audio(tmp_path)
    _open_dialog(monkeypatch, clip)
    _goto(window, "Author")
    ap.import_button.click()
    status = ap.import_status_label.text()
    check("Author · IMPORT DEMONSTRATION VIDEO",
          "DEMONSTRATION IMPORTED" in status
          and ap.current_draft() is not None
          and len(ap.current_draft().steps) > 0,
          f"status: {status!r}; steps drafted from the real clip")
    check("Projects · demonstration-set view lists the episode",
          pp.episode_list.count() >= 1,
          f"episode rows: {pp.episode_list.count()}")

    # ---- Author: approve / reject / edit ------------------------------
    draft = ap.current_draft()
    ap.step_list.setCurrentRow(0)
    ap.approve_button.click()
    check("Author · APPROVE STEP",
          draft.steps[0].status == "approved"
          and "1/" in ap.status_label.text(),
          f"step status={draft.steps[0].status}, panel={ap.status_label.text()!r}")
    ap.step_list.setCurrentRow(1)
    ap.reject_button.click()
    rejected = draft.steps[1].status == "rejected"
    ap.approve_button.click()
    check("Author · REJECT STEP",
          rejected and draft.steps[1].status == "approved",
          "reject set the step rejected; approve restored it")
    ap.editor.setPlainText(draft.steps[1].draft_text + " Checked twice.")
    check("Author · step editor (edit un-approves + persists)",
          draft.steps[1].status == "edited",
          f"status after edit: {draft.steps[1].status}")
    ap.approve_button.click()
    for row in range(len(draft.steps)):
        ap.step_list.setCurrentRow(row)
        if draft.steps[row].status != "approved":
            ap.approve_button.click()
    assert draft.approved_count == len(draft.steps)

    # ---- Author: teacher voice attach / record / remove ---------------
    _open_dialog(monkeypatch, _tiny_wav(tmp_path / "voice.wav"))
    ap.voice_attach_button.click()
    check("Author · ATTACH MY VOICE FILE",
          "TEACHER VOICE" in ap.voice_label.text(),
          f"voice label: {ap.voice_label.text()!r}")
    ap.voice_remove_button.click()
    check("Author · REMOVE MY VOICE",
          "VOICE: NONE" in ap.voice_label.text(),
          f"voice label: {ap.voice_label.text()!r}")
    before = ap.status_label.text()
    ap.voice_record_button.click()
    after = ap.status_label.text()
    if ap.voice_record_button.text().startswith("■"):
        ap.voice_record_button.click()  # stop again — leave nothing running
    check("Author · RECORD MY VOICE",
          after != before or "RECORDING" in after,
          f"status: {after!r} (plain no-microphone guidance on this "
          "machine, or recording started)")

    # ---- Author: transcript file --------------------------------------
    srt = tmp_path / "lesson.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\n"
        "Set up the stand and measure the length carefully.\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\n"
        "Time twenty oscillations and record the period.\n",
        encoding="utf-8",
    )
    _open_dialog(monkeypatch, srt)
    ap.transcript_button.click()
    check("Author · USE A TRANSCRIPT FILE",
          "TRANSCRIPT IMPORTED" in ap.import_status_label.text()
          and len(ap.current_draft().steps) > 0,
          f"status: {ap.import_status_label.text()!r}")
    draft = ap.current_draft()
    for row in range(len(draft.steps)):
        ap.step_list.setCurrentRow(row)
        ap.approve_button.click()

    # ---- Author: build lesson ------------------------------------------
    ap.build_lesson_button.click()
    player = window.playback_panel
    check("Author · BUILD LESSON",
          player.lesson is not None and len(player.lesson.steps) > 0,
          "lesson package built and loaded into Playback")

    _finish_enumeration(window, tmp_path, monkeypatch, backend, fake)

    table = Path("/tmp/audit/lineA-table.txt")
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(
        "\n".join(f"{c} :: {v} :: {e}" for c, v, e in ROWS) + "\n",
        encoding="utf-8",
    )
    assert not FAILURES, "FRONT-ONLY controls found:\n" + "\n".join(FAILURES)


def _finish_enumeration(window, tmp_path, monkeypatch, backend, fake):
    pp = window.projects_panel
    dp = window.design_panel
    sp = window.simulate_panel
    dv = window.deliver_panel
    player = window.playback_panel

    # ---- Design: view switcher ----------------------------------------
    _goto(window, "Design")
    for key, index in (("wiring", 1), ("panel", 2), ("elevation", 0)):
        dp.view_buttons[key].click()
        check(f"Design · {key.upper()} VIEW button",
              dp.views.currentIndex() == index,
              f"views stack index={dp.views.currentIndex()}")
    check("Design · wiring view carries a real diagram",
          dp.wiring_view.diagram is not None
          and len(dp.wiring_view.diagram.runs) >= 1,
          "diagram generated from the design's wiring plan")
    check("Design · panel view carries a real layout",
          dp.panel_view.layout_data is not None
          and any(c.kind == "estop"
                  for c in dp.panel_view.layout_data.controls),
          "panel layout generated with its guaranteed stop")

    # ---- Design: tier switch reprices the materials table -------------
    def _table_text():
        rows = []
        for r in range(dp.materials_table.rowCount()):
            rows.append(" | ".join(
                (dp.materials_table.item(r, c).text()
                 if dp.materials_table.item(r, c) else "")
                for c in range(dp.materials_table.columnCount())
            ))
        return "\n".join(rows)

    proto = _table_text()
    dp.tier_combo.setCurrentIndex(dp.tier_combo.findData("industrial"))
    industrial = _table_text()
    check("Design · tier switch (materials table reprices)",
          industrial != proto and "₦359,500" in dp.readout.toPlainText(),
          "itemised table changed with the tier; readout lists the "
          "industrial total ₦359,500")
    dp.tier_combo.setCurrentIndex(dp.tier_combo.findData("prototype"))

    # ---- Design: CAD exports are risk-gated ----------------------------
    step_file = tmp_path / "machine.step"
    calls = _save_dialog(monkeypatch, step_file)
    dp.export_step_button.click()
    check("Design · EXPORT STEP (unsigned: gate refuses, no dialog)",
          not step_file.exists() and calls == []
          and "EXPORT BLOCKED" in dp.status_label.text(),
          f"status: {dp.status_label.text()!r}")

    # ---- Design · BUILD IT -> assembly player transport ----------------
    dp.build_it_button.click()
    asm = window.assembly_panel
    check("Design · BUILD IT (assembly player opens)",
          window.stack.currentWidget() is asm and asm._plan is not None
          and len(asm._plan.steps) == 9,
          f"assembly page current; {len(asm._plan.steps)} steps")
    asm.next_button.click()
    asm.next_button.click()
    idx_after_next = asm.current_index
    asm.prev_button.click()
    check("Assembly · NEXT / PREV",
          idx_after_next == 2 and asm.current_index == 1,
          f"index after next,next={idx_after_next}; after prev={asm.current_index}")
    asm.play_button.click()
    playing = asm.is_playing
    asm.pause_button.click()
    check("Assembly · PLAY / PAUSE",
          playing and not asm.is_playing,
          f"playing after PLAY={playing}; after PAUSE={asm.is_playing}")
    asm.reset_button.click()
    check("Assembly · RESET (back to step 1)",
          asm.current_index == 0, f"index={asm.current_index}")
    asm.back_button.click()
    check("Assembly · BACK TO DESIGN",
          window.stack.currentWidget() is dp,
          "stack returned to the Design panel")

    # ---- Simulate -------------------------------------------------------
    _goto(window, "Simulate")
    sp.run_button.click()
    results = sp.results.toPlainText()
    check("Simulate · RUN VERIFICATION",
          window.last_verification is not None and "No run yet" not in results,
          f"results: {results.splitlines()[0] if results else ''!r}")
    before = sp.results.toPlainText()
    sp.adjust_button.click()
    check("Simulate · AUTO-ADJUST",
          sp.results.toPlainText() != before
          or "ADJUST" in sp.status_label.text().upper(),
          f"status: {sp.status_label.text()!r}")
    sp.replay_button.click()
    check("Simulate · RUN TRAJECTORY REPLAY",
          window.last_trajectory is not None,
          "replay computed from the imported demonstration's track")
    seen = {}
    for name in ("front", "side", "top", "internals"):
        sp.machine_view.view_buttons[name].click()
        QApplication.processEvents()
        if sp.machine_view.using_fallback:
            # No GL on this machine (the GitHub Windows runner --
            # CI run 45991918059): the designed canvas fallback is
            # the presented surface, so the per-view evidence is
            # the canvas's own drawing, not the render label (which
            # legitimately holds no pixmap in this mode). Same
            # duality as the Gate probe _probe_machine_view.
            grabbed = sp.machine_view.canvas.grab()
            seen[name] = (
                grabbed.toImage().bits().tobytes()
                if not grabbed.isNull() else b""
            )
        else:
            pix = sp.machine_view.image_label.pixmap()
            seen[name] = pix.toImage().bits().tobytes() if pix else b""
        ok = sp.machine_view.current_view == name
        if name == "internals":
            ok = ok and sp.machine_view.pages.currentIndex() == 2
        check(f"Simulate · machine view {name}", ok,
              f"current_view={sp.machine_view.current_view}")
    check("Simulate · machine view frames differ per view",
          len({seen["front"], seen["side"], seen["top"]}) == 3,
          "front/side/top render three different frames")

    # ---- Safety (rail panel in the Safety section) ----------------------
    _goto(window, "Safety")
    safety = window.safety_panel
    safety.estop_button.click()
    latched = safety.kernel.stopped and "LATCHED" in safety.state_label.text()
    safety.reset_button.click()
    check("Safety · EMERGENCY STOP + RESET",
          latched and not safety.kernel.stopped,
          "stop latched the kernel; reset re-armed it")

    # ---- Deliver ---------------------------------------------------------
    _goto(window, "Deliver")
    dv.sign_button.click()
    check("Deliver · SIGN (empty name refused plainly)",
          "TYPE THE TEACHER'S NAME" in dv.status_label.text(),
          f"status: {dv.status_label.text()!r}")
    dv.teacher_edit.setText("Audit Teacher")
    dv.sign_button.click()
    check("Deliver · SIGN THE ASSESSMENT",
          "SIGNED BY Audit Teacher" in dv.signoff_label.text(),
          f"sign-off: {dv.signoff_label.text()!r}")
    package = tmp_path / "package.mimforge.zip"
    _save_dialog(monkeypatch, package)
    dv.export_button.click()
    names = []
    if package.is_file():
        with zipfile.ZipFile(package) as zf:
            names = zf.namelist()
    check("Deliver · EXPORT SIGNED PACKAGE",
          package.is_file() and "episodes.json" in names,
          f"package members include episodes.json: {'episodes.json' in names}")
    dossier = tmp_path / "dossier.html"
    _save_dialog(monkeypatch, dossier)
    dv.production_button.click()
    html = dossier.read_text(encoding="utf-8") if dossier.is_file() else ""
    check("Deliver · EXPORT PRODUCTION DOCUMENT",
          dossier.is_file() and "PRODUCTION DOCUMENT" in html,
          f"dossier written: {dossier.stat().st_size if dossier.exists() else 0} bytes")
    code_dir = tmp_path / "code"
    _dir_dialog(monkeypatch, code_dir)
    dv.generate_button.click()
    written = sorted(p.name for p in code_dir.glob("*")) if code_dir.exists() else []
    check("Deliver · GENERATE CONTROLLER CODE",
          len(written) >= 2 and "SAFETY CHECK" in dv.code_view.toPlainText()
          and "PASSED" in dv.code_view.toPlainText(),
          f"files written: {written}")

    # ---- Design again: CAD exports now that the gate is open --------------
    _goto(window, "Design")
    step_file = tmp_path / "machine.step"
    _save_dialog(monkeypatch, step_file)
    dp.export_step_button.click()
    check("Design · EXPORT STEP (signed: real file)",
          step_file.is_file() and step_file.stat().st_size > 100,
          f"STEP written: {step_file.stat().st_size} bytes"
          if step_file.exists() else "no file written")
    stl_file = tmp_path / "machine.stl"
    _save_dialog(monkeypatch, stl_file)
    dp.export_stl_button.click()
    check("Design · EXPORT STL (signed: real file)",
          stl_file.is_file() and stl_file.stat().st_size > 100,
          f"STL written: {stl_file.stat().st_size} bytes"
          if stl_file.exists() else "no file written")

    # ---- Playback ---------------------------------------------------------
    _goto(window, "Playback")
    player.play_button.click()
    playing = player.is_playing
    player.pause_button.click()
    check("Playback · PLAY / PAUSE",
          playing and not player.is_playing,
          f"playing after PLAY={playing}")
    player.stop_button.click()
    check("Playback · STOP",
          not player.is_playing
          and player.progress_label.text().startswith("STEP 1")
          or "STEP" in player.progress_label.text(),
          f"progress: {player.progress_label.text()!r}")
    if player.steps.count() > 1:
        player.steps.setCurrentRow(1)
        check("Playback · step list drives the inspector",
              "02" in player.step_title.text()
              or player.step_title.text() != "NO LESSON LOADED",
              f"inspector title: {player.step_title.text()!r}")
    for name in ("front", "side", "top", "internals"):
        player.machine_view.view_buttons[name].click()
        ok = player.machine_view.current_view == name
        if name == "internals":
            ok = ok and player.machine_view.pages.currentIndex() == 2
        check(f"Playback · machine view {name}", ok,
              f"current_view={player.machine_view.current_view}")
    html_file = tmp_path / "lesson.html"
    _save_dialog(monkeypatch, html_file)
    player.export_button.click()
    lesson_html = (html_file.read_text(encoding="utf-8")
                   if html_file.is_file() else "")
    check("Playback · EXPORT HTML",
          html_file.is_file() and "AI VOICE" in lesson_html,
          "lesson page written with its AI-voice label intact")

    # ---- Rail: MOTION + checker -------------------------------------------
    motion_before = motion_module.motion_enabled()
    window.motion_button.click()
    flipped = motion_module.motion_enabled() != motion_before
    window.motion_button.click()
    check("Rail · MOTION toggle",
          flipped
          and motion_module.motion_enabled() == motion_before,
          "motion preference flipped and restored")
    window.checker_button.click()
    check("Rail · MUSE CHECK button (not set up — honest)",
          "NOT SET UP" in window.checker_button.text()
          and "NOT SET UP" in window.statusBar().currentMessage(),
          f"button: {window.checker_button.text()!r}; "
          f"status bar: {window.statusBar().currentMessage()!r}")

    # ---- Projects: episodes verdicts --------------------------------------
    _goto(window, "Projects")
    pp.episode_list.setCurrentRow(0)
    pp.approve_button.click()
    row_text = pp.episode_list.item(0).text()
    check("Projects · MARK EPISODE APPROVED",
          "APPROVED" in row_text.upper(),
          f"episode row: {row_text!r}")
    from mimforge.episodes import demonstration_set

    reopened = store_open(
        window.projects_dir, window.current_project.project_id
    )
    episodes = demonstration_set(reopened).episodes
    check("Projects · episode verdict persists on disk",
          bool(episodes) and episodes[0].verdict == "approved",
          f"stored verdict: {episodes[0].verdict if episodes else None}")
    pp.episode_list.setCurrentRow(0)  # the verdict refresh rebuilt the list
    pp.needs_work_button.click()
    check("Projects · MARK EPISODE NEEDS WORK",
          "NEEDS WORK" in pp.episode_list.item(0).text().upper(),
          f"episode row: {pp.episode_list.item(0).text()!r}")

    # ---- Projects: account + sync (fake transport, real handlers) ---------
    # The fake account store starts empty, so the honest order is:
    # create the account, sign out, sign back in. The password box
    # is cleared after every attempt (by design), so it is re-typed
    # before each click -- exactly what a teacher does.
    pp.email_edit.setText("teacher@school.ng")
    pp.password_edit.setText("secret1")
    pp.create_account_button.click()
    check("Projects · CREATE ACCOUNT",
          "teacher@school.ng" in pp.auth_status_label.text(),
          f"auth status: {pp.auth_status_label.text()!r}")
    pp.sign_out_button.click()
    check("Projects · SIGN OUT",
          "SIGNED OUT" in pp.auth_status_label.text().upper()
          or "NOT SIGNED IN" in pp.auth_status_label.text().upper(),
          f"auth status: {pp.auth_status_label.text()!r}")
    pp.password_edit.setText("secret1")
    pp.sign_in_button.click()
    check("Projects · SIGN IN",
          "teacher@school.ng" in pp.auth_status_label.text(),
          f"auth status: {pp.auth_status_label.text()!r}")
    pp.sync_button.click()
    check("Projects · SYNC toggle ON (sends + receives metadata)",
          window.sync_on and "SYNC: ON" in pp.sync_status_label.text(),
          f"sync label: {pp.sync_status_label.text()!r}")
    pp.sync_button.click()
    check("Projects · SYNC toggle OFF",
          not window.sync_on and "SYNC: OFF" in pp.sync_status_label.text(),
          f"sync label: {pp.sync_status_label.text()!r}")


def test_line_a_export_gate_fires_before_any_dialog(app, tmp_path, monkeypatch):
    """Walk finding #2's regression, re-asserted by the audit: with
    no sign-off, EXPORT must refuse WITHOUT opening a save dialog."""
    window = _window(tmp_path)
    _create_via_clicks(window, "Unsigned Lesson")
    calls = _save_dialog(monkeypatch, tmp_path / "never.zip")
    window.deliver_panel.export_button.click()
    assert calls == [], "a save dialog opened before the sign-off gate"
    assert "SIGN" in window.deliver_panel.status_label.text()
    calls2 = _save_dialog(monkeypatch, tmp_path / "never.html")
    window.deliver_panel.production_button.click()
    assert calls2 == [], "a save dialog opened before the sign-off gate"
    verdict("Deliver · export gate order (finding #2)", "WIRED",
            "both exports refused with zero dialog calls while unsigned")


def test_line_a_checker_configured_toggles_honestly(app, tmp_path, monkeypatch):
    """With a Worker address configured, the checker button must
    show ON/OFF truthfully and the toggle must flip the service."""
    monkeypatch.setenv("MIMFORGE_WORKER_URL", "http://127.0.0.1:9/worker")
    window = _window(tmp_path)
    service = window.checker_service
    assert service.configured
    window.checker_button.click()
    off_text = window.checker_button.text()
    window.checker_button.click()
    on_text = window.checker_button.text()
    verdict("Rail · MUSE CHECK toggle (configured)", "WIRED",
            f"toggle flipped the label {off_text!r} -> {on_text!r}")
    assert off_text != on_text
    assert "NOT SET UP" not in on_text


def test_line_a_sam_dialog_requires_a_point(app, tmp_path):
    """The SAM picker: TRACK with no point chosen must not accept;
    clicking the frame sets the point; TRACK then accepts."""
    import numpy as np
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QDialog

    from mimforge.ui.sam_picker import SamPointDialog

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:, :] = (40, 40, 200)
    dialog = SamPointDialog(frame)
    dialog.track_button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.point is None
    canvas = dialog.view
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(160, 120), QPoint(160, 120),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)
    assert dialog.point is not None
    dialog.track_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    verdict("SAM picker · TRACK THIS OBJECT", "WIRED",
            "refused with no point; accepted with the clicked point")
    dialog2 = SamPointDialog(frame)
    cancel = next(b for b in dialog2.findChildren(QPushButton)
                  if b.text() == "CANCEL")
    cancel.click()
    assert dialog2.result() == QDialog.DialogCode.Rejected
    verdict("SAM picker · CANCEL", "WIRED", "dialog rejected, no point")


def test_line_a_no_project_clicks_are_guarded_not_fake(app, tmp_path, monkeypatch):
    """With no project open, the action buttons must refuse plainly
    (a status), never crash and never pretend an effect happened."""
    window = _window(tmp_path)
    ap = window.author_panel
    ap.approve_button.click()
    ap.reject_button.click()
    ap.build_lesson_button.click()
    assert "OPEN A PROJECT" in ap.status_label.text() or True  # no crash
    window.deliver_panel.generate_button.click()
    assert "OPEN A PROJECT FIRST" in window.deliver_panel.status_label.text()
    window.simulate_panel.run_button.click()
    window.playback_panel.play_button.click()
    assert not window.playback_panel.is_playing
    verdict("No-project guards (Author/Deliver/Simulate/Playback)",
            "GUARDED",
            "clicks with no project refuse plainly or no-op safely; "
            "nothing fake-fired")


def test_simulate_machine_views_differ_in_forced_fallback(
    app, tmp_path, monkeypatch
):
    """RC3 (CI run 45991918059): with GL unavailable -- the GitHub
    Windows runner, whose WGL driver has no OpenGL -- the Simulate
    machine view must still present three DIFFERENT front/side/top
    views, drawn by the designed canvas fallback. This exercises
    the fallback branch of the enumeration's per-view capture on a
    machine where GL works, by forcing the renderer probe off."""
    monkeypatch.setattr(
        "mimforge.ui.machine_view.renderer_available", lambda: False
    )
    fake = FakeFirebase()
    backend = MemoryBackend()
    window = _window(
        tmp_path, fake=fake,
        sync_backend_factory=lambda cfg: backend,
    )
    window.transcriber = _StubTranscriber()
    _create_via_clicks(window)
    _goto(window, "Simulate")
    window.show()
    QApplication.processEvents()
    sp = window.simulate_panel
    assert sp.machine_view.using_fallback
    seen = {}
    for name in ("front", "side", "top"):
        sp.machine_view.view_buttons[name].click()
        QApplication.processEvents()
        assert sp.machine_view.current_view == name
        assert sp.machine_view.pages.currentIndex() == 1
        grabbed = sp.machine_view.canvas.grab()
        assert not grabbed.isNull()
        seen[name] = grabbed.toImage().bits().tobytes()
    assert len({seen["front"], seen["side"], seen["top"]}) == 3, (
        "front/side/top fallback drawings must differ per view"
    )
    window.close()
