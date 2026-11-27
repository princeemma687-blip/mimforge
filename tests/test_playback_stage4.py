"""Stage 4 sample panel: the Playback re-skin (plan §9).

Covers only what this stage changed, on the Playback panel alone:
the vector icon set (``ui.icons``), the side-by-side layout and
its narrow-width collapse, the §4.2 type audit (mono on
measurements, grotesque on prose), the §4.3 motion behaviour of
this panel, and the inspector (readings / fitted graph / outcome).
The existing click-path tests in ``test_playback.py`` still own
the player behaviour; these tests own the re-skin.
"""

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mimforge.design import GantryParameters  # noqa: E402
from mimforge.models import VerificationRun  # noqa: E402
from mimforge.outcome import evaluate_derived, table_from_timings  # noqa: E402
from mimforge.playback import (  # noqa: E402
    LessonGraph,
    LessonReplay,
    LessonTable,
    build_lesson,
)
from mimforge.simulation import simulate_suspension  # noqa: E402
from mimforge.templates import load_template, load_template_data  # noqa: E402

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QBoxLayout,
    QHeaderView,
    QLabel,
)

from mimforge.ui.icons import (  # noqa: E402
    ICON_NAMES,
    icon_path,
    icon_pixmap,
    make_icon,
)
from mimforge.ui.main_window import MONO_FAMILY, PROSE_FAMILY  # noqa: E402
from mimforge.ui.motion import motion_enabled, set_motion_enabled  # noqa: E402
from mimforge.ui.playback import LessonPlayer, ReadingsGraphView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture(autouse=True)
def _restore_motion():
    set_motion_enabled(True)
    yield
    set_motion_enabled(True)


def _demo_lesson():
    """The full pipeline lesson from test_playback: table + fit +
    replay, so the inspector has real readings, graph and outcome."""
    template = load_template("pendulum")
    data = load_template_data("pendulum")
    spec = data["observation_spec"]
    columns = [
        {"key": c["key"], "label": c["label"], "unit": c.get("unit", "")}
        for c in spec["columns"]
    ]
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


def _drawn_pixels(pixmap) -> int:
    """Non-transparent pixels in a rendered icon pixmap."""
    image = pixmap.toImage()
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                count += 1
    return count


# ------------------------------------------------------------------ icons


def test_icon_paths_exist_for_all_transport_names():
    # The Stage 4 sample shipped the transport four; the full
    # pass extends the same set to every panel's actions.
    assert set(ICON_NAMES) == {
        "play", "pause", "stop", "export",
        "import", "file", "attach", "record", "check", "cross",
        "build", "sign", "gear", "back", "prev", "next", "reset", "doc",
    }
    for name in ICON_NAMES:
        path = icon_path(name)
        assert not path.isEmpty()
        assert path.elementCount() >= 2


def test_icon_path_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown icon"):
        icon_path("teleport")


def test_icons_render_at_16_32_64_without_error(app):
    for name in ICON_NAMES:
        for size in (16, 32, 64):
            pixmap = icon_pixmap(name, size)
            assert not pixmap.isNull()
            assert pixmap.width() == size
            assert pixmap.height() == size
            assert _drawn_pixels(pixmap) > 0


def test_icons_are_distinct_from_each_other(app):
    images = {n: icon_pixmap(n, 32).toImage() for n in ICON_NAMES}
    names = list(ICON_NAMES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert images[a] != images[b], f"{a} and {b} render identically"


def test_icon_stroke_scales_with_size(app):
    """Vector behaviour: doubling the size roughly quadruples the
    drawn area (the stroke scales with the icon, it is not a
    fixed-width raster stamp)."""
    small = _drawn_pixels(icon_pixmap("play", 32))
    large = _drawn_pixels(icon_pixmap("play", 64))
    ratio = large / max(small, 1)
    assert 3.0 < ratio < 5.0, f"drawn-pixel ratio {ratio:.2f} is not ~4x"


def test_icon_renders_in_the_requested_colour(app):
    pixmap = icon_pixmap("stop", 32, color="#FF0000")
    image = pixmap.toImage()
    reds = 0
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 0 and colour.red() > 200 \
                    and colour.green() < 80 and colour.blue() < 80:
                reds += 1
    assert reds > 0, "no pixel carries the requested colour"


def test_icon_too_small_is_refused():
    with pytest.raises(ValueError, match="too small"):
        icon_pixmap("play", 4)


def test_make_icon_returns_a_usable_icon(app):
    icon = make_icon("play", 24)
    assert not icon.isNull()
    # QIcon hands back the stored 24 px pixmap for a 24 px request.
    assert icon.pixmap(24, 24).width() == 24


# ----------------------------------------------------------------- layout


def _show_at(player, width, height):
    player.show()
    player.resize(width, height)
    player.resize(width, height)  # second pass: a narrow first pass
    # can clamp at the wide minimum width; the reflow follows the
    # live width either way.
    QApplication.processEvents()


def test_side_by_side_at_laptop_width(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    _show_at(player, 1200, 800)
    assert player.width() >= 900
    assert not player.is_narrow_layout
    assert player._main_row.direction() == QBoxLayout.LeftToRight
    # All three columns are present and visible.
    assert player.machine_view.isVisibleTo(player)
    assert player.steps.isVisibleTo(player)
    assert player.readings_table.isVisibleTo(player)
    assert player.graph_view.isVisibleTo(player)
    assert player.play_button.isVisibleTo(player)
    assert player.export_button.isVisibleTo(player)
    player.close()


def test_columns_stack_at_narrow_width(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    _show_at(player, 1200, 800)
    assert not player.is_narrow_layout
    _show_at(player, 600, 900)
    assert player.width() < 900
    assert player.is_narrow_layout
    assert player._main_row.direction() == QBoxLayout.TopToBottom
    # Nothing is lost in the collapse: every surface is still
    # present, visible and usable.
    assert player.machine_view.isVisibleTo(player)
    assert player.steps.count() == 9
    assert player.readings_table.isVisibleTo(player)
    assert player.graph_view.isVisibleTo(player)
    assert player.play_button.isEnabled()
    assert player.pause_button.isEnabled()
    assert player.stop_button.isEnabled()
    assert player.export_button.isEnabled()
    assert player.steps.isVisibleTo(player)
    # Stacked columns are taller than a short panel: the scroll
    # area must offer the rest instead of cutting it off.
    _show_at(player, 600, 500)
    assert player._scroll.verticalScrollBar().maximum() > 0
    player.close()


def test_step_titles_wrap_instead_of_clipping(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.steps.wordWrap() is True
    player.close()


def test_readings_table_sizes_columns_to_content(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    header = player.readings_table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeToContents
    player.close()


def test_machine_frame_fills_its_view(app, lesson):
    """The rendered frame tracks the view's size: after a resize
    settles, the picture is rendered at (or near) the label's size
    instead of sitting as a small stamp, and the label scales its
    pixmap to fill."""
    from PySide6.QtTest import QTest

    player = LessonPlayer()
    player.load_lesson(lesson)
    _show_at(player, 1200, 800)
    assert player.machine_view.image_label.hasScaledContents()
    QTest.qWait(100)  # let the deferred re-render run
    QApplication.processEvents()
    label = player.machine_view.image_label
    pixmap = label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    # The adaptive ladder may halve the resolution on a slow
    # machine, so the bar is "near the label size", not exact.
    assert pixmap.width() >= label.width() * 0.4
    assert pixmap.height() >= label.height() * 0.4
    player.close()


def test_layout_reflows_when_resized(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    _show_at(player, 1200, 800)
    assert not player.is_narrow_layout
    _show_at(player, 600, 900)
    assert player.is_narrow_layout
    _show_at(player, 1200, 800)
    assert not player.is_narrow_layout
    assert player._main_row.direction() == QBoxLayout.LeftToRight
    player.close()


# -------------------------------------------------------------- type audit


def _families(widget):
    return list(widget.font().families())


def test_mono_on_measurement_surfaces(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    mono_first = MONO_FAMILY.split(",")[0].strip().strip("'")
    for widget in (
        player.progress_label,
        player.status,
        player.outcome_label,
        player.readings_table,
        player.steps,
        player.voice_label,
    ):
        assert mono_first in _families(widget), (
            f"{widget} is not set in the mono face"
        )
    player.close()


def test_prose_on_prose_surfaces(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    prose_first = PROSE_FAMILY.split(",")[0].strip().strip("'")
    for widget in (
        player.step_title,
        player.narration,
        player.observation,
        player.check,
    ):
        assert prose_first in _families(widget), (
            f"{widget} is not set in the prose face"
        )
    # And the two faces are genuinely different faces.
    assert _families(player.narration) != _families(player.progress_label)
    player.close()


# ------------------------------------------------------------------ motion


def test_reduced_motion_draws_complete_at_once(app, lesson):
    set_motion_enabled(False)
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.graph_view.sweep_progress == pytest.approx(1.0)
    assert not player.graph_view.sweep_active
    assert player._draw_line.draw_progress == pytest.approx(1.0)
    assert not player._draw_line.draw_active
    # The panel is complete: readings, graph points, outcome all there.
    assert player.readings_table.rowCount() == 5
    assert player.graph_view.point_count == 5
    assert "9.821" in player.outcome_label.text()
    player.close()


def test_full_motion_sweeps_then_completes(app, lesson):
    set_motion_enabled(True)
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.graph_view.sweep_progress == pytest.approx(0.0)
    assert player.graph_view.sweep_active
    assert player._draw_line.draw_progress == pytest.approx(0.0)
    assert player._draw_line.draw_active
    for _ in range(13):
        player.graph_view._advance_sweep()
    assert player.graph_view.sweep_progress == pytest.approx(1.0)
    assert not player.graph_view.sweep_active
    for _ in range(7):
        player._draw_line._advance()
    assert player._draw_line.draw_progress == pytest.approx(1.0)
    assert not player._draw_line.draw_active
    player.close()


def test_motion_toggle_mid_sweep_completes_it(app, lesson):
    set_motion_enabled(True)
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.graph_view.sweep_active
    set_motion_enabled(False)
    player.graph_view._advance_sweep()
    assert player.graph_view.sweep_progress == pytest.approx(1.0)
    assert not player.graph_view.sweep_active
    player._draw_line._advance()
    assert player._draw_line.draw_progress == pytest.approx(1.0)
    assert not player._draw_line.draw_active
    player.close()


def test_reduced_motion_end_states_match(app, lesson):
    """The re-skinned panel reaches the same end states with
    motion forced off as with it on -- motion never gates
    behaviour."""
    set_motion_enabled(False)
    player = LessonPlayer()
    player.load_lesson(lesson)
    player.play()
    for _ in range(8):
        player.advance()
    player.advance()
    assert not player.is_playing
    assert "FINISHED" in player.status.text()
    assert player.replay_view.progress == pytest.approx(1.0)
    assert player.graph_view.sweep_progress == pytest.approx(1.0)
    player.play()  # restart from step 1
    assert player.current_index == 0
    assert player.is_playing
    player.close()


# --------------------------------------------------------------- inspector


def test_inspector_shows_readings_graph_outcome(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert player.readings_table.rowCount() == 5
    assert player.readings_table.columnCount() == 7
    # Column 0 is L (cm): the demo table carries no L_cm values, so
    # its cells are honestly empty; the populated columns read back.
    assert player.readings_table.horizontalHeaderItem(0).text() == "L (cm)"
    assert player.readings_table.item(0, 0).text() == ""
    assert player.readings_table.item(0, 1).text() == "0.9"
    assert player.readings_table.item(0, 4).text() == "38.1"
    assert player.graph_view.point_count == 5
    assert player.graph_view._graph.slope == pytest.approx(4.03, abs=0.05)
    assert "9.821" in player.outcome_label.text()
    assert "OUTCOME RESULT" in player.outcome_label.text()
    player.close()


def test_inspector_empty_states_for_minimal_lesson(app):
    template = load_template("pendulum")
    lesson = build_lesson(template)
    player = LessonPlayer()
    player.load_lesson(lesson)
    assert not player.readings_table.isVisibleTo(player)
    assert player.readings_empty.isVisibleTo(player)
    assert "NO READINGS" in player.readings_empty.text()
    assert player.graph_view.point_count == 0
    assert "NO OUTCOME RECORDED" in player.outcome_label.text()
    player.close()


def test_transport_buttons_use_vector_icons(app, lesson):
    player = LessonPlayer()
    player.load_lesson(lesson)
    expected = {
        "play_button": "PLAY",
        "pause_button": "PAUSE",
        "stop_button": "STOP",
        "export_button": "EXPORT HTML",
    }
    for attr, text in expected.items():
        button = getattr(player, attr)
        assert button.text() == text
        assert not button.icon().isNull()
        assert button.icon().pixmap(20, 20).width() == 20
    player.close()


def test_panel_chrome_has_no_demo_specific_terms(app):
    """The sample panel's own strings (headings, buttons, empty
    states) carry no demonstration-specific wording -- the
    anti-pendulum rule extends to the new UI strings. Step content
    is template data and is not the panel's own wording."""
    player = LessonPlayer()
    chrome = []
    for widget in player.findChildren(QLabel):
        chrome.append(widget.text())
    for widget in (
        player.play_button,
        player.pause_button,
        player.stop_button,
        player.export_button,
    ):
        chrome.append(widget.text())
    text = " ".join(chrome).lower()
    for term in ("pendulum", "bob", "gravity", "fiducial", "retort"):
        assert not re.search(r"(?<![a-z])" + term + r"(?![a-z])", text), (
            f"panel chrome leaks {term!r}"
        )
    assert "9.81" not in text
    player.close()


def test_graph_view_paints_without_a_lesson(app):
    """The inspector graph renders its empty state and its sweep
    state without ever needing a lesson loaded."""
    view = ReadingsGraphView()
    view.resize(300, 200)
    view.show()
    QApplication.processEvents()
    assert view.point_count == 0
    view.set_graph(None)
    assert view.sweep_progress == pytest.approx(1.0)
    view.close()
