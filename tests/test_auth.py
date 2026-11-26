"""Firebase Auth + authenticated sync (2026-11-26).

The client and the authenticated Firestore backend are exercised
against a fake transport that speaks the real wire shapes (Identity
Toolkit + Firestore REST), so URLs, headers, error mapping and the
per-user document layout are all proven without a network. One live
test at the end performs the real round trip when this machine has
the project settings; it skips cleanly when any precondition is
absent (no settings, no network, rules not yet deployed) -- whether
it ran live or skipped is recorded in the progress log for this run.
"""

from __future__ import annotations

import io
import json
import urllib.error
import uuid

import pytest

from mimforge.firebase_auth import AuthError, FirebaseAuthClient
from mimforge.firebase_sync import (
    FirebaseConfig,
    FirestoreRestBackend,
    build_metadata_sync,
)
from mimforge.sync import SyncError

CONFIG = FirebaseConfig(
    api_key="test-key", project_id="test-project", auth_domain="x"
)


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, message: str) -> urllib.error.HTTPError:
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://example.invalid", code, "error", {}, io.BytesIO(body)
    )


class FakeFirebase:
    """One fake transport for both Identity Toolkit and Firestore."""

    def __init__(self) -> None:
        self.accounts: dict[str, dict] = {}  # email -> record
        self.documents: dict[str, dict] = {}  # path -> fields payload
        self.requests: list = []
        self.refresh_should_fail = False
        self._counter = 0

    # ---------------------------------------------------------- routing

    def __call__(self, request):
        url = request.full_url
        self.requests.append(request)
        if "identitytoolkit.googleapis.com" in url:
            return self._identity(url, request)
        if "securetoken.googleapis.com" in url:
            return self._refresh(request)
        if "firestore.googleapis.com" in url:
            return self._firestore(url, request)
        raise AssertionError(f"unexpected URL: {url}")

    def _identity(self, url: str, request):
        body = json.loads(request.data.decode("utf-8"))
        if url.rsplit("/", 1)[-1].startswith("accounts:signUp"):
            email = body["email"]
            if email in self.accounts:
                raise _http_error(400, "EMAIL_EXISTS")
            if len(body["password"]) < 6:
                raise _http_error(
                    400,
                    "WEAK_PASSWORD : Password should be at least "
                    "6 characters",
                )
            self._counter += 1
            record = {
                "password": body["password"],
                "uid": f"uid-{self._counter}",
                "refresh": f"refresh-{self._counter}",
            }
            self.accounts[email] = record
            return FakeResponse(
                {
                    "idToken": f"token-{self._counter}",
                    "refreshToken": record["refresh"],
                    "expiresIn": "3600",
                    "localId": record["uid"],
                    "email": email,
                }
            )
        if "accounts:signInWithPassword" in url:
            email = body["email"]
            record = self.accounts.get(email)
            if record is None:
                raise _http_error(400, "EMAIL_NOT_FOUND")
            if record["password"] != body["password"]:
                raise _http_error(400, "INVALID_PASSWORD")
            return FakeResponse(
                {
                    "idToken": f"token-for-{record['uid']}",
                    "refreshToken": record["refresh"],
                    "expiresIn": "3600",
                    "localId": record["uid"],
                    "email": email,
                    "registered": True,
                }
            )
        if "accounts:delete" in url:
            token = body["idToken"]
            for email, record in list(self.accounts.items()):
                if token.endswith(record["uid"]):
                    del self.accounts[email]
            return FakeResponse({})
        raise AssertionError(f"unexpected identity URL: {url}")

    def _refresh(self, request):
        if self.refresh_should_fail:
            raise _http_error(400, "INVALID_REFRESH_TOKEN")
        self._counter += 1
        return FakeResponse(
            {
                "id_token": f"fresh-token-{self._counter}",
                "refresh_token": f"fresh-refresh-{self._counter}",
                "expires_in": "3600",
                "user_id": "uid-1",
            }
        )

    def _firestore(self, url: str, request):
        path = url.split("/documents/", 1)[1]
        method = request.get_method()
        if method == "PATCH":
            self.documents[path] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(self.documents[path])
        if method == "GET":
            if path not in self.documents:
                raise _http_error(404, "NOT_FOUND")
            return FakeResponse(self.documents[path])
        if method == "DELETE":
            self.documents.pop(path, None)
            return FakeResponse({})
        raise AssertionError(f"unexpected Firestore method: {method}")


def _client(tmp_path, fake: FakeFirebase, clock=None) -> FirebaseAuthClient:
    return FirebaseAuthClient(
        CONFIG,
        session_path=tmp_path / "auth-session.json",
        opener=fake,
        clock=clock or (lambda: 1_000.0),
    )


# ------------------------------------------------------------- client


def test_sign_up_signs_in_and_persists(tmp_path):
    fake = FakeFirebase()
    client = _client(tmp_path, fake)
    session = client.sign_up("teacher@school.ng", "secret1")
    assert session.email == "teacher@school.ng"
    assert session.uid == "uid-1"
    assert client.signed_in
    # A fresh client over the same store restores the session.
    restored = _client(tmp_path, fake)
    assert restored.session is None  # nothing until restore() is called
    assert restored.restore() is not None
    assert restored.session.email == "teacher@school.ng"
    # The repr never leaks a token value.
    assert "token" not in repr(session).lower().split("=", 1)[-1]


def test_sign_in_wrong_password_is_plain_words(tmp_path):
    fake = FakeFirebase()
    client = _client(tmp_path, fake)
    client.sign_up("teacher@school.ng", "secret1")
    client.sign_out()
    with pytest.raises(AuthError) as caught:
        client.sign_in("teacher@school.ng", "wrong-pass")
    assert caught.value.code == "INVALID_PASSWORD"
    message = str(caught.value)
    assert "INVALID_PASSWORD" not in message  # never the raw code
    assert "does not match" in message


def test_sign_in_unknown_email_and_duplicate_sign_up(tmp_path):
    fake = FakeFirebase()
    client = _client(tmp_path, fake)
    with pytest.raises(AuthError) as caught:
        client.sign_in("ghost@school.ng", "secret1")
    assert caught.value.code == "EMAIL_NOT_FOUND"
    client.sign_up("teacher@school.ng", "secret1")
    with pytest.raises(AuthError) as caught:
        client.sign_up("teacher@school.ng", "secret1")
    assert caught.value.code == "EMAIL_EXISTS"
    assert "already exists" in str(caught.value)


def test_weak_password_and_empty_fields_are_plain(tmp_path):
    fake = FakeFirebase()
    client = _client(tmp_path, fake)
    with pytest.raises(AuthError) as caught:
        client.sign_up("teacher@school.ng", "abc")
    assert caught.value.code == "WEAK_PASSWORD"
    with pytest.raises(AuthError):
        client.sign_in("", "secret1")
    with pytest.raises(AuthError):
        client.sign_in("teacher@school.ng", "")
    # The empty-field attempts never reached the wire.
    assert all(
        "signInWithPassword" not in r.full_url for r in fake.requests
    )


def test_refresh_replaces_the_expiring_token(tmp_path):
    now = [1_000.0]
    fake = FakeFirebase()
    client = _client(tmp_path, fake, clock=lambda: now[0])
    client.sign_up("teacher@school.ng", "secret1")
    first_token = client.session.id_token
    now[0] += 3_600.0  # the stored token has now expired
    active = client.active_session()
    assert active is not None
    assert active.id_token != first_token
    assert any(
        "securetoken.googleapis.com" in r.full_url for r in fake.requests
    )
    # The refreshed session is the persisted one.
    restored = _client(tmp_path, fake, clock=lambda: now[0])
    restored.restore()
    assert restored.session.id_token == active.id_token


def test_dead_refresh_token_ends_the_session(tmp_path):
    now = [1_000.0]
    fake = FakeFirebase()
    client = _client(tmp_path, fake, clock=lambda: now[0])
    client.sign_up("teacher@school.ng", "secret1")
    fake.refresh_should_fail = True
    now[0] += 3_600.0
    assert client.active_session() is None
    assert not client.signed_in
    assert not (tmp_path / "auth-session.json").exists()


def test_sign_out_clears_session_and_file(tmp_path):
    fake = FakeFirebase()
    client = _client(tmp_path, fake)
    client.sign_up("teacher@school.ng", "secret1")
    assert (tmp_path / "auth-session.json").exists()
    client.sign_out()
    assert not client.signed_in
    assert not (tmp_path / "auth-session.json").exists()


def test_network_failure_is_plain_words(tmp_path):
    def dead_opener(request):
        raise urllib.error.URLError("no route")

    client = FirebaseAuthClient(
        CONFIG, session_path=tmp_path / "s.json", opener=dead_opener
    )
    with pytest.raises(AuthError) as caught:
        client.sign_in("teacher@school.ng", "secret1")
    assert caught.value.code == "NETWORK"
    assert "could not be reached" in str(caught.value)


# ------------------------------------------------- authenticated sync


def _signed_in_client(tmp_path, fake: FakeFirebase) -> FirebaseAuthClient:
    client = _client(tmp_path, fake)
    client.sign_up("teacher@school.ng", "secret1")
    return client


def test_authenticated_backend_uses_the_users_own_subtree(tmp_path):
    fake = FakeFirebase()
    client = _signed_in_client(tmp_path, fake)
    backend = FirestoreRestBackend(
        CONFIG, opener=fake, auth_provider=client.active_session
    )
    backend.push("projects", "p1", {"title": "Demo", "count": 2})
    expected_path = "users/uid-1/sync/projects__p1"
    assert expected_path in fake.documents
    wire = [
        r
        for r in fake.requests
        if "firestore.googleapis.com" in r.full_url
    ]
    assert wire, "the push never reached the transport"
    assert wire[0].headers.get("Authorization", "").startswith("Bearer ")
    pulled = backend.pull("projects", "p1")
    assert pulled == {"title": "Demo", "count": 2}
    backend.delete("projects", "p1")
    assert backend.pull("projects", "p1") is None


def test_authenticated_backend_refuses_signed_out(tmp_path):
    fake = FakeFirebase()
    backend = FirestoreRestBackend(
        CONFIG, opener=fake, auth_provider=lambda: None
    )
    with pytest.raises(SyncError) as caught:
        backend.push("projects", "p1", {"title": "x"})
    assert "sign in" in str(caught.value)


def test_build_metadata_sync_with_auth_round_trips(tmp_path):
    fake = FakeFirebase()
    client = _signed_in_client(tmp_path, fake)
    # build_metadata_sync builds its own backend with the default
    # opener; swap the transport by rebuilding the backend here is
    # not possible, so exercise the same wiring directly:
    sync = build_metadata_sync(CONFIG, auth_provider=client.active_session)
    sync.config.backend._opener = fake  # test seam: same wire, fake net
    result = sync.push_metadata("projects", "p9", {"title": "Synced"})
    assert result.status == "synced"
    pull_result, payload = sync.pull_metadata("projects", "p9")
    assert pull_result.status == "synced"
    assert payload == {"title": "Synced"}


# ---------------------------------------------------------------- live


def test_live_auth_and_sync_round_trip():
    """The real service, when this machine is set up for it.

    Preconditions: the project settings exist locally, the network
    reaches Firebase, and the per-user Firestore rules are deployed
    (a parallel Console task owns the rules). Missing settings or
    network -> skip; a 403 from Firestore -> skip with the reason,
    because the live proof is then pending the rules deploy, not
    failed code. The throwaway account and document are deleted
    again before the test ends.
    """
    from mimforge.firebase_sync import load_firebase_config

    config = load_firebase_config()
    if config is None:
        pytest.skip("no Firebase settings on this machine")
    client = FirebaseAuthClient(config)  # no session file: memory only
    email = f"mimforge-livetest-{uuid.uuid4().hex[:10]}@example.org"
    password = f"Live-{uuid.uuid4().hex[:12]}"
    try:
        client.sign_up(email, password)
    except AuthError as exc:
        if exc.code == "NETWORK":
            pytest.skip("the sign-in service is unreachable from here")
        raise
    backend = FirestoreRestBackend(
        config, auth_provider=client.active_session
    )
    doc_id = f"livetest-{uuid.uuid4().hex[:8]}"
    try:
        try:
            backend.push(
                "projects", doc_id, {"title": "live round trip", "n": 1}
            )
        except SyncError as exc:
            if "403" in str(exc) or "refused" in str(exc):
                pytest.skip(
                    "Firestore refused the write (403) — the per-user "
                    "rules are not deployed yet; live proof pending "
                    "the rules deploy"
                )
            raise
        pulled = backend.pull("projects", doc_id)
        assert pulled == {"title": "live round trip", "n": 1}
        backend.delete("projects", doc_id)
        assert backend.pull("projects", doc_id) is None
    finally:
        try:
            client.delete_account()
        except AuthError:
            pass
