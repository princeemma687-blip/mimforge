"""Phase 1, tests T1.3/T1.4: sync is flag-gated and offline work never breaks."""

from mimforge.projects import create_project, open_project
from mimforge.sync import MemoryBackend, MetadataSync, SyncConfig


def test_sync_disabled_by_default_and_never_blocks_local_work(tmp_path):
    sync = MetadataSync()  # default: disabled, no backend
    assert sync.enabled is False
    result = sync.push_metadata("projects", "p1", {"title": "Demo"})
    assert result.status == "skipped"
    pull_result, payload = sync.pull_metadata("projects", "p1")
    assert pull_result.status == "skipped"
    assert payload is None

    # Offline gate (T1.4): core workflows work with sync disabled.
    project = create_project(tmp_path, "offline-proj", "Offline")
    project.put_record("practical", "p1", {"title": "Works offline"})
    project.save()
    reopened = open_project(tmp_path, "offline-proj")
    assert reopened.get_record("practical", "p1")["title"] == "Works offline"


def test_sync_enabled_with_backend_round_trips_metadata():
    backend = MemoryBackend()
    sync = MetadataSync(SyncConfig(enabled=True, project_id="mimforge", backend=backend))
    assert sync.enabled is True
    result = sync.push_metadata("projects", "p1", {"title": "Synced", "owner": "teacher"})
    assert result.status == "synced"
    pull_result, payload = sync.pull_metadata("projects", "p1")
    assert pull_result.status == "synced"
    assert payload == {"title": "Synced", "owner": "teacher"}


def test_sync_enabled_without_backend_reports_failed_not_crash():
    sync = MetadataSync(SyncConfig(enabled=True, project_id="mimforge", backend=None))
    result = sync.push_metadata("projects", "p1", {"title": "x"})
    assert result.status == "failed"
    assert "no backend" in result.detail
