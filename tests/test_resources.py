"""Resource Layer tests (Stage 0, 2026-11-26).

The resolver is the structural fix for walk findings #5/#6: every
runtime asset (ffmpeg/ffprobe, SAM weights, Whisper model,
Firebase config) resolves in ONE order -- bundled -> per-user ->
developer override -- and these tests pin that order with fake
directory trees, independent of whatever happens to be staged in
the developer's real ``bundled/`` folder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mimforge import resources
from mimforge.firebase_sync import load_firebase_config


def _fake_bundled(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "bundled"
    root.mkdir()
    monkeypatch.setenv("MIMFORGE_BUNDLED_DIR", str(root))
    monkeypatch.setenv("MIMFORGE_HOME", str(tmp_path / "userhome"))
    return root


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ------------------------------------------------------------- binaries


def test_binary_resolution_order_bundled_user_override_path(
    tmp_path, monkeypatch
):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    # Nothing anywhere -> None (never an exception).
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    assert resources.ffmpeg_path() is None
    # PATH (dev) is the last resort.
    path_dir = tmp_path / "pathbin"
    on_path = _touch(path_dir / exe)
    if os.name != "nt":
        on_path.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_dir))
    assert resources.ffmpeg_path() == on_path
    # Explicit dev override beats PATH.
    override = _touch(tmp_path / "override" / exe)
    monkeypatch.setenv("MIMFORGE_FFMPEG", str(override))
    assert resources.ffmpeg_path() == override
    monkeypatch.delenv("MIMFORGE_FFMPEG")
    # Per-user copy beats PATH.
    user_copy = _touch(tmp_path / "userhome" / "bin" / exe)
    assert resources.ffmpeg_path() == user_copy
    # Bundled beats everything.
    bundled_copy = _touch(bundled / "bin" / exe)
    assert resources.ffmpeg_path() == bundled_copy
    assert resources.describe_resolution()["ffmpeg"]["source"] == "bundled"


def test_ffprobe_resolves_independently(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    probe = _touch(bundled / "bin" / exe)
    assert resources.ffprobe_path() == probe


# --------------------------------------------------------------- models


def test_sam_weights_dir_prefers_bundled(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    monkeypatch.delenv("MIMFORGE_SAM_DIR", raising=False)
    assert resources.sam_weights_dir() is None
    user_dir = tmp_path / "userhome" / "models" / resources.SAM_FOLDER
    user_dir.mkdir(parents=True)
    assert resources.sam_weights_dir() == user_dir
    bundled_dir = bundled / "models" / resources.SAM_FOLDER
    bundled_dir.mkdir(parents=True)
    assert resources.sam_weights_dir() == bundled_dir


def test_whisper_model_dir_requires_model_bin(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    folder = bundled / "models" / "faster-whisper-base"
    folder.mkdir(parents=True)
    assert resources.whisper_model_dir("base") is None
    _touch(folder / "model.bin")
    assert resources.whisper_model_dir("base") == folder
    assert resources.whisper_model_dir("small") is None


# --------------------------------------------------------------- config


def _bundled_config(bundled: Path, project_id: str = "bundled-proj") -> Path:
    return _touch(
        bundled / "config" / "firebase_config.json",
        json.dumps(
            {
                "api_key": "test-key",
                "auth_domain": "x.example",
                "project_id": project_id,
                "storage_bucket": "",
                "messaging_sender_id": "",
                "app_id": "1:0:web:0",
            }
        ).encode(),
    )


def test_bundled_firebase_config_loads(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    monkeypatch.delenv("MIMFORGE_ENV_FILE", raising=False)
    _bundled_config(bundled)
    config = load_firebase_config()
    assert config is not None
    assert config.project_id == "bundled-proj"
    assert config.usable


def test_env_override_stays_authoritative_over_bundled(tmp_path, monkeypatch):
    """Tests (and developers) pointing MIMFORGE_ENV_FILE at an
    absent file must get "not set up" even when a bundled config
    exists -- the override is authoritative, as before Stage 0."""
    bundled = _fake_bundled(tmp_path, monkeypatch)
    _bundled_config(bundled)
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(tmp_path / "absent.env"))
    assert load_firebase_config() is None


def test_bundled_config_unusable_values_are_not_set_up(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(tmp_path / "absent.env"))
    _bundled_config(bundled, project_id="")
    # Override says absent -> not set up; and with no override the
    # bundled-but-empty config is equally unusable. (The repo's own
    # .env.local may exist on a dev machine, so only the override
    # branch is asserted here.)
    assert load_firebase_config() is None


def test_sample_clip_resolution(tmp_path, monkeypatch):
    bundled = _fake_bundled(tmp_path, monkeypatch)
    assert resources.sample_clip_path() is None
    clip = _touch(bundled / "selftest" / "sample.mp4")
    assert resources.sample_clip_path() == clip


# --------------------------------------------------------- flow probes


@pytest.mark.skipif(
    resources.bundled_root() is None,
    reason="packaging fetch step has not staged bundled/ here",
)
def test_gate_v2_flow_probes_pass_with_bundled_resources():
    """The Gate v2 probes, run in-process: every probe green and
    every resource sourced from the bundle, PATH scrubbed."""
    from mimforge.selftest_flows import run_flow_probes

    results = run_flow_probes(require_bundled=True)
    failures = [(n, d) for n, ok, d in results if not ok]
    assert not failures, f"flow probes failed: {failures}"
    assert len(results) >= 10


@pytest.mark.skipif(
    resources.bundled_root() is None,
    reason="packaging fetch step has not staged bundled/ here",
)
def test_gate_colour_track_probe_rejects_a_static_lock(monkeypatch):
    """Retroactive audit regression (2026-11-27): the probe must
    FAIL when the tracker returns a full-coverage track that never
    moves -- the exact hollow proof the old tracker once produced
    on a static sample clip. A tracker that sits still is fed in
    directly, so the GATE (not the tracker) carries the invariant."""
    import numpy as np

    from mimforge import perception
    from mimforge.perception import TrackResult
    from mimforge.selftest_flows import run_flow_probes

    def static_track(path, prompt, stride=1):
        n = 18
        return TrackResult(
            times=np.arange(n) / 30.0,
            xs=np.full(n, 160.0),
            ys=np.full(n, 120.0),
            fps=30.0,
            frames_total=n,
            frames_tracked=n,
        )

    monkeypatch.setattr(perception, "track_object", static_track)
    results = dict((name, ok) for name, ok, _ in run_flow_probes(
        require_bundled=True
    ))
    assert results.get("colour-track sample frames") is False
