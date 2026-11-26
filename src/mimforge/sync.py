"""Metadata sync (plan Phase 1, step 1.3) — Firebase behind a flag.

Design (plan 1.4): Firebase Spark is used for Auth + Firestore
*metadata* only (accounts, project metadata, sharing index). No video,
CAD, package or large file ever goes through it — those stay local as
signed packages. Sync is an optional convenience behind a feature flag
and every core workflow works with the network off and sync disabled
(the offline gate, test T1.4).

The Firebase project exists (created 2026-11-25, free Spark plan);
the real backend is the stdlib Firestore REST client in
``firebase_sync``, plugged in at this module's backend seam by the
shell when sync is toggled on. This module stays the flag, the
offline gate, and the seam -- and the layer can never break local
work: every failure comes back as a SyncResult, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class SyncError(Exception):
    """Raised when an enabled sync backend fails."""


@dataclass
class SyncResult:
    """Outcome of one sync attempt. ``skipped`` means sync is off."""

    status: str  # synced | skipped | failed
    detail: str = ""


class SyncBackend(Protocol):
    """A metadata store (Firestore in production; a stub in tests)."""

    def push(self, collection: str, doc_id: str, payload: dict[str, Any]) -> None: ...
    def pull(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]: ...


@dataclass
class SyncConfig:
    """Feature flag + project identity. Disabled by default."""

    enabled: bool = False
    project_id: Optional[str] = None  # Firebase project id, when created
    backend: Optional[SyncBackend] = None


class MetadataSync:
    """Syncs project metadata only, when enabled. Never blocks local work."""

    def __init__(self, config: Optional[SyncConfig] = None) -> None:
        self.config = config or SyncConfig()

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.backend is not None)

    def push_metadata(
        self, collection: str, doc_id: str, payload: dict[str, Any]
    ) -> SyncResult:
        if not self.config.enabled:
            return SyncResult("skipped", "sync disabled by feature flag")
        if self.config.backend is None:
            return SyncResult(
                "failed", "sync enabled but no backend registered (no Firebase project yet)"
            )
        try:
            self.config.backend.push(collection, doc_id, payload)
        except Exception as exc:  # never crash the caller on a sync failure
            return SyncResult("failed", f"backend error: {exc}")
        return SyncResult("synced", f"{collection}/{doc_id} pushed")

    def pull_metadata(self, collection: str, doc_id: str) -> tuple[SyncResult, Optional[dict[str, Any]]]:
        if not self.config.enabled:
            return SyncResult("skipped", "sync disabled by feature flag"), None
        if self.config.backend is None:
            return (
                SyncResult("failed", "sync enabled but no backend registered"),
                None,
            )
        try:
            payload = self.config.backend.pull(collection, doc_id)
        except Exception as exc:
            return SyncResult("failed", f"backend error: {exc}"), None
        return SyncResult("synced", f"{collection}/{doc_id} pulled"), payload


class MemoryBackend:
    """In-memory backend for tests and offline demos. Not a Firebase client."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def push(self, collection: str, doc_id: str, payload: dict[str, Any]) -> None:
        self.store[f"{collection}/{doc_id}"] = dict(payload)

    def pull(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        found = self.store.get(f"{collection}/{doc_id}")
        return dict(found) if found is not None else None
