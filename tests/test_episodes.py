"""Stage 5 (plan section 10): episode discipline + zero-setup
first-run, as amended by Prince's 2026-11-26 18:06 order.

5.1 -- demonstrations gain numbered episodes per project, with
per-episode quality flags (track coverage as measured, the recovered
period where the track supports one, the teacher's verdict) and a
project-level demonstration-set view in the Projects panel.
Episodes persist in project records, survive reopen, and travel in
the signed package as episodes.json.

5.2 -- first run stays NEUTRAL/GENERAL (no pre-loaded example, no
practical favoured): the library opens with no project and no
practical pre-selected (already proven by the library workstream),
and a guided first-run empty state in Projects shows the whole
loop in plain words and starts cleanly from any library template.

Generic only: no practical names, shapes or constants in core code
-- the anti-pendulum and generalised anti-leak scans cover this
file too.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from mimforge import signing  # noqa: E402
from mimforge.episodes import (  # noqa: E402
    DemonstrationSet,
    Episode,
    EpisodeError,
    demonstration_set,
    episode_record_id,
    new_episode,
)
from mimforge.narration import Transcript, TranscriptSegment  # noqa: E402
from mimforge.projects import (  # noqa: E402
    create_project,
    open_project as store_open,
)
from mimforge.ui.main_window import SECTIONS, MainWindow  # noqa: E402

VIDEOS = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, **kwargs) -> MainWindow:
    return MainWindow(projects_dir=tmp_path / "projects", **kwargs)


def _create_via_clicks(window: MainWindow, title: str = "Pendulum Class"):
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


def _open_dialog(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )


def _save_dialog(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )


class _StubTranscriber:
    """Prepared transcript: the wiring, not the speech model, is
    under test here (the real engine keeps its Phase 2 tests)."""

    def transcribe(self, audio_path):
        return Transcript(
            segments=[
                TranscriptSegment(
                    0.0,
                    4.0,
                    "Set up the stand, clamp the thread and measure "
                    "the length from the pivot to the centre.",
                ),
                TranscriptSegment(
                    4.0,
                    8.0,
                    "Displace it through a small angle and release "
                    "without a push, then time twenty oscillations.",
                ),
            ],
            language="en",
            engine="stub",
            model="stub",
        )


def _clip_with_audio(tmp_path) -> Path:
    """The reference clip with an audio track muxed in (silent
    tone): the import's success path needs a video whose audio can
    be extracted -- the reference clips are silent by design."""
    target = tmp_path / "demo_with_audio.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-i", str(VIDEOS / "demo_L090cm.mp4"),
            "-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest", "-c:v", "copy", "-c:a", "aac",
            str(target),
        ],
        check=True,
        timeout=120,
    )
    return target


def _import_episode(window, tmp_path, monkeypatch):
    """One successful demonstration import; returns the clip path."""
    window.transcriber = _StubTranscriber()
    clip = _clip_with_audio(tmp_path)
    _open_dialog(monkeypatch, clip)
    window.author_panel.import_button.click()
    assert "DEMONSTRATION IMPORTED" in (
        window.author_panel.import_status_label.text()
    )
    return clip


def _episode_lines(window):
    panel = window.projects_panel
    return [
        panel.episode_list.item(row).text()
        for row in range(panel.episode_list.count())
    ]


# ------------------------------------------------------------ engine: one episode


def test_episode_rejects_bad_numbers_and_flags():
    with pytest.raises(EpisodeError):
        Episode(number=0, demonstration_id="episode-0")
    with pytest.raises(EpisodeError):
        Episode(number=1.5, demonstration_id="episode-1")
    with pytest.raises(EpisodeError):
        Episode(number=True, demonstration_id="episode-1")
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="")
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="../escape")
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="episode-1", coverage=1.5)
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="episode-1", coverage=float("nan"))
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="episode-1", coverage="high")
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="episode-1", period_s=-1.0)
    with pytest.raises(EpisodeError):
        Episode(number=1, demonstration_id="episode-1", period_s=float("inf"))
    with pytest.raises(EpisodeError):
        Episode(
            number=1, demonstration_id="episode-1", verdict="brilliant"
        )


def test_episode_round_trip_preserves_flags_and_verdict():
    episode = Episode(
        number=2,
        demonstration_id=episode_record_id(2),
        source_name="clip.mp4",
        tracker="colour",
        coverage=0.944,
        period_s=1.902,
        video_sha256="a" * 64,
        verdict="approved",
        verdict_by="Mrs A. Teacher",
        imported_at="2026-11-27T06:00:00+00:00",
    )
    rebuilt = Episode.from_dict(episode.to_dict())
    assert rebuilt == episode
    assert rebuilt.coverage == 0.944
    assert rebuilt.period_s == 1.902
    assert rebuilt.verdict == "approved"


def test_episode_from_dict_refuses_malformed_records():
    with pytest.raises(EpisodeError):
        Episode.from_dict("not an object")
    with pytest.raises(EpisodeError):
        Episode.from_dict({"demonstration_id": "episode-1"})
    with pytest.raises(EpisodeError):
        Episode.from_dict(
            {"number": 1, "demonstration_id": "episode-1", "coverage": 2.0}
        )
    with pytest.raises(EpisodeError):
        Episode.from_dict(
            {
                "number": 1,
                "demonstration_id": "episode-1",
                "verdict": "maybe",
            }
        )


# ------------------------------------------------------------ engine: the set


def test_set_numbers_episodes_and_refuses_duplicates():
    episode_set = DemonstrationSet()
    assert episode_set.next_number() == 1
    first = new_episode(
        episode_set,
        source_name="one.mp4",
        tracker="colour",
        coverage=1.0,
        period_s=1.9,
    )
    episode_set.add(first)
    assert first.number == 1
    assert first.demonstration_id == "episode-1"
    assert first.verdict == "not-set"
    assert episode_set.next_number() == 2
    second = new_episode(
        episode_set,
        source_name="two.mp4",
        tracker="colour",
        coverage=0.5,
        period_s=None,
    )
    episode_set.add(second)
    assert second.number == 2
    with pytest.raises(EpisodeError):
        episode_set.add(
            Episode(number=2, demonstration_id="episode-2")
        )
    with pytest.raises(EpisodeError):
        DemonstrationSet(
            episodes=[
                Episode(number=1, demonstration_id="episode-1"),
                Episode(number=1, demonstration_id="episode-1"),
            ]
        )


def test_set_verdict_requires_known_episode_and_known_verdict():
    episode_set = DemonstrationSet(
        episodes=[Episode(number=1, demonstration_id="episode-1")]
    )
    episode = episode_set.set_verdict(1, "approved", by="Mrs A. Teacher")
    assert episode.verdict == "approved"
    assert episode.verdict_by == "Mrs A. Teacher"
    with pytest.raises(EpisodeError):
        episode_set.set_verdict(9, "approved")
    with pytest.raises(EpisodeError):
        episode_set.set_verdict(1, "brilliant")
    # A failed verdict leaves the stored one untouched.
    assert episode_set.get(1).verdict == "approved"


def test_set_from_dict_refuses_corrupt_records():
    good = DemonstrationSet(
        episodes=[
            Episode(
                number=1,
                demonstration_id="episode-1",
                coverage=0.9,
                verdict="approved",
            )
        ]
    ).to_dict()
    assert DemonstrationSet.from_dict(good).get(1).verdict == "approved"
    with pytest.raises(EpisodeError):
        DemonstrationSet.from_dict("not an object")
    with pytest.raises(EpisodeError):
        DemonstrationSet.from_dict({"version": 2, "episodes": []})
    with pytest.raises(EpisodeError):
        DemonstrationSet.from_dict({"version": 1, "episodes": {}})
    with pytest.raises(EpisodeError):
        DemonstrationSet.from_dict(
            {
                "version": 1,
                "episodes": [
                    {"number": 1, "demonstration_id": "episode-1"},
                    {"number": 1, "demonstration_id": "episode-1"},
                ],
            }
        )
    with pytest.raises(EpisodeError):
        DemonstrationSet.from_dict(
            {
                "version": 1,
                "episodes": [
                    {
                        "number": 1,
                        "demonstration_id": "episode-1",
                        "verdict": "maybe",
                    }
                ],
            }
        )


def test_set_round_trip_through_a_project_record(tmp_path):
    project = create_project(tmp_path / "projects", "demo", "Demo")
    episode_set = DemonstrationSet()
    episode_set.add(
        new_episode(
            episode_set,
            source_name="one.mp4",
            tracker="colour",
            coverage=0.944,
            period_s=1.902,
        )
    )
    episode_set.set_verdict(1, "needs-work", by="Mrs A. Teacher")
    project.put_record("episodes", "set", episode_set.to_dict())
    project.save()
    reopened = store_open(tmp_path / "projects", "demo")
    loaded = demonstration_set(reopened)
    assert loaded.next_number() == 2
    episode = loaded.get(1)
    assert episode.coverage == 0.944
    assert episode.period_s == 1.902
    assert episode.verdict == "needs-work"
    assert episode.verdict_by == "Mrs A. Teacher"


def test_missing_demonstrations_are_flagged_not_dropped(tmp_path):
    project = create_project(tmp_path / "projects", "demo", "Demo")
    episode_set = DemonstrationSet()
    episode_set.add(
        new_episode(
            episode_set,
            source_name="one.mp4",
            tracker="colour",
            coverage=0.9,
            period_s=None,
        )
    )
    episode_set.add(
        new_episode(
            episode_set,
            source_name="two.mp4",
            tracker="colour",
            coverage=0.8,
            period_s=None,
        )
    )
    project.put_record("episodes", "set", episode_set.to_dict())
    project.put_record("demonstration", "episode-1", {"source_name": "one.mp4"})
    project.put_record("demonstration", "episode-2", {"source_name": "two.mp4"})
    project.save()
    reopened = store_open(tmp_path / "projects", "demo")
    loaded = demonstration_set(reopened)
    assert loaded.missing_demonstrations(reopened.list_records("demonstration")) == []
    reopened.delete_record("demonstration", "episode-2")
    reopened.save()
    again = store_open(tmp_path / "projects", "demo")
    loaded = demonstration_set(again)
    assert loaded.missing_demonstrations(again.list_records("demonstration")) == [2]
    # The episode itself survives with its snapshot flags.
    assert loaded.get(2).coverage == 0.8


def test_legacy_demonstration_is_adopted_as_episode_1(tmp_path):
    project = create_project(tmp_path / "projects", "demo", "Demo")
    project.put_record(
        "demonstration",
        "current",
        {
            "source_name": "old-clip.mp4",
            "tracker": "colour",
            "sha256": "b" * 64,
            "track": {"coverage_measured": 0.97, "coverage": 1.0},
            "periodic": {"mean_period_s": 1.904},
        },
    )
    project.save()
    reopened = store_open(tmp_path / "projects", "demo")
    loaded = demonstration_set(reopened)
    assert loaded.next_number() == 2
    episode = loaded.get(1)
    assert episode.demonstration_id == "current"
    assert episode.source_name == "old-clip.mp4"
    assert episode.coverage == 0.97
    assert episode.period_s == 1.904
    assert episode.verdict == "not-set"


def test_legacy_without_period_is_adopted_with_no_period(tmp_path):
    project = create_project(tmp_path / "projects", "demo", "Demo")
    project.put_record(
        "demonstration",
        "current",
        {
            "source_name": "old-clip.mp4",
            "tracker": "colour",
            "track": {"coverage_measured": 0.5},
            "periodic": None,
        },
    )
    project.save()
    loaded = demonstration_set(store_open(tmp_path / "projects", "demo"))
    assert loaded.get(1).period_s is None
    assert loaded.get(1).coverage == 0.5


def test_empty_project_has_an_empty_set(tmp_path):
    project = create_project(tmp_path / "projects", "demo", "Demo")
    project.save()
    loaded = demonstration_set(store_open(tmp_path / "projects", "demo"))
    assert loaded.episodes == []
    assert loaded.next_number() == 1


# ------------------------------------------------------------ delivery payload


def test_package_files_carries_episodes_when_given(tmp_path):
    from mimforge import delivery
    from mimforge.design import GantryParameters
    from mimforge.risk import RiskAssessment

    episode_set = DemonstrationSet()
    episode_set.add(
        new_episode(
            episode_set,
            source_name="one.mp4",
            tracker="colour",
            coverage=0.944,
            period_s=1.902,
        )
    )
    files = delivery.package_files(
        project_id="demo",
        project_title="Demo",
        template_name="demo",
        template_data={},
        draft=None,
        lesson=None,
        assessment=RiskAssessment(
            practical_id="demo", platform_id="gantry"
        ),
        params=GantryParameters(),
        code=delivery.generate_checked_code({}, GantryParameters()),
        episodes=episode_set.to_dict(),
    )
    assert "episodes.json" in files
    import json

    payload = json.loads(files["episodes.json"])
    assert payload["episodes"][0]["number"] == 1
    assert payload["episodes"][0]["coverage"] == 0.944
    files_without = delivery.package_files(
        project_id="demo",
        project_title="Demo",
        template_name="demo",
        template_data={},
        draft=None,
        lesson=None,
        assessment=RiskAssessment(
            practical_id="demo", platform_id="gantry"
        ),
        params=GantryParameters(),
        code=delivery.generate_checked_code({}, GantryParameters()),
    )
    assert "episodes.json" not in files_without


# ------------------------------------------------------------ first run (5.2)


def test_first_run_shows_the_loop_and_favours_no_practical(app, tmp_path):
    window = _window(tmp_path)
    panel = window.projects_panel
    # A fresh first run: no project, no practical pre-selected,
    # the whole library listed behind a neutral prompt.
    assert window.current_project is None
    assert panel.template_combo.currentData() is None
    assert panel.first_run_guide.isVisibleTo(window)
    guide = panel.first_run_guide_text.text()
    for word in ("DEMONSTRATE", "DESIGN", "BUILD", "TEACH"):
        assert word in guide
    # The guide names no practical at all.
    lowered = guide.lower()
    for name in ("pendulum", "hooke", "moments"):
        assert name not in lowered
    # The demonstration set is empty on a fresh first run.
    assert panel.episode_list.count() == 0
    assert not panel.approve_button.isEnabled()
    assert not panel.needs_work_button.isEnabled()


def test_first_run_guide_hides_once_a_project_is_open(app, tmp_path):
    window = _window(tmp_path)
    panel = window.projects_panel
    assert panel.first_run_guide.isVisibleTo(window)
    _create_via_clicks(window)
    assert not panel.first_run_guide.isVisibleTo(window)
    assert panel.episode_list.count() == 0


def test_first_run_guide_shows_with_saved_projects_present(
    app, tmp_path
):
    first = _window(tmp_path)
    _create_via_clicks(first)
    first.close()
    # A later launch: projects exist, but still no project open --
    # the guided empty state shows again, over the saved list.
    second = _window(tmp_path)
    panel = second.projects_panel
    assert second.current_project is None
    assert panel.first_run_guide.isVisibleTo(second)
    assert panel.project_list.count() == 1
    assert panel.template_combo.currentData() is None


def test_start_from_library_focuses_the_template_picker(
    app, tmp_path
):
    window = _window(tmp_path)
    panel = window.projects_panel
    window.show()
    panel.start_button.click()
    QApplication.processEvents()
    assert panel.template_combo.hasFocus()
    assert "CHOOSE A PRACTICAL" in panel.status_label.text()


# ------------------------------------------------------------ episodes in the shell


def test_import_assigns_episode_1_and_shows_its_flags(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    _import_episode(window, tmp_path, monkeypatch)
    lines = _episode_lines(window)
    assert len(lines) == 1
    assert "EPISODE 1" in lines[0]
    assert "TRACKED" in lines[0]
    assert "PERIOD" in lines[0]
    assert "VERDICT: NOT SET" in lines[0]
    assert window.last_import_report["episode"] == 1
    # The episode survives reopen, with its measured flags.
    stored = store_open(window.projects_dir, project.project_id)
    loaded = demonstration_set(stored)
    episode = loaded.get(1)
    assert episode is not None
    assert episode.coverage is not None and episode.coverage > 0.9
    assert episode.period_s is not None
    assert 1.5 < episode.period_s < 2.2
    assert episode.video_sha256
    assert episode.verdict == "not-set"
    # The demonstration record lives under its episode id as well
    # as under "current" (the paths the older panels already read).
    assert stored.get_record("demonstration", "episode-1") is not None
    assert stored.get_record("demonstration", "current") is not None
    window.open_project(project.project_id)
    assert len(_episode_lines(window)) == 1
    assert "EPISODE 1" in _episode_lines(window)[0]


def test_second_import_assigns_episode_2_and_keeps_episode_1_media(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    first_clip = _import_episode(window, tmp_path, monkeypatch)
    _import_episode(window, tmp_path, monkeypatch)
    lines = _episode_lines(window)
    assert len(lines) == 2
    assert "EPISODE 1" in lines[0]
    assert "EPISODE 2" in lines[1]
    assert window.last_import_report["episode"] == 2
    stored = store_open(window.projects_dir, project.project_id)
    first = stored.get_record("demonstration", "episode-1")
    second = stored.get_record("demonstration", "episode-2")
    # Each episode's recording is its own sealed media file: the
    # second import must not overwrite the first episode's video.
    assert first["stored_media"] == "media/demonstration-episode-1.mp4"
    assert second["stored_media"] == "media/demonstration-episode-2.mp4"
    first_file = (
        window.projects_dir / project.project_id / "media"
        / "demonstration-episode-1.mp4"
    )
    assert first_file.is_file()
    assert first_file.stat().st_size == first_clip.stat().st_size
    assert stored.verify()


def test_teacher_verdict_buttons_persist_across_reopen(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    _import_episode(window, tmp_path, monkeypatch)
    panel = window.projects_panel
    panel.episode_list.setCurrentRow(0)
    assert panel.approve_button.isEnabled()
    panel.approve_button.click()
    assert "VERDICT: APPROVED" in _episode_lines(window)[0]
    window.open_project(project.project_id)
    assert "VERDICT: APPROVED" in _episode_lines(window)[0]
    panel.episode_list.setCurrentRow(0)
    panel.needs_work_button.click()
    assert "VERDICT: NEEDS WORK" in _episode_lines(window)[0]
    window.open_project(project.project_id)
    assert "VERDICT: NEEDS WORK" in _episode_lines(window)[0]


def test_episode_with_deleted_demonstration_is_shown_missing(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    _import_episode(window, tmp_path, monkeypatch)
    stored = store_open(window.projects_dir, project.project_id)
    assert stored.delete_record("demonstration", "episode-1")
    stored.save()
    # Reopen as a fresh launch would: a second window on the same
    # store reads the project as stored on disk.
    window.close()
    fresh = _window(tmp_path)
    fresh.open_project(project.project_id)
    lines = _episode_lines(fresh)
    assert len(lines) == 1
    assert "EPISODE 1" in lines[0]
    assert "DEMONSTRATION RECORD MISSING" in lines[0]
    # The episode's snapshot flags are still shown, not dropped.
    assert "TRACKED" in lines[0]


def test_corrupt_episode_set_is_a_plain_row_not_a_crash(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    stored = store_open(window.projects_dir, project.project_id)
    stored.put_record(
        "episodes", "set", {"version": 99, "episodes": []}
    )
    stored.save()
    # Reopen as a fresh launch would: a second window on the same
    # store reads the project as stored on disk.
    window.close()
    fresh = _window(tmp_path)
    reopened = fresh.open_project(project.project_id)
    assert reopened is not None
    assert fresh.current_project is not None
    lines = _episode_lines(fresh)
    assert len(lines) == 1
    assert "COULD NOT BE READ" in lines[0]


def test_import_with_corrupt_episode_set_falls_back_without_a_number(
    app, tmp_path, monkeypatch
):
    """A set record that cannot be read does not block the import:
    the recording is still saved (under the pre-episode media
    name), the draft is still built, and the status says plainly
    the recording has no episode number."""
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    stored = store_open(window.projects_dir, project.project_id)
    stored.put_record(
        "episodes", "set", {"version": 99, "episodes": []}
    )
    stored.save()
    window.close()
    fresh = _window(tmp_path)
    fresh.open_project(project.project_id)
    assert "COULD NOT BE READ" in _episode_lines(fresh)[0]
    _import_episode(fresh, tmp_path, monkeypatch)
    status = fresh.author_panel.import_status_label.text()
    assert "DEMONSTRATION IMPORTED" in status
    assert "NO EPISODE NUMBER" in status
    assert fresh.last_import_report["episode"] is None
    stored = store_open(fresh.projects_dir, project.project_id)
    demo = stored.get_record("demonstration", "current")
    assert demo is not None
    assert demo["stored_media"] == "media/demonstration.mp4"
    assert stored.get_record("demonstration", "episode-1") is None
    # The set is still unreadable afterwards -- nothing was
    # silently rebuilt over the corrupt record.
    assert "COULD NOT BE READ" in _episode_lines(fresh)[0]


def test_signed_package_carries_episodes_json(
    app, tmp_path, monkeypatch
):
    import json

    window = _window(tmp_path)
    project = _create_via_clicks(window)
    _import_episode(window, tmp_path, monkeypatch)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    panel.teacher_edit.setText("Mrs A. Teacher")
    panel.sign_button.click()
    assert "SIGNED BY Mrs A. Teacher" in panel.signoff_label.text()
    target = tmp_path / "pkg.tmachine"
    _save_dialog(monkeypatch, target)
    panel.export_button.click()
    assert "PACKAGE SAVED" in panel.status_label.text()
    public_pem = Path(str(target) + ".pubkey.pem").read_bytes()
    manifest = signing.verify_package(target, public_pem)
    assert "episodes.json" in manifest["files"]
    # The signed payload carries the episode set as stored.
    import zipfile

    with zipfile.ZipFile(target) as archive:
        payload = json.loads(archive.read("episodes.json"))
    assert payload["episodes"][0]["number"] == 1
    assert payload["episodes"][0]["verdict"] == "not-set"
    assert payload["episodes"][0]["coverage"] > 0.9


# ------------------------------------------------------------ Gate v2 probe


def test_gate_probe_episode_round_trip():
    from mimforge.selftest_flows import _probe_episodes

    results: list = []
    _probe_episodes(results)
    assert results, "the probe recorded nothing"
    name, ok, detail = results[0]
    assert name == "episode set round trip"
    assert ok, detail
