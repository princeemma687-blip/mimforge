"""The practicals library (Prince's no-single-practical-preview
rule, 2026-11-26): the library is a set of equals.

- The registry lists every bundled template; pendulum is one
  among several, not the face of the app.
- Loading a template REQUIRES an explicit name -- there is no
  default practical anywhere in the loader.
- The Projects picker opens on a neutral prompt; a project is
  created only from an explicit choice.
- The two static practicals verify through the engine's static
  shape: their worked tables recover their constants inside
  their own tolerance bands, a demonstration-measured table is
  judged identically, and a badly-off table FAILS -- the verdict
  is earned, not automatic.
- No new practical's specifics leak into core code (the
  anti-pendulum discipline, generalised).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mimforge.templates import (  # noqa: E402
    list_templates,
    load_template,
    load_template_data,
    template_from_data,
)
from mimforge.verification import run_verification  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "mimforge"
LIBRARY = {"pendulum", "hooke", "moments"}


# ------------------------------------------------------------- registry


def test_registry_lists_the_whole_library():
    names = {entry["name"] for entry in list_templates()}
    assert LIBRARY <= names
    for entry in list_templates():
        assert entry["title"] and entry["subject"]


def test_every_library_template_loads_as_a_template():
    for name in LIBRARY:
        template = load_template(name)
        data = load_template_data(name)
        assert template.id == data["template_id"]
        assert len(template.steps) >= 5
        assert template.practical.apparatus
        spec = data["observation_spec"]
        assert spec["rows"] and spec["tolerance"]["expected_value"]


def test_loader_has_no_default_practical():
    with pytest.raises(TypeError):
        load_template()  # noqa: the missing name IS the test
    with pytest.raises(TypeError):
        load_template_data()  # noqa: the missing name IS the test


# ------------------------------------------------- static verification


@pytest.mark.parametrize("name", ["hooke", "moments"])
def test_static_templates_verify_on_their_worked_tables(name):
    outcome = run_verification(load_template(name), load_template_data(name))
    assert outcome.passed
    assert outcome.engine == "static-fit"
    assert outcome.track_basis == "readings"
    assert outcome.replay is None
    recovered = float(outcome.teacher_fit["recovered_value"])
    gap = abs(recovered - outcome.expected_value) / outcome.expected_value
    assert gap * 100 <= outcome.band_percent


@pytest.mark.parametrize(
    "name,rows",
    [
        (
            "hooke",
            [
                {"mass_g": 100, "load_N": 0.981, "extension_cm": 4.0, "extension_m": 0.040},
                {"mass_g": 200, "load_N": 1.962, "extension_cm": 7.8, "extension_m": 0.078},
                {"mass_g": 300, "load_N": 2.943, "extension_cm": 11.9, "extension_m": 0.119},
                {"mass_g": 400, "load_N": 3.924, "extension_cm": 15.6, "extension_m": 0.156},
                {"mass_g": 500, "load_N": 4.905, "extension_cm": 19.8, "extension_m": 0.198},
            ],
        ),
        (
            "moments",
            [
                {"known_mass_g": 100, "a_cm": 12.0, "b_cm": 15.2},
                {"known_mass_g": 100, "a_cm": 16.0, "b_cm": 19.8},
                {"known_mass_g": 100, "a_cm": 20.0, "b_cm": 25.1},
                {"known_mass_g": 100, "a_cm": 24.0, "b_cm": 30.2},
                {"known_mass_g": 100, "a_cm": 28.0, "b_cm": 34.9},
            ],
        ),
    ],
)
def test_static_verification_judges_a_measured_table(name, rows):
    outcome = run_verification(
        load_template(name), load_template_data(name), measured_rows=rows
    )
    assert outcome.passed
    assert outcome.track_basis == "demonstration"


@pytest.mark.parametrize("name", ["hooke", "moments"])
def test_static_verification_fails_a_badly_off_table(name):
    data = load_template_data(name)
    spec = data["observation_spec"]
    y_key = spec["graph_spec"]["y_quantity"]
    bad = [dict(r) for r in spec["rows"]]
    for row in bad:
        row[y_key] = row[y_key] * 1.3
    outcome = run_verification(
        load_template(name), data, measured_rows=bad
    )
    assert not outcome.passed
    assert "outcome-vs-expected" in outcome.report.check_ids


# ------------------------------------------------------- anti-leak scan


def _word_leaks(term: str) -> list[str]:
    hits = []
    for path in SRC.rglob("*.py"):
        if "templates" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text):
            hits.append(path.name)
    return hits


@pytest.mark.parametrize("term", ["hooke", "spring"])
def test_new_practical_terms_do_not_leak_into_core(term):
    assert _word_leaks(term) == []


# ------------------------------------------------------ picker neutrality


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_picker_opens_neutral_and_creates_only_on_choice(app, tmp_path):
    from mimforge.ui.main_window import MainWindow

    window = MainWindow(projects_dir=tmp_path / "projects")
    panel = window.projects_panel
    # A fresh first run: no project, no practical pre-selected,
    # the whole library listed behind a neutral prompt.
    assert window.current_project is None
    assert panel.template_combo.currentData() is None
    assert panel.template_combo.count() >= 1 + len(LIBRARY)
    assert panel.title_edit.text() == ""
    panel.create_button.click()
    assert window.current_project is None
    assert "CHOOSE A PRACTICAL" in panel.status_label.text()
    # An explicit choice creates a project from THAT practical.
    index = panel.template_combo.findData("hooke")
    assert index > 0
    panel.template_combo.setCurrentIndex(index)
    assert "Hooke" in panel.title_edit.text()
    panel.create_button.click()
    assert window.current_project is not None
    record = window.current_project.get_record("template", "current")
    assert record["name"] == "hooke"
