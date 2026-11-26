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
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
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

LGPL_URL = "https://www.gnu.org/licenses/lgpl-3.0.txt"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "mimforge-packaging"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        with dest.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)


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
    # Draw the disc with ffmpeg's drawbox on a moving x expression
    # (a filled square reads to the centroid tracker exactly like
    # a disc: one bright blob on a dark field).
    vf = (
        "drawbox=x='120+80*sin(2*PI*t/2)':y=100:w=40:h=40:"
        "color=red@1:t=fill"
    )
    cmd = [
        str(ffmpeg),
        "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0x101418:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
        "-vf", vf,
        "-t", "3", "-c:v", "mpeg4", "-c:a", "aac", "-shortest",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not dest.is_file():
        raise SystemExit(f"sample clip generation failed: {proc.stderr}")
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
    stage_firebase_config()
    stage_sample_clip()
    write_manifest()
    print("Bundled assets ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
