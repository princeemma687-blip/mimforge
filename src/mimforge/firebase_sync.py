"""Firebase configuration + Firestore REST backend for ``sync``.

The sync layer (``mimforge.sync``) ships a backend seam; this module
is the real backend that plugs into it. It reads the project's web
configuration through the Resource Layer -- the config bundled
inside the app at packaging time, or a developer's local
``.env.local`` file (the same values the Firebase Console shows
under Project settings -- configuration, not a password) -- and
talks to Firestore's REST API directly: no SDK, no extra
dependency, standard library only.

Honest limits, by design:

- The values are read from disk at toggle-on time and are never
  written to the repo, a log, or an error message. Error text carries
  the service's answer (status + its message), never the address or
  the key.
- Firestore in production mode answers unauthenticated REST calls
  with a refusal until a signed-in user exists. The backend reports
  that refusal plainly through ``MetadataSync`` -- it never pretends
  a send worked when the service said no.

Authenticated layout (the per-user rules pattern): when the backend
is given an auth provider (``firebase_auth``), every document lives
under the signed-in user's own subtree --

    users/{uid}/sync/{collection}__{doc_id}

-- one ``sync`` collection per user, one document per synced record,
the sync layer's collection folded into the document id. The rules
grant a user exactly that subtree and nothing else, so a signed-in
teacher can only ever reach their own metadata. Requests then carry
the user's ID token; without a provider the backend keeps the
original top-level layout and no credential.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .sync import MetadataSync, SyncConfig, SyncError

__all__ = [
    "FirebaseConfig",
    "FirestoreRestBackend",
    "build_metadata_sync",
    "find_env_file",
    "load_firebase_config",
    "parse_env_text",
]

ENV_FILE_NAME = ".env.local"
ENV_OVERRIDE = "MIMFORGE_ENV_FILE"

_FIELD_MAP = {
    "FIREBASE_API_KEY": "api_key",
    "FIREBASE_AUTH_DOMAIN": "auth_domain",
    "FIREBASE_PROJECT_ID": "project_id",
    "FIREBASE_STORAGE_BUCKET": "storage_bucket",
    "FIREBASE_MESSAGING_SENDER_ID": "messaging_sender_id",
    "FIREBASE_APP_ID": "app_id",
}


@dataclass
class FirebaseConfig:
    """The Firebase web configuration for one project."""

    api_key: str = ""
    auth_domain: str = ""
    project_id: str = ""
    storage_bucket: str = ""
    messaging_sender_id: str = ""
    app_id: str = ""

    @property
    def usable(self) -> bool:
        """A config can drive the REST backend only with a project
        id and an API key."""
        return bool(self.project_id and self.api_key)


def parse_env_text(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (``#`` comments and quotes tolerated)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def find_env_file() -> Optional[Path]:
    """Locate the local Firebase config file, or None.

    Search order: the ``MIMFORGE_ENV_FILE`` override (authoritative
    when set -- a missing file there means "not set up"), then
    ``.env.local`` beside the working directory, in the user's
    ``Mimforge`` folder, and at the repository root (development).
    """
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        path = Path(override)
        return path if path.is_file() else None
    candidates = [
        Path.cwd() / ENV_FILE_NAME,
        Path.home() / "Mimforge" / ENV_FILE_NAME,
        Path(__file__).resolve().parents[2] / ENV_FILE_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_bundled_config() -> Optional[FirebaseConfig]:
    """The Firebase web config bundled inside the app (Stage 0).

    The resource is generated at packaging time from the developer's
    ``.env.local`` (see ``setup/fetch_bundled_assets.py``) and is a
    JSON object keyed by the ``FirebaseConfig`` field names (the
    ``FIREBASE_*`` env names are also accepted). A web config is a
    public project identifier, not a secret -- the per-user
    Firestore rules are the security -- so it ships in the bundle
    and a clean install needs no files present."""
    from . import resources

    resource_path = resources.firebase_config_path()
    if resource_path is None:
        return None
    try:
        data = json.loads(resource_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    values: dict[str, str] = {}
    for env_key, field in _FIELD_MAP.items():
        raw = data.get(field, data.get(env_key, ""))
        values[field] = raw if isinstance(raw, str) else str(raw)
    config = FirebaseConfig(**values)
    return config if config.usable else None


def load_firebase_config(path: str | Path | None = None) -> Optional[FirebaseConfig]:
    """Load the config, or None when no usable config exists.

    Order (Stage 0, via the Resource Layer): an explicit ``path``
    wins; then the ``MIMFORGE_ENV_FILE`` developer override (kept
    authoritative -- a missing file there means "not set up");
    then the config BUNDLED inside the app; then a developer
    ``.env.local`` found by :func:`find_env_file`; otherwise None
    (the app reports NOT SET UP and works signed out)."""
    if path is None and os.environ.get(ENV_OVERRIDE):
        env_path = find_env_file()
        if env_path is None or not env_path.is_file():
            return None
        path = env_path
    if path is None:
        bundled = _load_bundled_config()
        if bundled is not None:
            return bundled
    env_path = Path(path) if path is not None else find_env_file()
    if env_path is None or not env_path.is_file():
        return None
    try:
        values = parse_env_text(env_path.read_text(encoding="utf-8"))
    except OSError:
        return None
    config = FirebaseConfig(
        **{
            field: values.get(env_key, "")
            for env_key, field in _FIELD_MAP.items()
        }
    )
    return config if config.usable else None


# ------------------------------------------------------- value encoding


def _to_firestore_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, dict):
        return {
            "mapValue": {
                "fields": {
                    str(k): _to_firestore_value(v) for k, v in value.items()
                }
            }
        }
    if isinstance(value, (list, tuple)):
        return {
            "arrayValue": {"values": [_to_firestore_value(v) for v in value]}
        }
    return {"stringValue": str(value)}


def _from_firestore_value(value: dict[str, Any]) -> Any:
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "stringValue" in value:
        return str(value["stringValue"])
    if "mapValue" in value:
        fields = value["mapValue"].get("fields", {})
        return {k: _from_firestore_value(v) for k, v in fields.items()}
    if "arrayValue" in value:
        return [
            _from_firestore_value(v)
            for v in value["arrayValue"].get("values", [])
        ]
    return None


# ------------------------------------------------------------- backend

# An opener takes a urllib Request and returns a response object with
# ``status`` and ``read()``; tests inject a fake so the wire format is
# exercised without a network.
Opener = Callable[[urllib.request.Request], Any]


def _default_opener(request: urllib.request.Request) -> Any:
    return urllib.request.urlopen(request, timeout=20)


class FirestoreRestBackend:
    """``SyncBackend`` over the Firestore REST API (metadata only).

    ``auth_provider``, when given, is called before every request
    and returns the current auth session (an object with ``uid``
    and ``id_token``) or None. It is the seam ``firebase_auth``
    plugs into: with it, requests are authenticated and documents
    live in the user's own subtree (see the module docstring);
    without it, the backend is the original unauthenticated one.
    """

    def __init__(
        self,
        config: FirebaseConfig,
        opener: Opener | None = None,
        auth_provider: Callable[[], Any] | None = None,
    ) -> None:
        if not config.usable:
            raise SyncError("the sync settings are incomplete")
        self._config = config
        self._opener = opener or _default_opener
        self._auth_provider = auth_provider

    # ------------------------------------------------------------ wire

    def _session(self):
        """The current auth session, when this backend has a
        provider. A provider failure is a sync failure, in plain
        words -- never a crash and never a silent downgrade to
        unauthenticated access."""
        if self._auth_provider is None:
            return None
        try:
            return self._auth_provider()
        except Exception as exc:
            raise SyncError(
                "the sign-in session could not be refreshed — "
                "sign in again"
            ) from exc

    def _document_url(self, collection: str, doc_id: str, session=None) -> str:
        base = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{self._config.project_id}/databases/(default)/documents/"
        )
        if session is not None:
            return f"{base}users/{session.uid}/sync/{collection}__{doc_id}"
        return f"{base}{collection}/{doc_id}"

    def _request(
        self, method: str, collection: str, doc_id: str, body: bytes | None
    ) -> tuple[int, dict[str, Any]]:
        session = self._session()
        if self._auth_provider is not None and session is None:
            raise SyncError("no signed-in user — sign in before syncing")
        request = urllib.request.Request(
            self._document_url(collection, doc_id, session),
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        request.add_header("X-Goog-Api-Key", self._config.api_key)
        if session is not None:
            request.add_header("Authorization", f"Bearer {session.id_token}")
        try:
            with self._opener(request) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            status = int(exc.code)
            if status == 404 and method in ("GET", "DELETE"):
                return 404, {}  # no such document — the caller decides
            payload = self._parse(raw)
            message = (
                payload.get("error", {}).get("message")
                or f"the sync service answered {status}"
            )
            raise SyncError(
                f"the sync service refused (status {status}): {message}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise SyncError(
                "the sync service could not be reached — "
                "check the network connection"
            ) from exc
        return status, self._parse(raw)

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # ------------------------------------------------------- SyncBackend

    def push(self, collection: str, doc_id: str, payload: dict[str, Any]) -> None:
        body = json.dumps(
            {
                "fields": {
                    str(k): _to_firestore_value(v)
                    for k, v in payload.items()
                }
            }
        ).encode("utf-8")
        self._request("PATCH", collection, doc_id, body)

    def pull(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        status, payload = self._request("GET", collection, doc_id, None)
        if status == 404:
            return None  # no such document yet — not a failure
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return None
        return {k: _from_firestore_value(v) for k, v in fields.items()}

    def delete(self, collection: str, doc_id: str) -> None:
        """Remove one document (housekeeping: test clean-up and a
        user clearing their synced copy). A missing document is
        already gone -- not a failure."""
        self._request("DELETE", collection, doc_id, None)


def build_metadata_sync(
    config: FirebaseConfig,
    auth_provider: Callable[[], Any] | None = None,
) -> MetadataSync:
    """A ``MetadataSync`` enabled against the REST backend. With an
    ``auth_provider`` the backend syncs as the signed-in user, into
    that user's own subtree."""
    return MetadataSync(
        SyncConfig(
            enabled=True,
            project_id=config.project_id,
            backend=FirestoreRestBackend(config, auth_provider=auth_provider),
        )
    )
