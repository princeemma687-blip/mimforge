"""Phase 1, test T1.1: create -> save -> reopen keeps identical hashes."""

import pytest

from mimforge.projects import (
    IntegrityError,
    create_project,
    list_projects,
    open_project,
)


def test_create_save_reopen_round_trip_keeps_identical_hash(tmp_path):
    project = create_project(tmp_path, "demo-project", "Demo Project")
    project.put_record("practical", "p1", {"title": "First practical", "subject": "Physics"})
    project.put_record("step", "s1", {"order": 1, "title": "Set up the apparatus"})
    digest = project.add_media("clip.bin", b"fake-video-bytes")
    assert digest
    hash_before = project.save()

    reopened = open_project(tmp_path, "demo-project")
    assert reopened.title == "Demo Project"
    assert reopened.get_record("practical", "p1")["title"] == "First practical"
    assert reopened.read_media("clip.bin") == b"fake-video-bytes"
    hash_after_reopen = reopened.save()
    assert hash_after_reopen == hash_before

    reopened_again = open_project(tmp_path, "demo-project")
    assert reopened_again.content_hash() == hash_before


def test_tampered_database_fails_open(tmp_path):
    project = create_project(tmp_path, "tamper-demo", "Tamper Demo")
    project.put_record("practical", "p1", {"title": "Original"})
    project.save()
    # Corrupt the stored record behind the app's back.
    db = tmp_path / "tamper-demo" / "project.db"
    raw = db.read_bytes().replace(b"Original", b"Modified")
    db.write_bytes(raw)
    with pytest.raises(IntegrityError):
        open_project(tmp_path, "tamper-demo")


def test_create_duplicate_and_list(tmp_path):
    create_project(tmp_path, "a-proj", "A")
    with pytest.raises(Exception):
        create_project(tmp_path, "a-proj", "A again")
    assert list_projects(tmp_path) == ["a-proj"]
