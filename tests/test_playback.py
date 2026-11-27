"""Phase 6.1, lesson playback: a lesson package built from the real
template + real pipeline outputs plays start-to-finish offline --
in the app player and as a self-contained HTML export with no
external references."""

import json
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mimforge.design import GantryParameters  # noqa: E402
from mimforge.models import VerificationRun  # noqa: E402
from mimforge.outcome import evaluate_derived, table_from_timings  # noqa: E402
from mimforge.playback import (  # noqa: E402
    DEFAULT_STEP_SECONDS,
    LessonGraph,
    LessonPackage,
    LessonReplay,
    LessonStep,
    LessonTable,
    build_lesson,
    export_html_lesson,
)
from mimforge.simulation import simulate_suspension  # noqa: E402
from mimforge.templates import load_template, load_template_data  # noqa: E402

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.ui.playback import LessonPlayer  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


# ------------------------------------------------------- shared fixtures


def _demo_lesson() -> LessonPackage:
    """The first demonstration's lesson, built through the real
    pipeline: table + fit from the readings, replay from the MuJoCo
    (or RK4 fallback) simulation of the gantry."""
    template = load_template("pendulum")
    data = load_template_data("pendulum")
    spec = data["observation_spec"]
    columns = [
        {"key": c["key"], "label": c["label"], "unit": c.get("unit", "")}
        for c in spec["columns"]
    ]
    # Plan readings: mean times for 20 oscillations at L = 90..50 cm.
    rows = table_from_timings(
        [0.9, 0.8, 0.7, 0.6, 0.5],
        [(1.905, 1.905), (1.795, 1.795), (1.68, 1.68),
         (1.555, 1.555), (1.42, 1.42)],
        x_key="L_m", t1_key="t1_s", t2_key="t2_s", mean_key="mean_t_s",
        period_key="T_s", derived_key="T2_s2",
        oscillations=20, derived_fn=lambda period: period ** 2,
    )
    table = LessonTable(columns=columns, rows=rows)
    derived = evaluate_derived(
        rows, x_key="L_m", y_key="T2_s2", formula="4*pi^2 / slope"
    )
    graph = LessonGraph(
        x_label="L (m)",
        y_label="T^2 (s^2)",
        points=[(r["L_m"], r["T2_s2"]) for r in rows],
        slope=derived["slope"],
        intercept=derived["intercept"],
        notes="line of best fit",
    )
    sim = simulate_suspension(
        GantryParameters(), length_m=0.9, release_deg=8.0,
        world_constant=spec["tolerance"]["expected_value"],
    )
    replay = LessonReplay.from_points(
        sim.track_points(),
        label="simulated track, L = 0.90 m",
        sample_hz=200.0,
        x_label="x (m)", y_label="y (m)",
    )
    run = VerificationRun(
        id="demo-run-1",
        practical_id=template.practical.id,
        outcome_result=f"recovered {derived['recovered_value']:.3f}",
        discrepancy_metrics={
            "max_abs_residual_percent": derived["max_abs_residual_percent"]
        },
        passed=True,
    )
    return build_lesson(
        template, table=table, graph=graph, replay=replay,
        verification_run=run,
    )


@pytest.fixture(scope="module")
def lesson():
    return _demo_lesson()


# ------------------------------------------------------------------ build


def test_build_lesson_from_template_and_pipeline(lesson):
    assert lesson.step_count == 9
    assert lesson.title
    assert lesson.template_id == "waec-physics-simple-pendulum"
    assert lesson.steps[0].order == 1
    assert lesson.steps[-1].order == 9
    assert len(lesson.table.rows) == 5
    assert lesson.table.rows[0]["L_m"] == 0.9
    assert lesson.table.rows[0]["mean_t_s"] == 38.1
    assert lesson.graph.slope == pytest.approx(4.03, abs=0.05)
    assert 9.5 < float(
        lesson.outcome_summary["outcome_result"].split()[-1]
    ) < 10.1
    assert lesson.outcome_summary["verification_passed"] == "True"
    assert lesson.provenance["engine"] == "precomputed-replay"
    assert len(lesson.replay.points) == 600  # downsampled from thousands
    assert lesson.replay.points[0][0] < 0.01  # track starts at the release
    assert lesson.total_seconds == pytest.approx(
        9 * DEFAULT_STEP_SECONDS
    )


def test_lesson_json_round_trip(lesson):
    restored = LessonPackage.from_json(lesson.to_json())
    assert restored.title == lesson.title
    assert restored.step_count == lesson.step_count
    assert restored.steps[3].title == lesson.steps[3].title
    assert restored.table.rows == lesson.table.rows
    assert restored.graph.slope == lesson.graph.slope
    assert restored.replay.points == lesson.replay.points
    assert restored.outcome_summary == lesson.outcome_summary


def test_replay_downsample_keeps_endpoints():
    points = [(t * 0.01, t * 0.001, -t * 0.001) for t in range(2000)]
    replay = LessonReplay.from_points(
        points, label="test", sample_hz=100.0
    )
    assert len(replay.points) == 600
    assert replay.points[0] == points[0]
    assert replay.points[-1] == points[-1]


def test_validation_rejects_bad_packages():
    good_step = LessonStep(order=1, title="Set up")
    with pytest.raises(ValueError, match="at least one step"):
        LessonPackage(title="T", subject="S", template_id="x", steps=[]).validate()
    with pytest.raises(ValueError, match="unique, ascending"):
        LessonPackage(
            title="T", subject="S", template_id="x",
            steps=[good_step, LessonStep(order=1, title="Again")],
        ).validate()
    with pytest.raises(ValueError, match="time order"):
        LessonReplay(
            label="r", sample_hz=10.0,
            points=[(1.0, 0.0, 0.0), (0.5, 0.0, 0.0)],
        ).validate()
    with pytest.raises(ValueError, match="not in the spec"):
        LessonTable(
            columns=[{"key": "a", "label": "A"}],
            rows=[{"a": 1, "zzz": 2}],
        ).validate()
    with pytest.raises(ValueError, match="at least 2 plotted points"):
        LessonGraph(x_label="x", y_label="y", points=[(1.0, 2.0)],
                    slope=1.0, intercept=0.0).validate()


def test_minimal_lesson_without_table_graph_or_replay():
    template = load_template("pendulum")
    lesson = build_lesson(template)
    assert lesson.step_count == 9
    assert lesson.table is None and lesson.graph is None
    assert lesson.replay is None
    lesson.validate()


# ------------------------------------------------------------ HTML export


def test_html_export_is_self_contained_and_complete(lesson, tmp_path):
    path = export_html_lesson(lesson, tmp_path / "lesson.html")
    text = path.read_text(encoding="utf-8")
    # Every step, the table and the graph are in the file.
    for step in lesson.steps:
        assert step.title in text
    assert "38.1" in text  # a readings-table value
    assert "Fitted line" in text
    assert "<svg" in text
    assert 'id="replay"' in text
    # No external references of any kind.
    assert 'src="http' not in text
    assert "href=\"http" not in text
    assert "@import" not in text
    assert "url(http" not in text
    assert "fonts.googleapis" not in text
    # The embedded JSON payload parses and matches the package.
    match = re.search(
        r'<script type="application/json" id="lesson-data">(.*?)</script>',
        text, re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert len(payload["steps"]) == 9
    assert len(payload["replay"]["points"]) == 600
    assert payload["table"]["rows"][0]["L_m"] == 0.9


def test_html_export_minimal_lesson(tmp_path):
    lesson = build_lesson(load_template("pendulum"))
    path = export_html_lesson(lesson, tmp_path / "minimal.html")
    text = path.read_text(encoding="utf-8")
    assert "NO LESSON" not in text
    assert 'src="http' not in text


def test_html_export_escapes_hostile_template_text(tmp_path):
    """Tamper case: template text carrying markup must stay text --
    no live tags, no script breakout, payload intact as data."""
    evil = LessonPackage(
        title="T</title><script>alert(1)</script>",
        subject="S",
        template_id="x",
        steps=[
            LessonStep(
                order=1,
                title="A</script><img src=x onerror=alert(2)>",
                narration="n</script><script>alert(3)</script>",
            )
        ],
    )
    path = export_html_lesson(evil, tmp_path / "evil.html")
    text = path.read_text(encoding="utf-8")
    assert text.count("<script") == 2  # only the exporter's own two
    assert text.count("</script>") == 2
    assert "<img" not in text
    match = re.search(
        r'<script type="application/json" id="lesson-data">(.*?)</script>',
        text, re.DOTALL,
    )
    assert match is not None
    assert "<" not in match.group(1)  # payload carries no raw '<'
    payload = json.loads(match.group(1))
    assert payload["steps"][0]["title"].startswith("A</script>")


# -------------------------------------------------------------- Qt player


def test_player_plays_full_lesson_start_to_finish(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.steps.count() == 9
    assert player.current_index == 0
    assert "LOADED" in player.status.text()
    assert "STEP 01/09" in player.progress_label.text()

    player.play()
    assert player.is_playing
    for expected in range(1, 9):
        player.advance()
        assert player.current_index == expected
        assert player.is_playing
    player.advance()  # past the last step
    assert not player.is_playing
    assert "FINISHED" in player.status.text()
    assert player.replay_view.progress == pytest.approx(1.0)

    # Play again restarts from step 1.
    player.play()
    assert player.current_index == 0
    assert player.is_playing


def test_player_pause_holds_and_stop_resets(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    player.play()
    player.advance()
    assert player.current_index == 1
    player.pause()
    assert not player.is_playing
    assert player.current_index == 1
    assert "PAUSED" in player.status.text()
    player.advance()  # a paused player does not advance
    assert player.current_index == 1
    player.play()
    player.stop()
    assert not player.is_playing
    assert player.current_index == 0
    assert "STOPPED" in player.status.text()


def test_player_step_selection_and_no_lesson(app, lesson):
    player = LessonPlayer()
    player.play()  # no lesson loaded
    assert "NO LESSON LOADED" in player.status.text()
    player.load_lesson(lesson)
    player.steps.setCurrentRow(4)
    assert player.current_index == 4
    assert "05" in player.step_title.text()
    assert player.replay_view.progress == pytest.approx(5 / 9)


# ------------------------------------------- full spec audit (2026-11-26)


def test_lesson_load_validates_like_the_write_path():
    """A hand-edited lesson with duplicate step orders is refused
    on load: the invariants are not write-path-only."""
    package = _demo_lesson()
    data = package.to_dict()
    data["steps"][1]["order"] = data["steps"][0]["order"]
    with pytest.raises(ValueError):
        LessonPackage.from_dict(data)


def test_replay_from_points_rejects_a_silly_cap():
    with pytest.raises(ValueError):
        LessonReplay.from_points(
            [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)],
            label="x",
            sample_hz=30.0,
            max_points=1,
        )
