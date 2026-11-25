"""Project storage for Mimforge (plan Phase 1, step 1.1).

A project is a folder holding one SQLite database plus a manifest.
The database is the source of truth for structured records (practicals,
demonstrations, steps, designs, runs); the manifest records a SHA-256
hash of the project's canonical logical content and of every media file
so a save -> reopen -> save round trip is verifiable (test T1.1).

Everything here is generic: records are stored as JSON payloads keyed by
``kind`` and ``id``. Nothing in this module knows about any particular
practical, subject or syllabus.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

MANIFEST_NAME = "manifest.json"
DB_NAME = "project.db"


class ProjectError(Exception):
    """Base error for project storage failures."""


class IntegrityError(ProjectError):
    """Raised when a stored project fails its manifest hash check."""


def _canonical_json(payload: Any) -> bytes:
    """Deterministic serialisation: sorted keys, no whitespace variance."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Project:
    """An open project: its folder, its records, its media hashes."""

    root: Path
    project_id: str
    title: str
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    media: dict[str, str] = field(default_factory=dict)  # rel path -> sha256

    # -- records ---------------------------------------------------------
    def put_record(self, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        self.records.setdefault(kind, {})[record_id] = payload

    def get_record(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        return self.records.get(kind, {}).get(record_id)

    def list_records(self, kind: str) -> dict[str, dict[str, Any]]:
        return dict(self.records.get(kind, {}))

    def delete_record(self, kind: str, record_id: str) -> bool:
        bucket = self.records.get(kind, {})
        if record_id in bucket:
            del bucket[record_id]
            return True
        return False

    # -- media -----------------------------------------------------------
    def add_media(self, rel_path: str, data: bytes) -> str:
        """Store a media blob under the project folder; return its hash."""
        target = self.root / "media" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = _sha256(data)
        self.media[f"media/{rel_path}"] = digest
        return digest

    def read_media(self, rel_path: str) -> bytes:
        return (self.root / "media" / rel_path).read_bytes()

    # -- persistence -----------------------------------------------------
    def content_hash(self) -> str:
        """Hash of the canonical logical content (records + media hashes)."""
        return _sha256(_canonical_json({"records": self.records, "media": self.media}))

    def save(self) -> str:
        """Write the database and manifest; return the content hash."""
        digest = self.content_hash()
        db_path = self.root / DB_NAME
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(kind TEXT, id TEXT, payload TEXT, PRIMARY KEY (kind, id))"
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("project_id", self.project_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("title", self.title),
            )
            conn.execute("DELETE FROM records")
            for kind, bucket in self.records.items():
                for record_id, payload in bucket.items():
                    conn.execute(
                        "INSERT INTO records (kind, id, payload) VALUES (?, ?, ?)",
                        (kind, record_id, json.dumps(payload, sort_keys=True)),
                    )
            conn.commit()
        manifest = {
            "project_id": self.project_id,
            "title": self.title,
            "content_hash": digest,
            "media": dict(sorted(self.media.items())),
            "format_version": 1,
        }
        (self.root / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return digest

    def verify(self) -> bool:
        """True when the stored manifest hash matches the live content."""
        manifest_path = self.root / MANIFEST_NAME
        if not manifest_path.exists():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("content_hash") == self.content_hash()


def create_project(base_dir: str | Path, project_id: str, title: str) -> Project:
    """Create a fresh project folder. Fails if the id already exists."""
    root = Path(base_dir) / project_id
    if root.exists():
        raise ProjectError(f"project already exists: {project_id}")
    root.mkdir(parents=True)
    (root / "media").mkdir()
    (root / "packages").mkdir()
    project = Project(root=root, project_id=project_id, title=title)
    project.save()
    return project


def open_project(base_dir: str | Path, project_id: str) -> Project:
    """Open an existing project, verifying its manifest hash first."""
    root = Path(base_dir) / project_id
    if not root.is_dir():
        raise ProjectError(f"no such project: {project_id}")
    db_path = root / DB_NAME
    if not db_path.exists():
        raise ProjectError(f"project has no database: {project_id}")
    records: dict[str, dict[str, Any]] = {}
    title = ""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        for key, value in conn.execute("SELECT key, value FROM meta"):
            if key == "title":
                title = value
        for kind, record_id, payload in conn.execute(
            "SELECT kind, id, payload FROM records"
        ):
            records.setdefault(kind, {})[record_id] = json.loads(payload)
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    project = Project(
        root=root,
        project_id=project_id,
        title=title,
        records=records,
        media=dict(manifest.get("media", {})),
    )
    if not project.verify():
        raise IntegrityError(
            f"manifest hash mismatch for project {project_id}: stored content "
            "does not match the database — the project may be damaged or "
            "have been edited outside the app"
        )
    return project


def list_projects(base_dir: str | Path) -> list[str]:
    """Ids of projects present in a base directory."""
    base = Path(base_dir)
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and (p / DB_NAME).exists() and (p / MANIFEST_NAME).exists()
    )
