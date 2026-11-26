"""Firebase Authentication client (Identity Toolkit REST, stdlib only).

Sign-in exists for exactly one purpose: live metadata sync. The app
is fully usable signed out -- projects, authoring, verification,
delivery and playback never look at this module. This client is the
shell's side of the Email/Password provider the project enables in
the Firebase Console; it talks to the Identity Toolkit REST API
directly, the same no-SDK pattern as ``firebase_sync``.

Custody rules, by design:

- The session (refresh token + identity) persists in one JSON file
  in the app's data folder so a reopened app is still signed in.
  Token values are never written to a log, an error message, or the
  repo -- error text is plain words a teacher can act on, mapped
  from the service's codes at this boundary.
- The API key used here is the project's web configuration value
  (``firebase_sync`` loads it); it identifies the project, it is not
  a password and it never leaves the machine except to Firebase.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .firebase_sync import FirebaseConfig

__all__ = [
    "AuthError",
    "AuthSession",
    "FirebaseAuthClient",
    "plain_auth_error",
]

_IDENTITY_BASE = "https://identitytoolkit.googleapis.com/v1"
_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

# The service's machine codes -> words a person can act on. Anything
# unmapped falls back to a generic line; the raw code never reaches
# the screen (it is kept on the exception for tests and support).
_PLAIN_ERRORS = {
    "EMAIL_NOT_FOUND": (
        "No account was found for that email — check it, or create "
        "the account first."
    ),
    "INVALID_PASSWORD": (
        "That password does not match this account — check it and "
        "try again."
    ),
    "INVALID_LOGIN_CREDENTIALS": (
        "That email and password do not match any account — check "
        "them and try again."
    ),
    "EMAIL_EXISTS": (
        "An account with that email already exists — sign in instead."
    ),
    "WEAK_PASSWORD": (
        "That password is too weak — use at least 6 characters."
    ),
    "INVALID_EMAIL": "That email address does not look right.",
    "MISSING_EMAIL": "Type the email address first.",
    "MISSING_PASSWORD": "Type the password first.",
    "USER_DISABLED": "This account has been switched off.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": (
        "Too many tries in a row — wait a while, then try again."
    ),
    "OPERATION_NOT_ALLOWED": (
        "Email sign-in is not switched on for this project."
    ),
    "INVALID_REFRESH_TOKEN": (
        "The saved sign-in is no longer valid — sign in again."
    ),
    "TOKEN_EXPIRED": (
        "The saved sign-in is no longer valid — sign in again."
    ),
    "USER_NOT_FOUND": (
        "The saved sign-in is no longer valid — sign in again."
    ),
}

_NETWORK_ERROR = (
    "The sign-in service could not be reached — check the network "
    "connection."
)
_GENERIC_ERROR = "Sign-in failed — the service answered with an error."


def plain_auth_error(code: str) -> str:
    """The plain-words line for one service error code."""
    return _PLAIN_ERRORS.get(code, _GENERIC_ERROR)


class AuthError(Exception):
    """A sign-in failure, already in plain words.

    ``code`` carries the service's machine code (or a local one such
    as ``NOT_SIGNED_IN``) for tests and support; ``str(error)`` is
    always the plain line that is safe to show a teacher.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or plain_auth_error(code))


@dataclass
class AuthSession:
    """One signed-in identity. Tokens are credentials: the repr
    shows only who is signed in, never a token value."""

    email: str
    uid: str
    id_token: str
    refresh_token: str
    expires_at: float  # epoch seconds at which the ID token expires

    def __repr__(self) -> str:
        return f"AuthSession(email={self.email!r}, uid={self.uid!r})"

    def expiring(self, within_s: float = 60.0, now: float | None = None) -> bool:
        """True when the ID token is expired or about to be."""
        moment = time.time() if now is None else now
        return moment >= self.expires_at - within_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "uid": self.uid,
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["AuthSession"]:
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                email=str(data["email"]),
                uid=str(data["uid"]),
                id_token=str(data["id_token"]),
                refresh_token=str(data["refresh_token"]),
                expires_at=float(data["expires_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


# An opener takes a urllib Request and returns a response object with
# ``status`` and ``read()``; tests inject a fake so the wire format is
# exercised without a network (same seam as ``firebase_sync``).
Opener = Callable[[urllib.request.Request], Any]


def _default_opener(request: urllib.request.Request) -> Any:
    return urllib.request.urlopen(request, timeout=20)


class FirebaseAuthClient:
    """Email/password sign-in against one Firebase project."""

    def __init__(
        self,
        config: FirebaseConfig,
        session_path: str | Path | None = None,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not config.usable:
            raise AuthError(
                "NOT_SET_UP",
                "The sign-in settings are incomplete on this computer.",
            )
        self._config = config
        self._session_path = (
            Path(session_path) if session_path is not None else None
        )
        self._opener = opener or _default_opener
        self._clock = clock
        self._session: Optional[AuthSession] = None

    # ------------------------------------------------------------ state

    @property
    def session(self) -> Optional[AuthSession]:
        return self._session

    @property
    def signed_in(self) -> bool:
        return self._session is not None

    # ------------------------------------------------------------- wire

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._send(request)

    def _post_form(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self._opener(request) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read() if hasattr(exc, "read") else b""
            code = self._error_code(raw)
            raise AuthError(code) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise AuthError("NETWORK", _NETWORK_ERROR) from exc
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _error_code(raw: bytes) -> str:
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return "UNKNOWN"
        message = ""
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = str(error.get("message", ""))
        # Codes sometimes arrive as "CODE : human detail"; the code
        # is the part before the separator.
        code = message.split(" :")[0].strip().upper()
        return code or "UNKNOWN"

    # --------------------------------------------------------- accounts

    def _account_call(self, action: str, email: str, password: str) -> AuthSession:
        email = (email or "").strip()
        if not email:
            raise AuthError("MISSING_EMAIL")
        if not password:
            raise AuthError("MISSING_PASSWORD")
        payload = self._post_json(
            f"{_IDENTITY_BASE}/accounts:{action}?key={self._config.api_key}",
            {"email": email, "password": password, "returnSecureToken": True},
        )
        try:
            session = AuthSession(
                email=str(payload.get("email", email)),
                uid=str(payload["localId"]),
                id_token=str(payload["idToken"]),
                refresh_token=str(payload["refreshToken"]),
                expires_at=self._clock() + float(payload.get("expiresIn", 3600)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("UNKNOWN") from exc
        self._session = session
        self._persist()
        return session

    def sign_up(self, email: str, password: str) -> AuthSession:
        """Create the account and sign in with it."""
        return self._account_call("signUp", email, password)

    def sign_in(self, email: str, password: str) -> AuthSession:
        """Sign in to an existing account."""
        return self._account_call("signInWithPassword", email, password)

    def delete_account(self) -> None:
        """Delete the signed-in account at the service (used to
        clean up throwaway accounts; the local session is cleared
        either way)."""
        session = self._session
        if session is None:
            raise AuthError(
                "NOT_SIGNED_IN", "No account is signed in on this computer."
            )
        try:
            self._post_json(
                f"{_IDENTITY_BASE}/accounts:delete?key={self._config.api_key}",
                {"idToken": session.id_token},
            )
        finally:
            self.sign_out()

    # ---------------------------------------------------------- session

    def refresh(self) -> AuthSession:
        """Exchange the stored refresh token for a fresh ID token."""
        session = self._session
        if session is None:
            raise AuthError(
                "NOT_SIGNED_IN", "No account is signed in on this computer."
            )
        payload = self._post_form(
            f"{_TOKEN_URL}?key={self._config.api_key}",
            {
                "grant_type": "refresh_token",
                "refresh_token": session.refresh_token,
            },
        )
        try:
            refreshed = AuthSession(
                email=session.email,
                uid=str(payload.get("user_id", session.uid)),
                id_token=str(payload["id_token"]),
                refresh_token=str(
                    payload.get("refresh_token", session.refresh_token)
                ),
                expires_at=self._clock() + float(payload.get("expires_in", 3600)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("UNKNOWN") from exc
        self._session = refreshed
        self._persist()
        return refreshed

    def active_session(self) -> Optional[AuthSession]:
        """The current session with a usable ID token, refreshing
        when the stored one is expired or about to be. None when
        signed out. A failed refresh ends the local session: the
        saved sign-in is dead and the teacher must sign in again."""
        session = self._session
        if session is None:
            return None
        if not session.expiring(now=self._clock()):
            return session
        try:
            return self.refresh()
        except AuthError:
            self.sign_out()
            return None

    def sign_out(self) -> None:
        """Forget the session on this computer (the account itself
        is untouched)."""
        self._session = None
        if self._session_path is not None:
            try:
                self._session_path.unlink(missing_ok=True)
            except OSError:
                pass

    def restore(self) -> Optional[AuthSession]:
        """Reload the persisted session, if one exists and parses.
        A stale ID token is fine -- ``active_session`` refreshes it
        on first use; a dead refresh token ends the session there."""
        if self._session_path is None or not self._session_path.is_file():
            self._session = None
            return None
        try:
            data = json.loads(self._session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._session = None
            return None
        self._session = AuthSession.from_dict(data)
        return self._session

    def _persist(self) -> None:
        if self._session_path is None or self._session is None:
            return
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_path.write_text(
                json.dumps(self._session.to_dict(), indent=1),
                encoding="utf-8",
            )
        except OSError:
            # A session that cannot be saved still works until the
            # app closes; persistence must never break sign-in.
            pass
