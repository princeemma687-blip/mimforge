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


# ------------------------------------------- full spec audit (2026-11-26)


def test_media_file_edited_outside_the_app_is_detected(tmp_path):
    """The manifest seals media hashes; open_project must re-hash
    the files themselves -- editing one outside the app is
    tampering, exactly like editing a record."""
    project = create_project(tmp_path, "demo-project", "Demo")
    project.add_media("clip.bin", b"original-bytes")
    project.save()
    target = tmp_path / "demo-project" / "media" / "clip.bin"
    target.write_bytes(b"tampered-bytes!")
    with pytest.raises(IntegrityError):
        open_project(tmp_path, "demo-project")


def test_media_file_deleted_is_detected(tmp_path):
    project = create_project(tmp_path, "demo-project", "Demo")
    project.add_media("clip.bin", b"original-bytes")
    project.save()
    (tmp_path / "demo-project" / "media" / "clip.bin").unlink()
    with pytest.raises(IntegrityError):
        open_project(tmp_path, "demo-project")


def test_add_media_file_streams_and_seals(tmp_path):
    """The streaming copy a demonstration video takes: bytes land
    identical, the returned digest is the real SHA-256, and the
    sealed project reopens clean."""
    import hashlib

    source = tmp_path / "recording.bin"
    source.write_bytes(b"frame-data" * 300_000)
    project = create_project(tmp_path, "demo-project", "Demo")
    digest = project.add_media_file("recording.bin", source)
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    project.save()
    reopened = open_project(tmp_path, "demo-project")
    assert reopened.read_media("recording.bin") == source.read_bytes()


def test_damaged_database_is_a_plain_project_error(tmp_path):
    """A corrupt project.db must surface as ProjectError (which the
    shell turns into a plain refusal), never as a raw sqlite
    exception escaping through a click handler."""
    from mimforge.projects import ProjectError

    project = create_project(tmp_path, "demo-project", "Demo")
    project.put_record("note", "n1", {"text": "x"})
    project.save()
    (tmp_path / "demo-project" / "project.db").write_bytes(
        b"this is not a sqlite database at all"
    )
    with pytest.raises(ProjectError):
        open_project(tmp_path, "demo-project")


def test_missing_manifest_is_a_plain_project_error(tmp_path):
    from mimforge.projects import ProjectError

    project = create_project(tmp_path, "demo-project", "Demo")
    project.save()
    (tmp_path / "demo-project" / "manifest.json").unlink()
    with pytest.raises(ProjectError):
        open_project(tmp_path, "demo-project")


def test_title_edited_in_the_database_breaks_the_seal(tmp_path):
    """The seal covers the title too: editing it directly in
    SQLite (bypassing the app) is detected on open."""
    import sqlite3

    from mimforge.projects import ProjectError

    project = create_project(tmp_path, "demo-project", "Honest Title")
    project.save()
    db_path = tmp_path / "demo-project" / "project.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE meta SET value = 'Forged Title' WHERE key = 'title'"
        )
        conn.commit()
    with pytest.raises(IntegrityError):
        open_project(tmp_path, "demo-project")
    assert ProjectError  # IntegrityError is a ProjectError


def test_verify_answers_false_for_a_corrupt_manifest(tmp_path):
    project = create_project(tmp_path, "demo-project", "Demo")
    project.save()
    (tmp_path / "demo-project" / "manifest.json").write_text(
        "{ not json", encoding="utf-8"
    )
    assert project.verify() is False


def test_path_traversal_is_refused(tmp_path):
    from mimforge.projects import ProjectError

    with pytest.raises(ProjectError):
        create_project(tmp_path, "../outside", "Nope")
    assert not (tmp_path.parent / "outside").exists()
    project = create_project(tmp_path, "demo-project", "Demo")
    with pytest.raises(ProjectError):
        project.add_media("../escape.bin", b"x")
    with pytest.raises(ProjectError):
        project.read_media("../project.db")
    with pytest.raises(ProjectError):
        open_project(tmp_path, "../outside")
