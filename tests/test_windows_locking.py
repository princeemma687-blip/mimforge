"""Windows file-lock regressions -- CI run 45991918059.

The first CI run of the final code failed its pytest gate with
4 failures whose roots are all Windows file semantics: Windows
refuses to delete a file that is still open (PermissionError
[WinError 32]); Linux permits it, so none of this was visible in
the Linux suite. Three root causes, each pinned here:

RC1 -- the project store's SQLite connections were only ever
closed by the garbage collector (``with sqlite3.connect(...)``
commits but never closes), so ``project.db`` could still be open
when a temp tree was deleted. The store now closes connections
deterministically and ``Project.close()`` is the explicit
lifecycle the probe/tests use in a ``finally``.

RC2 -- the narration players (lesson + assembly) held their WAV
files through QMediaPlayer while ``tempfile`` removed (or, at
interpreter exit, tried to remove) the audio folder. The players
now release the media -- stop, clear source, release output --
BEFORE the folder is removed, and the removal itself
(``mimforge.tempdirs``) retries briefly and can never raise.

The lock is simulated, not assumed: a guarded ``os.unlink`` that
applies Windows semantics (refuse to unlink a file this process
holds open, detected through /proc/self/fd), and an
always-failing unlink for the never-raises guarantee.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------- RC1


class _TrackedConnection:
    """Proxy recording whether close() was really called."""

    def __init__(self, real):
        self._real = real
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def close(self):
        self.closed = True
        return self._real.close()


def test_project_connections_are_closed_deterministically(
    tmp_path, monkeypatch
):
    """Every connection the store opens is closed by the operation
    itself -- never left to the garbage collector."""
    from mimforge import projects

    tracked: list[_TrackedConnection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = _TrackedConnection(real_connect(*args, **kwargs))
        tracked.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    project = projects.create_project(tmp_path, "probe", "Probe")
    project.put_record("demonstration", "episode-1", {"x": 1})
    project.save()
    reopened = projects.open_project(tmp_path, "probe")
    assert reopened.get_record("demonstration", "episode-1") == {"x": 1}
    assert tracked, "the store opened no connections at all"
    assert all(conn.closed for conn in tracked), (
        "a project.db connection was left open: "
        f"{[c.closed for c in tracked]}"
    )


def test_project_close_is_idempotent_and_save_refuses(tmp_path):
    from mimforge.projects import ProjectError, create_project

    project = create_project(tmp_path, "probe", "Probe")
    project.close()
    project.close()  # second close is a no-op, not an error
    with pytest.raises(ProjectError):
        project.save()


def _open_file_targets() -> set[str]:
    fd_dir = Path("/proc/self/fd")
    targets: set[str] = set()
    for fd in fd_dir.iterdir():
        try:
            targets.add(os.readlink(fd))
        except OSError:
            continue
    return targets


@pytest.mark.skipif(
    not Path("/proc/self/fd").is_dir(),
    reason="the lock simulation needs /proc/self/fd",
)
def test_episode_probe_survives_windows_lock_semantics(monkeypatch):
    """Run the Gate episode probe under simulated Windows rules:
    unlinking a project.db this process still holds open raises
    PermissionError [WinError 32]. The probe must still pass --
    it closes every store before its temp tree is deleted."""
    real_unlink = os.unlink

    def guarded_unlink(path, *args, **kwargs):
        target = os.fspath(path)
        if target.endswith("project.db") and target in _open_file_targets():
            raise PermissionError(
                32,
                "The process cannot access the file because it is "
                "being used by another process",
                target,
            )
        return real_unlink(path, *args, **kwargs)

    # The simulation itself must bite: a deliberately held-open
    # database refuses deletion until its connection closes.
    import tempfile

    from mimforge.projects import create_project

    with tempfile.TemporaryDirectory() as tmp:
        scratch = create_project(Path(tmp), "held", "Held")
        db_path = Path(tmp) / "held" / "project.db"
        scratch.close()
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("SELECT value FROM meta").fetchall()
            with pytest.raises(PermissionError):
                guarded_unlink(db_path)
        guarded_unlink(db_path)  # closed now: deletion succeeds
        assert not db_path.exists()

    monkeypatch.setattr(os, "unlink", guarded_unlink)
    from mimforge.selftest_flows import _probe_episodes

    results: list = []
    _probe_episodes(results)
    assert results, "the probe recorded nothing"
    name, ok, detail = results[0]
    assert name == "episode set round trip"
    assert ok, detail


# ---------------------------------------------------------------- RC2


def test_remove_tree_never_raises_when_unlink_always_fails(
    tmp_path, monkeypatch
):
    """The cleanup guarantee: even with every unlink refused (a
    permanently locked file), remove_tree degrades and returns --
    it never raises."""
    from mimforge.tempdirs import remove_tree

    target = tmp_path / "mimforge-voice-locked"
    target.mkdir()
    (target / "step-01.wav").write_bytes(b"RIFF")

    def always_fail(path, *args, **kwargs):
        raise PermissionError(
            32, "being used by another process", os.fspath(path)
        )

    monkeypatch.setattr(os, "unlink", always_fail)
    assert remove_tree(target, attempts=2, delay_s=0) is False


def test_remove_tree_removes_a_normal_tree(tmp_path):
    from mimforge.tempdirs import remove_tree

    target = tmp_path / "tree"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "a.wav").write_bytes(b"x")
    assert remove_tree(target) is True
    assert not target.exists()


class _FakeMedia:
    """A QMediaPlayer stand-in recording the release order."""

    def __init__(self, calls: list):
        self.calls = calls
        self._output = object()

    def stop(self):
        self.calls.append("stop")

    def setSource(self, url):  # noqa: N802 - Qt naming
        self.calls.append(("setSource-empty", url.isEmpty()))

    def setAudioOutput(self, output):  # noqa: N802 - Qt naming
        self.calls.append(("setAudioOutput", output))
        self._output = output

    def audioOutput(self):  # noqa: N802 - Qt naming
        return self._output

    def play(self):
        self.calls.append("play")


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6", reason="PySide6 not installed")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _exercise_release_order(player, tmp_path):
    """Shared RC2 assertion for both narration players: with a
    fake media backend holding the 'current' file, releasing the
    audio must stop the player, clear its source and release the
    output BEFORE the folder cleanup runs -- and the folder must
    actually be removed."""
    from mimforge.tempdirs import TempDir

    calls: list = []
    player._media = _FakeMedia(calls)
    audio_dir = TempDir(prefix="mimforge-lock-test-")
    wav = Path(audio_dir.name) / "step-01.wav"
    wav.write_bytes(b"RIFF")
    player._audio_dir = audio_dir
    player._audio_files = {0: wav}
    real_cleanup = audio_dir.cleanup

    def recording_cleanup():
        calls.append("cleanup")
        real_cleanup()

    audio_dir.cleanup = recording_cleanup
    player._release_audio()
    assert calls == [
        "stop",
        ("setSource-empty", True),
        ("setAudioOutput", None),
        "cleanup",
    ]
    assert player._audio_dir is None
    assert not Path(audio_dir.name).exists()


def test_lesson_player_releases_media_before_cleanup(app, tmp_path):
    from mimforge.ui.playback import LessonPlayer

    player = LessonPlayer()
    try:
        _exercise_release_order(player, tmp_path)
    finally:
        player.close()


def test_assembly_player_releases_media_before_cleanup(app, tmp_path):
    from mimforge.ui.assembly import AssemblyPlayer

    player = AssemblyPlayer()
    try:
        _exercise_release_order(player, tmp_path)
    finally:
        player.close()


def test_player_release_never_raises_with_locked_files(
    app, tmp_path, monkeypatch
):
    """Even if every file in the audio folder stays locked, the
    player's release path completes without raising (the folder
    degrades to temp litter, exactly as designed)."""
    from mimforge.tempdirs import TempDir
    from mimforge.ui.playback import LessonPlayer

    def always_fail(path, *args, **kwargs):
        raise PermissionError(
            32, "being used by another process", os.fspath(path)
        )

    monkeypatch.setattr(os, "unlink", always_fail)
    player = LessonPlayer()
    try:
        player._media = _FakeMedia([])
        audio_dir = TempDir(prefix="mimforge-lock-test-")
        (Path(audio_dir.name) / "step-09.wav").write_bytes(b"RIFF")
        player._audio_dir = audio_dir
        player._release_audio()  # must not raise
        assert player._audio_dir is None
    finally:
        player.close()
