"""The Resource Layer (Stage 0, 2026-11-26).

One resolver for every runtime asset the app needs -- the fix for
the defect family behind walk findings #5 and #6 (and, in spirit,
the run #6 scipy crash): the shipped bundle silently depended on
the development machine three times, because each subsystem
improvised its own lookup (``shutil.which`` for ffmpeg/ffprobe,
a hunt for ``.env.local`` for the Firebase config, a first-run
download folder for the SAM weights). All three improvisations
succeed on the dev machine and fail -- politely -- on a clean one.

Every lookup now goes through this module, in one order:

1. **Bundled** -- inside the installed app (PyInstaller datas under
   ``mimforge_resources/``; in a source checkout, the repo-local
   ``bundled/`` folder produced by ``setup/fetch_bundled_assets.py``
   at packaging time).
2. **Per-user data** -- ``~/Mimforge/`` (e.g. weights a repair
   download fetched, a config the user placed there).
3. **Developer override** -- environment variables and the OS PATH,
   honoured last and never required by a shipped build.

Gate v2 (``mimforge --self-test`` in a frozen build) asserts that
every registered resource resolves to a BUNDLED path, so this
family cannot ship a fourth time.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

__all__ = [
    "BUNDLED_DIR_NAME",
    "ResourceNotFound",
    "bundled_root",
    "user_data_dir",
    "resolve_binary",
    "ffmpeg_path",
    "ffprobe_path",
    "sam_weights_dir",
    "whisper_model_dir",
    "firebase_config_path",
    "piper_voice_dir",
    "kokoro_dir",
    "sample_clip_path",
    "describe_resolution",
]

#: Directory (inside the bundle / repo) holding packaged resources.
BUNDLED_DIR_NAME = "mimforge_resources"

#: Repo-local folder the packaging fetch step fills (gitignored).
_DEV_BUNDLED_NAME = "bundled"

SAM_FOLDER = "sam2.1-hiera-tiny"
WHISPER_FOLDER_TEMPLATE = "faster-whisper-{size}"
FIREBASE_CONFIG_NAME = "firebase_config.json"
SAMPLE_CLIP_NAME = "sample.mp4"

#: The bundled Piper narration voice under models/piper/ (Stage 2).
PIPER_VOICE = "en_US-ljspeech-medium"


class ResourceNotFound(Exception):
    """A required bundled resource could not be resolved anywhere."""


# ------------------------------------------------------------- roots


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_root() -> Optional[Path]:
    """The bundled resources root, or None when no bundle exists.

    Frozen: ``<sys._MEIPASS>/mimforge_resources`` (PyInstaller
    onedir puts datas under ``_internal``; ``_MEIPASS`` points
    there), falling back to a sibling of the executable.
    Source: ``MIMFORGE_BUNDLED_DIR`` when set, else the repo-local
    ``bundled/`` folder when the packaging fetch step has run.
    """
    if _frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / BUNDLED_DIR_NAME
            if candidate.is_dir():
                return candidate
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (
            exe_dir / BUNDLED_DIR_NAME,
            exe_dir / "_internal" / BUNDLED_DIR_NAME,
        ):
            if candidate.is_dir():
                return candidate
        return None
    override = os.environ.get("MIMFORGE_BUNDLED_DIR")
    if override:
        root = Path(override)
        return root if root.is_dir() else None
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / _DEV_BUNDLED_NAME
    return candidate if candidate.is_dir() else None


def user_data_dir() -> Path:
    """The per-user data folder (``~/Mimforge``; dev override via
    ``MIMFORGE_HOME``)."""
    override = os.environ.get("MIMFORGE_HOME")
    if override:
        return Path(override)
    return Path.home() / "Mimforge"


def _is_bundled(path: Path) -> bool:
    root = bundled_root()
    if root is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# ------------------------------------------------------------ binaries


def _exe_name(name: str) -> str:
    if os.name == "nt":
        return f"{name}.exe"
    return name


def resolve_binary(name: str) -> Optional[Path]:
    """Resolve an external binary (``ffmpeg`` / ``ffprobe``).

    Order: bundled ``bin/`` -> per-user ``bin/`` -> the explicit
    dev override ``MIMFORGE_<NAME>`` -> the OS PATH (dev only;
    a shipped build never needs it).
    """
    exe = _exe_name(name)
    root = bundled_root()
    if root is not None:
        candidate = root / "bin" / exe
        if candidate.is_file():
            return candidate
    candidate = user_data_dir() / "bin" / exe
    if candidate.is_file():
        return candidate
    override = os.environ.get(f"MIMFORGE_{name.upper()}")
    if override:
        path = Path(override)
        if path.is_file():
            return path
    found = shutil.which(name)
    return Path(found) if found else None


def ffmpeg_path() -> Optional[Path]:
    return resolve_binary("ffmpeg")


def ffprobe_path() -> Optional[Path]:
    return resolve_binary("ffprobe")


# -------------------------------------------------------------- models


def sam_weights_dir() -> Optional[Path]:
    """The SAM 2.1 weights folder: bundled first, then the legacy
    per-user locations the first-run download used (the download
    remains as a repair path into the per-user folder)."""
    root = bundled_root()
    if root is not None:
        candidate = root / "models" / SAM_FOLDER
        if candidate.is_dir():
            return candidate
    override = os.environ.get("MIMFORGE_SAM_DIR")
    if override:
        return Path(override)
    candidate = user_data_dir() / "models" / SAM_FOLDER
    if candidate.is_dir():
        return candidate
    return None


def sam_weights_repair_dir() -> Path:
    """Where a repair download writes when no bundled copy verifies."""
    return user_data_dir() / "models" / SAM_FOLDER


def whisper_model_dir(size: str = "base") -> Optional[Path]:
    """A local faster-whisper model folder (with ``model.bin``),
    bundled first, then per-user. None when no local copy exists --
    the caller then falls back to the model name (which downloads
    on a dev machine; a shipped build always has the bundle)."""
    folder = WHISPER_FOLDER_TEMPLATE.format(size=size)
    root = bundled_root()
    if root is not None:
        candidate = root / "models" / folder
        if (candidate / "model.bin").is_file():
            return candidate
    candidate = user_data_dir() / "models" / folder
    if (candidate / "model.bin").is_file():
        return candidate
    return None


# -------------------------------------------------------------- config


def firebase_config_path() -> Optional[Path]:
    """The bundled Firebase web config (a public project
    identifier -- the per-user Firestore rules are the security),
    then a per-user copy. The ``.env.local`` developer file is
    handled by ``firebase_sync`` as the final dev fallback."""
    root = bundled_root()
    if root is not None:
        candidate = root / "config" / FIREBASE_CONFIG_NAME
        if candidate.is_file():
            return candidate
    candidate = user_data_dir() / "config" / FIREBASE_CONFIG_NAME
    if candidate.is_file():
        return candidate
    return None


def piper_voice_dir(voice: str = PIPER_VOICE) -> Optional[Path]:
    """Directory of the bundled Piper narration voice (model.onnx +
    model.onnx.json + lexicon.json), bundled first, then per-user.
    None when the voice is not available on this machine."""
    required = ("model.onnx", "model.onnx.json", "lexicon.json")
    root = bundled_root()
    if root is not None:
        candidate = root / "models" / "piper" / voice
        if all((candidate / name).is_file() for name in required):
            return candidate
    candidate = user_data_dir() / "models" / "piper" / voice
    if all((candidate / name).is_file() for name in required):
        return candidate
    return None


def kokoro_dir() -> Optional[Path]:
    """Directory of the Kokoro-82M model, when bundled. Kokoro
    shipped because its measured pre-render gate passed (plan
    Stage 2; numbers in docs/SBOM.md); returns None on any machine
    where the model files are absent."""
    root = bundled_root()
    if root is not None:
        candidate = root / "models" / "kokoro"
        if (candidate / "model_fp16.onnx").is_file():
            return candidate
    candidate = user_data_dir() / "models" / "kokoro"
    if (candidate / "model_fp16.onnx").is_file():
        return candidate
    return None


def sample_clip_path() -> Optional[Path]:
    """The self-test sample clip (a generated test asset only --
    never shown to users as proof of anything)."""
    root = bundled_root()
    if root is not None:
        candidate = root / "selftest" / SAMPLE_CLIP_NAME
        if candidate.is_file():
            return candidate
    return None


# ----------------------------------------------------------- reporting


def describe_resolution() -> dict[str, dict[str, Optional[str]]]:
    """Where every registered resource resolves from right now --
    the Gate v2 report. ``source`` is ``bundled`` / ``user`` /
    ``override`` / None."""
    def source_of(path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        if _is_bundled(path):
            return "bundled"
        try:
            path.resolve().relative_to(user_data_dir().resolve())
            return "user"
        except (ValueError, OSError):
            return "override"

    sam = sam_weights_dir()
    whisper = whisper_model_dir()
    return {
        "ffmpeg": {
            "path": str(ffmpeg_path()) if ffmpeg_path() else None,
            "source": source_of(ffmpeg_path()),
        },
        "ffprobe": {
            "path": str(ffprobe_path()) if ffprobe_path() else None,
            "source": source_of(ffprobe_path()),
        },
        "sam_weights": {
            "path": str(sam) if sam else None,
            "source": source_of(sam),
        },
        "whisper_base": {
            "path": str(whisper) if whisper else None,
            "source": source_of(whisper),
        },
        "firebase_config": {
            "path": (
                str(firebase_config_path()) if firebase_config_path() else None
            ),
            "source": source_of(firebase_config_path()),
        },
        "piper_voice": {
            "path": str(piper_voice_dir()) if piper_voice_dir() else None,
            "source": source_of(piper_voice_dir()),
        },
        "kokoro": {
            "path": str(kokoro_dir()) if kokoro_dir() else None,
            "source": source_of(kokoro_dir()),
        },
        "sample_clip": {
            "path": str(sample_clip_path()) if sample_clip_path() else None,
            "source": source_of(sample_clip_path()),
        },
    }
