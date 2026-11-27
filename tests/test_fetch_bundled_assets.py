"""Packaging fetch: downloads retry transient network failures.

CI run 46023544376 died at the bundled-asset staging step when a
single unretried ``urlopen`` hit a connect timeout (WinError
10060) and the raw ``URLError`` killed the build before the test
suite ever ran. These tests pin the retry behaviour of
``setup/fetch_bundled_assets.py`` with a mocked transport -- no
network is touched, and the backoff seam is patched out so the
tests stay fast. The SHA-256 pins are NOT weakened: a download
that eventually succeeds is verified exactly as before, and wrong
bytes are still refused after retries.
"""

import hashlib
import http.client
import importlib.util
import io
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FETCH_PATH = ROOT / "setup" / "fetch_bundled_assets.py"


def _load_fetch_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_bundled_assets", FETCH_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fetch(monkeypatch):
    """The fetch module with its backoff seam recorded, not slept."""
    module = _load_fetch_module()
    sleeps: list[float] = []
    monkeypatch.setattr(module, "_sleep", sleeps.append)
    return module, sleeps


class FakeTransport:
    """``urlopen`` stand-in driven by a script: each entry is an
    exception instance (raised) or a response object (returned)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class TruncatedResponse:
    """Serves a partial body, then dies mid-read the way a dropped
    connection does (``copyfileobj`` reads in chunks)."""

    def __init__(self, partial: bytes):
        self._partial = partial
        self._served = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=-1):
        if not self._served:
            self._served = True
            return self._partial
        raise http.client.IncompleteRead(self._partial, 4096)


def test_retry_policy_shape(fetch):
    module, _sleeps = fetch
    assert module.DOWNLOAD_ATTEMPTS >= 4
    assert len(module.DOWNLOAD_BACKOFFS) == module.DOWNLOAD_ATTEMPTS - 1
    backoffs = module.DOWNLOAD_BACKOFFS
    assert all(later > earlier for earlier, later in zip(backoffs, backoffs[1:]))
    # Per-attempt timeout stays generous enough for the ~130 MB
    # largest asset on a slow runner.
    assert module.DOWNLOAD_TIMEOUT >= 300


def test_download_retries_transient_failures_then_succeeds(fetch, monkeypatch, tmp_path):
    module, sleeps = fetch
    payload = b"mimforge-asset-bytes" * 512
    transport = FakeTransport(
        [
            urllib.error.URLError(
                "urlopen error [WinError 10060] connection attempt failed"
            ),
            ConnectionResetError("connection reset by peer"),
            io.BytesIO(payload),
        ]
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", transport)
    dest = tmp_path / "asset.bin"
    module.download("https://example.invalid/asset.bin", dest)
    assert transport.calls == 3
    assert dest.read_bytes() == payload
    # The callers' verification step, exactly as the stage_*
    # functions run it on the finished file.
    assert module.sha256_of(dest) == hashlib.sha256(payload).hexdigest()
    assert sleeps == [module.DOWNLOAD_BACKOFFS[0], module.DOWNLOAD_BACKOFFS[1]]


def test_download_recovers_from_an_incomplete_read(fetch, monkeypatch, tmp_path):
    module, _sleeps = fetch
    payload = bytes(range(256)) * 64
    transport = FakeTransport(
        [
            TruncatedResponse(payload[:100]),
            io.BytesIO(payload),
        ]
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", transport)
    dest = tmp_path / "model.bin"
    module.download("https://example.invalid/model.bin", dest)
    assert transport.calls == 2
    # The fragment from attempt 1 was overwritten, not appended to.
    assert dest.read_bytes() == payload
    assert module.sha256_of(dest) == hashlib.sha256(payload).hexdigest()


def test_download_exhausts_attempts_and_raises_naming_the_asset(
    fetch, monkeypatch, tmp_path
):
    module, sleeps = fetch
    attempts = module.DOWNLOAD_ATTEMPTS
    transport = FakeTransport(
        [TruncatedResponse(b"partial fragment")]
        + [urllib.error.URLError("connected host failed to respond")] * (attempts - 1)
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", transport)
    dest = tmp_path / "ffmpeg-archive.zip"
    url = "https://example.invalid/ffmpeg-archive.zip"
    with pytest.raises(SystemExit) as excinfo:
        module.download(url, dest)
    message = str(excinfo.value)
    assert transport.calls == attempts
    assert "ffmpeg-archive.zip" in message
    assert url in message
    assert str(attempts) in message
    assert sleeps == list(module.DOWNLOAD_BACKOFFS)
    # The partial file from the truncated first attempt is gone, so
    # a later run re-downloads instead of tripping over it.
    assert not dest.exists()


def test_ffmpeg_hash_mismatch_still_refused_after_retries(
    fetch, monkeypatch, tmp_path
):
    """End-to-end through a real caller: the transport fails twice,
    then delivers the WRONG bytes -- the retries happen, and the
    pinned SHA-256 check still refuses the download."""
    module, _sleeps = fetch
    transport = FakeTransport(
        [
            urllib.error.URLError("temporary failure"),
            urllib.error.URLError("temporary failure"),
            io.BytesIO(b"this is not the pinned ffmpeg archive"),
        ]
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", transport)
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        module.stage_ffmpeg("win64", tmp_path)
    assert transport.calls == 3
