#!/usr/bin/env python3
"""Fetch + stage every runtime asset the app bundles (Stage 0).

Run at PACKAGING time, before PyInstaller -- by
``setup/build-windows.ps1`` and by the CI workflow -- never at
install or run time. It fills the repo-local ``bundled/`` folder
(gitignored) that ``mimforge.spec`` folds into the frozen app as
``mimforge_resources/`` and that ``mimforge.resources`` resolves
in a source checkout:

    bundled/
      bin/            ffmpeg + ffprobe (+ their shared libraries)
      models/sam2.1-hiera-tiny/     encoder.onnx, decoder.onnx
      models/faster-whisper-base/   model.bin, config.json, ...
      config/firebase_config.json   (generated, see below)
      selftest/sample.mp4           (generated self-test asset)
      licenses/       LGPL-3.0.txt, FFMPEG-NOTICE.txt
      manifest.json   every staged file with size + SHA-256

Pins (verified at fetch time; a mismatch aborts the fetch):

- FFmpeg: BtbN / FFmpeg-Builds, release ``autobuild-2026-11-26-12-56``,
  the ``lgpl`` SHARED builds only -- LGPL, no GPL components, so
  the bundle stays commercially clean. (The product is
  proprietary; GPL builds are never used.)
- SAM 2.1 weights: the publisher table in ``mimforge.sam_tracker``
  (URL, size, SHA-256 per file) -- a single source of truth.
- Whisper base: ``Systran/faster-whisper-base`` at the pinned
  revision below; per-file SHA-256 recorded in the manifest.

The Firebase config is GENERATED here from the developer's
``.env.local`` (or ``FIREBASE_*`` environment variables, which is
how CI supplies it) and written to ``bundled/config/``. The values
are never printed, logged, or echoed by this script -- only the
fact that a config was staged, and its project id field name
count, are reported. Without any source values the staging skips
the config with a loud warning: that build's account/sync will
report NOT SET UP and its Gate v2 self-test will fail, by design.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED = REPO_ROOT / "bundled"
SRC = REPO_ROOT / "src"

# ------------------------------------------------------------- pins

FFMPEG_RELEASE = "autobuild-2026-11-26-12-56"
FFMPEG_BASE = (
    "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/"
    + FFMPEG_RELEASE
)
FFMPEG_ASSETS = {
    "win64": "ffmpeg-N-129308-g17de9f8597-win64-lgpl-shared.zip",
    "linux64": "ffmpeg-N-129308-g17de9f8597-linux64-lgpl-shared.tar.xz",
}
# SHA-256 of the release archives, recorded when the pin was made
# (2026-11-26) and verified on every fetch.
FFMPEG_SHA256 = {
    "win64": "7c7627690848a4de59f342012d973f00107df6595a7ae2bfc559a764a4a1ed8c",
    "linux64": "b818772f340f8467d2e0a240be3388e93a1746f2b1c6553423dfc5186c2acd63",
}

WHISPER_REPO = "Systran/faster-whisper-base"
WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")

# Piper voice (Stage 2): en_US-ljspeech-medium from rhasspy/piper-voices.
# Licence chain, verified line-by-line on 2026-11-26 before this pin
# was made (evidence in docs/SBOM.md): the voices repo is MIT; the
# voice's MODEL_CARD states its dataset is the LJ Speech dataset,
# "License: public domain", and the card says the voice was trained
# from scratch (no base voice, so no inherited chain). The card is
# staged beside the model so the evidence travels with the bundle.
# SHA-256 pins recorded at first fetch (2026-11-26) and verified on
# every fetch, exactly like the FFmpeg archives.
PIPER_VOICE = "en_US-ljspeech-medium"
PIPER_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/ljspeech/medium"
)
PIPER_FILES = {
    "model.onnx": (
        "en_US-ljspeech-medium.onnx",
        "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    ),
    "model.onnx.json": (
        "en_US-ljspeech-medium.onnx.json",
        "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
    ),
    "MODEL_CARD": ("MODEL_CARD", None),  # hash recorded in the manifest
}

# Kokoro-82M (Stage 2 quality voice): SHIPS because its measured
# pre-render gate passed on 2026-11-26 (see docs/SBOM.md): a full
# 9-step lesson pre-rendered in 66.8 s wall / 657 MB peak RSS on the
# build VM (1.5 shared vCPUs), against plan limits of 180 s (Dell
# E7240) / 360 s (ZenBook) and 1.5 GB -- and its Whisper round-trip
# intelligibility scored 0.935 vs Piper's 0.802 (first session:
# 50.8 s / 701 MB, 0.947 / 0.789 -- same verdict). Model: hexgrad/
# Kokoro-82M, Apache-2.0; ONNX conversion by the onnx-community.
# One voice only (af_heart). SHA-256 pins recorded at first fetch.
KOKORO_BASE = (
    "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
)
KOKORO_FILES = {
    "model_fp16.onnx": (
        "onnx/model_fp16.onnx",
        "ba4527a874b42b21e35f468c10d326fdff3c7fc8cac1f85e9eb6c0dfc35c334a",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "77a02c8e164413299b4b4c403b14f8e0e1c1b727db4d46a09d6327b861060a34",
    ),
    "voices/af_heart.bin": (
        "voices/af_heart.bin",
        "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b",
    ),
}

LGPL_URL = "https://www.gnu.org/licenses/lgpl-3.0.txt"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------ downloads
#
# Every fetch below goes through download(), and download() retries.
# Packaging runs unattended on CI runners and home machines whose
# networks drop connections: CI run 46023544376 died at this staging
# step when a single unretried urlopen hit a connect timeout
# (WinError 10060, ~24 s in) and the raw URLError killed the build
# before the test suite ever ran. Retrying is safe here because
# every asset is verified afterwards against its SHA-256 pin (or
# recorded in the manifest), exactly as before -- a download that
# eventually succeeds is held to the identical standard, and one
# that never succeeds aborts the fetch with a clear message.

DOWNLOAD_ATTEMPTS = 4
# Per-attempt socket timeout, unchanged from the original fetch:
# generous enough for the largest assets (~130 MB SAM weights,
# ~90 MB Kokoro model) on a slow runner. The failures retries cure
# are connect/read drops, which surface long before this.
DOWNLOAD_TIMEOUT = 300
# Slept between attempts: attempt 1 -> 5 s, 2 -> 15 s, 3 -> 45 s.
DOWNLOAD_BACKOFFS = (5, 15, 45)

# Transient transport failures worth another attempt. URLError,
# TimeoutError and the connection errors are all OSError subclasses;
# http.client.HTTPException covers the rest of the family --
# IncompleteRead (body cut short) and RemoteDisconnected -- which
# OSError does not.
_RETRYABLE_DOWNLOAD_ERRORS = (OSError, http.client.HTTPException)


def _sleep(seconds: float) -> None:
    """Backoff seam: the tests patch this so the suite stays fast."""
    time.sleep(seconds)


def download(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``, retrying transient failures.

    Up to DOWNLOAD_ATTEMPTS attempts with exponential backoff. If
    every attempt fails, the partial file is removed -- so a later
    run re-downloads instead of tripping over the fragment -- and a
    SystemExit names the asset and the URL.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": "mimforge-packaging"}
    )
    last_error: BaseException | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=DOWNLOAD_TIMEOUT
            ) as response:
                with dest.open("wb") as out:
                    shutil.copyfileobj(response, out, length=1 << 20)
            return
        except _RETRYABLE_DOWNLOAD_ERRORS as exc:
            last_error = exc
            if attempt < DOWNLOAD_ATTEMPTS:
                delay = DOWNLOAD_BACKOFFS[attempt - 1]
                print(
                    f"  download of {dest.name} failed "
                    f"(attempt {attempt}/{DOWNLOAD_ATTEMPTS}): {exc}\n"
                    f"  retrying in {delay}s ..."
                )
                _sleep(delay)
    dest.unlink(missing_ok=True)
    raise SystemExit(
        f"download of {dest.name} failed after "
        f"{DOWNLOAD_ATTEMPTS} attempts.\n"
        f"  url: {url}\n"
        f"  last error: {last_error}\n"
        "Check the network connection and re-run the fetch."
    )


# ------------------------------------------------------------ ffmpeg


def stage_ffmpeg(platform: str, work: Path) -> None:
    asset = FFMPEG_ASSETS[platform]
    archive = work / asset
    if not archive.is_file():
        print(f"  downloading ffmpeg ({platform}) ...")
        download(f"{FFMPEG_BASE}/{asset}", archive)
    digest = sha256_of(archive)
    expected = FFMPEG_SHA256[platform]
    if expected != digest:
        raise SystemExit(
            f"ffmpeg archive SHA-256 mismatch for {asset}:\n"
            f"  pinned {expected}\n  actual {digest}\n"
            "Refusing to stage an unverified binary."
        )
    extract = work / "ffmpeg-extract"
    if extract.exists():
        shutil.rmtree(extract)
    extract.mkdir(parents=True)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(extract, filter="data")
    roots = [p for p in extract.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise SystemExit("unexpected ffmpeg archive layout")
    source_bin = roots[0] / "bin"
    dest_bin = BUNDLED / "bin"
    dest_bin.mkdir(parents=True, exist_ok=True)
    for item in source_bin.iterdir():
        # ffplay is a media player; the app never uses it.
        if item.is_file() and not item.name.startswith("ffplay"):
            shutil.copy2(item, dest_bin / item.name)
    # The shared builds look for their libraries in ../lib
    # relative to the executables (RPATH $ORIGIN/../lib on Linux;
    # the Windows DLLs already sit in bin/). Preserve the layout.
    source_lib = roots[0] / "lib"
    if source_lib.is_dir():
        dest_lib = BUNDLED / "lib"
        dest_lib.mkdir(parents=True, exist_ok=True)
        for item in source_lib.iterdir():
            if ".so" not in item.name and item.suffix != ".dll":
                continue
            dest_item = dest_lib / item.name
            if item.is_symlink():
                # Versioned .so names are symlinks to one real
                # file; keep them links so the bundle carries the
                # library once, not three times.
                dest_item.unlink(missing_ok=True)
                os.symlink(os.readlink(item), dest_item)
            elif item.is_file():
                shutil.copy2(item, dest_item)
    # The build's own licence text travels with the binaries.
    for licence in roots[0].glob("LICENSE*"):
        shutil.copy2(licence, dest_bin / licence.name)
    print(f"  ffmpeg staged: {sorted(p.name for p in dest_bin.iterdir())}")


def stage_licences() -> None:
    folder = BUNDLED / "licenses"
    folder.mkdir(parents=True, exist_ok=True)
    lgpl = folder / "LGPL-3.0.txt"
    if not lgpl.is_file():
        download(LGPL_URL, lgpl)
    (folder / "FFMPEG-NOTICE.txt").write_text(
        "Mimforge bundles unmodified FFmpeg tools (ffmpeg, ffprobe)\n"
        f"from the FFmpeg-Builds project, release {FFMPEG_RELEASE},\n"
        "the LGPL ('lgpl shared') build variant: FFmpeg is licensed\n"
        "under the GNU Lesser General Public License v3 or later\n"
        "(see LGPL-3.0.txt alongside this notice). The tools are\n"
        "separate executables invoked as child processes; they are\n"
        "not linked into the application. Corresponding source is\n"
        "available from https://ffmpeg.org and from\n"
        "https://github.com/FFmpeg-Builds/FFmpeg-Builds .\n",
        encoding="utf-8",
    )
    print("  licences staged (LGPL-3.0 + notice)")


# --------------------------------------------------------------- SAM


def stage_sam(work: Path) -> None:
    sys.path.insert(0, str(SRC))
    from mimforge.sam_tracker import _WEIGHT_FILES

    dest = BUNDLED / "models" / "sam2.1-hiera-tiny"
    dest.mkdir(parents=True, exist_ok=True)
    # A verified local copy (the app's own per-user folder) is
    # reused instead of re-downloading 130 MB.
    local = Path.home() / "Mimforge" / "models" / "sam2.1-hiera-tiny"
    for name, (url, size, digest) in _WEIGHT_FILES.items():
        target = dest / name
        if target.is_file() and sha256_of(target) == digest:
            continue
        source = local / name
        if source.is_file() and sha256_of(source) == digest:
            shutil.copy2(source, target)
            print(f"  SAM {name}: copied from the verified local copy")
            continue
        tmp = work / name
        print(f"  downloading SAM {name} ...")
        download(url, tmp)
        if tmp.stat().st_size != size or sha256_of(tmp) != digest:
            raise SystemExit(f"SAM weight {name} failed verification")
        shutil.copy2(tmp, target)
    print("  SAM 2.1 weights staged + verified")


# ------------------------------------------------------------ whisper


def stage_whisper(work: Path) -> None:
    dest = BUNDLED / "models" / "faster-whisper-base"
    dest.mkdir(parents=True, exist_ok=True)
    for name in WHISPER_FILES:
        target = dest / name
        if target.is_file() and target.stat().st_size > 0:
            continue
        url = (
            f"https://huggingface.co/{WHISPER_REPO}/resolve/"
            f"{WHISPER_REVISION}/{name}"
        )
        tmp = work / f"whisper-{name}"
        print(f"  downloading Whisper base {name} ...")
        download(url, tmp)
        shutil.copy2(tmp, target)
    print("  Whisper base model staged (hashes in manifest.json)")


# ------------------------------------------------------ firebase cfg


def stage_firebase_config() -> None:
    sys.path.insert(0, str(SRC))
    from mimforge.firebase_sync import _FIELD_MAP, parse_env_text

    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env.local"
    if env_file.is_file():
        parsed = parse_env_text(env_file.read_text(encoding="utf-8"))
        values = {field: parsed.get(key, "") for key, field in _FIELD_MAP.items()}
    else:
        values = {
            field: os.environ.get(key, "") for key, field in _FIELD_MAP.items()
        }
    if not (values.get("project_id") and values.get("api_key")):
        print(
            "  WARNING: no Firebase config source (.env.local or "
            "FIREBASE_* env) -- bundled config SKIPPED. This build's "
            "account/sync will report NOT SET UP and Gate v2 will fail."
        )
        return
    dest = BUNDLED / "config" / "firebase_config.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(values, indent=2), encoding="utf-8")
    print(
        "  Firebase config staged "
        f"({sum(1 for v in values.values() if v)} fields populated; "
        "values not printed)"
    )


# -------------------------------------------------------- sample clip


def _gruut_espeak_lexicon_db() -> Path | None:
    """Locate the gruut-lang-en espeak lexicon (packaging-time data
    source only -- its SQLite file is read directly; the app never
    imports gruut). Installed via setup/build-windows.ps1 alongside
    the other packaging tools."""
    import sysconfig

    purelib = Path(sysconfig.get_paths()["purelib"])
    candidate = purelib / "gruut_lang_en" / "espeak" / "lexicon.db"
    return candidate if candidate.is_file() else None


def _convert_lexicon(lexicon_db: Path, id_map: dict) -> dict[str, str]:
    """Convert the espeak lexicon into {word: "phoneme phoneme ..."}
    keeping only phonemes the bundled voice actually knows (checked
    against its phoneme_id_map). Verified 2026-11-26: 124,389 words,
    100% coverage for en_US-ljspeech-medium."""
    con = sqlite3.connect(f"file:{lexicon_db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT word, phonemes FROM word_phonemes ORDER BY word, id"
        ).fetchall()
    finally:
        con.close()
    best: dict[str, str] = {}
    for word, phonemes in rows:
        best.setdefault(word, phonemes)

    def convert(ph_str: str) -> str | None:
        out: list[str] = []
        for tok in ph_str.split():
            while tok and tok[0] in ("ˈ", "ˌ"):
                out.append(tok[0])
                tok = tok[1:]
            if not tok:
                continue
            if tok in id_map:
                out.append(tok)
                continue
            base, length = tok, False
            if base.endswith("ː"):
                base, length = base[:-1], True
            if base in id_map:
                out.append(base)
                if length and "ː" in id_map:
                    out.append("ː")
                continue
            if all(ch in id_map for ch in base):
                out.extend(base)
                continue
            return None
        return " ".join(out)

    lexicon: dict[str, str] = {}
    for word, ph_str in best.items():
        converted = convert(ph_str)
        if converted:
            lexicon[word] = converted
    return lexicon


def stage_piper() -> None:
    """Stage the Piper voice + its bundled phoneme lexicon.

    The synthesis engine itself is Mimforge's own code
    (``src/mimforge/speech.py``) driving the voice model on the
    already-bundled ONNX Runtime -- no piper binary and no
    espeak-ng (GPL) anywhere. The lexicon is converted here, at
    packaging time, from the MIT-licensed gruut-lang-en data."""
    target = BUNDLED / "models" / "piper" / PIPER_VOICE
    target.mkdir(parents=True, exist_ok=True)
    for staged_name, (remote_name, pin) in PIPER_FILES.items():
        dest = target / staged_name
        if not dest.is_file():
            print(f"  downloading piper {staged_name} ...")
            download(PIPER_BASE + "/" + remote_name, dest)
        if pin:
            digest = sha256_of(dest)
            if digest != pin:
                raise SystemExit(
                    f"piper {staged_name}: SHA-256 mismatch "
                    f"(expected {pin[:12]}..., got {digest[:12]}...); "
                    "refusing to bundle an unverified voice file"
                )
            print(f"  piper {staged_name}: SHA-256 verified")
        else:
            print(f"  piper {staged_name}: staged (hash in manifest)")

    config = json.loads((target / "model.onnx.json").read_text(encoding="utf-8"))
    lexicon_db = _gruut_espeak_lexicon_db()
    if lexicon_db is None:
        raise SystemExit(
            "gruut-lang-en is not installed in this packaging environment; "
            "its espeak lexicon.db is the packaging-time data source for "
            "the bundled phoneme lexicon. Install it (packaging tool "
            "only, never shipped): pip install gruut-lang-en"
        )
    lexicon = _convert_lexicon(lexicon_db, config["phoneme_id_map"])
    if len(lexicon) < 100_000:
        raise SystemExit(
            f"lexicon conversion produced only {len(lexicon)} words; "
            "refusing to stage a gutted lexicon"
        )
    (target / "lexicon.json").write_text(
        json.dumps(lexicon, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"  piper lexicon: {len(lexicon)} words converted from "
        "gruut-lang-en espeak data (MIT)"
    )

    (BUNDLED / "licenses").mkdir(parents=True, exist_ok=True)
    (BUNDLED / "licenses" / "PIPER-VOICE-NOTICE.txt").write_text(
        "Piper voice: en_US-ljspeech-medium\n"
        "Source: rhasspy/piper-voices (MIT licence).\n"
        "Dataset: the LJ Speech Dataset -- public domain, per the\n"
        "voice's MODEL_CARD (staged beside the model in\n"
        "models/piper/en_US-ljspeech-medium/MODEL_CARD) and the\n"
        "dataset's home at keithito.com/LJ-Speech-Dataset. The card\n"
        "states the voice was trained from scratch, so no other\n"
        "voice's licence chain applies.\n"
        "Synthesis: Mimforge's own implementation of the Piper 1.2.0\n"
        "(MIT) model interface, running on ONNX Runtime (MIT).\n"
        "Phoneme lexicon: converted at packaging time from the\n"
        "gruut-lang-en espeak lexicon (MIT, rhasspy/gruut); the app\n"
        "ships only the converted word list, not gruut itself.\n"
        "No espeak-ng code or binaries (GPL) are bundled anywhere.\n",
        encoding="utf-8",
    )
    print(f"  piper voice staged -> {target}")


def stage_kokoro() -> None:
    """Stage Kokoro-82M fp16 + tokenizer + the af_heart voice.

    Only staged because the Stage 2 measured gate passed (numbers
    in the KOKORO_FILES comment above and docs/SBOM.md). The app
    drives the model directly on ONNX Runtime; the kokoro-onnx
    wrapper package is not shipped."""
    target = BUNDLED / "models" / "kokoro"
    target.mkdir(parents=True, exist_ok=True)
    for staged_name, (remote_name, pin) in KOKORO_FILES.items():
        dest = target / staged_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file():
            print(f"  downloading kokoro {staged_name} ...")
            download(KOKORO_BASE + "/" + remote_name, dest)
        digest = sha256_of(dest)
        if digest != pin:
            raise SystemExit(
                f"kokoro {staged_name}: SHA-256 mismatch "
                f"(expected {pin[:12]}..., got {digest[:12]}...); "
                "refusing to bundle an unverified model file"
            )
        print(f"  kokoro {staged_name}: SHA-256 verified")
    (BUNDLED / "licenses").mkdir(parents=True, exist_ok=True)
    (BUNDLED / "licenses" / "KOKORO-NOTICE.txt").write_text(
        "Kokoro-82M text-to-speech model (fp16 ONNX) and the\n"
        "af_heart voice style vector.\n"
        "Model: hexgrad/Kokoro-82M -- Apache License 2.0.\n"
        "ONNX conversion: onnx-community/Kokoro-82M-v1.0-ONNX.\n"
        "Inference: Mimforge's own code on ONNX Runtime (MIT);\n"
        "the kokoro-onnx wrapper package is not bundled.\n"
        "Measured gate (2026-11-26): full 9-step lesson pre-render\n"
        "66.8 s / 657 MB peak on the build VM; Whisper round-trip\n"
        "intelligibility 0.935. See docs/SBOM.md.\n",
        encoding="utf-8",
    )
    print(f"  kokoro staged -> {target}")


def stage_sample_clip() -> None:
    """Generate the self-test sample clip with the staged ffmpeg:
    a bright red disc swinging sinusoidally on a dark field, with
    a sine tone track. A test asset only -- it proves the bundled
    tools run; it is never user-facing proof of anything."""
    ffmpeg = BUNDLED / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg.is_file():
        # Platform of this machine, staged under its own name.
        candidates = list((BUNDLED / "bin").glob("ffmpeg*"))
        ffmpeg = candidates[0] if candidates else ffmpeg
    dest = BUNDLED / "selftest" / "sample.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Render the frames HERE and pipe them to ffmpeg as raw video.
    # The previous version drew the disc with ffmpeg's drawbox and
    # a sin(t) expression -- in the staged ffmpeg build the box came
    # out STATIC, so the old self-test passed vacuously on a
    # motionless disc until the improved tracker refused to lock
    # onto scenery (2026-11-26). Raw frames are deterministic on
    # any ffmpeg build: a bright red 40x40 square swinging
    # sinusoidally (2 s period) on a dark field, which reads to the
    # tracker exactly like a disc.
    import math

    width, height, n_frames = 320, 240, 90
    background = bytes((24, 20, 16))  # BGR of 0x101418
    red_run = bytes((0, 0, 255)) * 40
    raw = bytearray()
    for i in range(n_frames):
        frame = bytearray(background * (width * height))
        cx = 120 + round(80 * math.sin(2 * math.pi * i / 60))
        for row in range(100, 140):
            off = (row * width + cx) * 3
            frame[off : off + 120] = red_run
        raw += frame
    cmd = [
        str(ffmpeg),
        "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", "30", "-i", "-",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
        "-t", "3", "-c:v", "mpeg4", "-c:a", "aac", "-shortest",
        str(dest),
    ]
    proc = subprocess.run(cmd, input=bytes(raw), capture_output=True, timeout=120)
    if proc.returncode != 0 or not dest.is_file():
        raise SystemExit(
            f"sample clip generation failed: {proc.stderr.decode(errors='replace')}"
        )
    print(f"  sample clip staged ({dest.stat().st_size} bytes)")


# ------------------------------------------------------------ manifest


def write_manifest() -> None:
    entries = {}
    for path in sorted(BUNDLED.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            rel = path.relative_to(BUNDLED).as_posix()
            entries[rel] = {
                "size": path.stat().st_size,
                "sha256": sha256_of(path),
            }
    (BUNDLED / "manifest.json").write_text(
        json.dumps(
            {"ffmpeg_release": FFMPEG_RELEASE, "files": entries}, indent=2
        ),
        encoding="utf-8",
    )
    total = sum(e["size"] for e in entries.values())
    print(f"  manifest: {len(entries)} files, {total / 1e6:.0f} MB staged")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=("win64", "linux64"),
        default="win64" if os.name == "nt" else "linux64",
        help="which ffmpeg build to stage (default: this machine)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=REPO_ROOT / "bundled-work",
        help="download scratch folder (gitignored)",
    )
    args = parser.parse_args()
    args.workdir.mkdir(parents=True, exist_ok=True)
    BUNDLED.mkdir(parents=True, exist_ok=True)
    print(f"Staging bundled assets for {args.platform} into {BUNDLED}")
    stage_ffmpeg(args.platform, args.workdir)
    stage_licences()
    stage_sam(args.workdir)
    stage_whisper(args.workdir)
    stage_piper()
    stage_kokoro()
    stage_firebase_config()
    stage_sample_clip()
    write_manifest()
    print("Bundled assets ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
