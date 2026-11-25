"""Signed export packages (plan Phase 1, step 1.2; security design 4.3).

A ``.tmachine`` package is a zip holding the project payload files, a
manifest of SHA-256 hashes (one per file), and an Ed25519 signature over
the canonical manifest bytes. Controllers and players verify the
signature and every file hash before loading; an unsigned or modified
package is refused for any motion run (it may still be opened read-only
for inspection by the caller, never by this module).

Keys are generated locally by the author and never leave the author's
machine through this module. Only the public key is needed to verify.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MANIFEST_NAME = "manifest.json"
SIGNATURE_NAME = "signature.sig"


class PackageError(Exception):
    """Base error for package export / verification failures."""


class VerificationError(PackageError):
    """Raised when a package fails signature or hash verification."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_pem, public_key_pem) for a fresh author key."""
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def load_private_key(pem: bytes) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(pem, password=None)


def load_public_key(pem: bytes) -> Ed25519PublicKey:
    return serialization.load_pem_public_key(pem)


def build_manifest(files: dict[str, bytes]) -> dict[str, Any]:
    """Manifest of per-file hashes for a set of package files."""
    return {
        "format_version": 1,
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
    }


def sign_manifest(manifest: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Base64 Ed25519 signature over the canonical manifest bytes."""
    return base64.b64encode(private_key.sign(_canonical_json(manifest))).decode("ascii")


def export_package(
    files: dict[str, bytes], out_path: str | Path, private_key_pem: bytes
) -> Path:
    """Write a signed ``.tmachine`` package. Returns the package path."""
    private_key = load_private_key(private_key_pem)
    manifest = build_manifest(files)
    signature = sign_manifest(manifest, private_key)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(files.items()):
            zf.writestr(name, data)
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
        zf.writestr(SIGNATURE_NAME, signature)
    return out


def read_package(path: str | Path) -> dict[str, bytes]:
    """Read every entry of a package into memory (no verification)."""
    with zipfile.ZipFile(path, "r") as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def verify_package(path: str | Path, public_key_pem: bytes) -> dict[str, Any]:
    """Verify signature + every file hash. Returns the manifest on success.

    Raises :class:`VerificationError` on any failure: missing manifest or
    signature, bad signature, a file hash mismatch, or an unlisted file.
    """
    public_key = load_public_key(public_key_pem)
    entries = read_package(path)
    if MANIFEST_NAME not in entries or SIGNATURE_NAME not in entries:
        raise VerificationError("package is missing its manifest or signature")
    try:
        manifest = json.loads(entries[MANIFEST_NAME].decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise VerificationError("package manifest is not valid JSON") from exc
    try:
        signature = base64.b64decode(entries[SIGNATURE_NAME].decode("ascii"))
    except ValueError as exc:
        raise VerificationError("package signature is not valid base64") from exc
    try:
        public_key.verify(signature, _canonical_json(manifest))
    except InvalidSignature as exc:
        raise VerificationError("package signature does not match the manifest") from exc
    listed = manifest.get("files", {})
    payload_names = {
        name for name in entries if name not in (MANIFEST_NAME, SIGNATURE_NAME)
    }
    if set(listed) != payload_names:
        raise VerificationError("package file list does not match its manifest")
    for name, expected in listed.items():
        if _sha256(entries[name]) != expected:
            raise VerificationError(f"file hash mismatch inside package: {name}")
    return manifest


def load_verified_package(path: str | Path, public_key_pem: bytes) -> dict[str, bytes]:
    """Verify, then return the payload files. Refuses tampered packages."""
    verify_package(path, public_key_pem)
    entries = read_package(path)
    return {
        name: data
        for name, data in entries.items()
        if name not in (MANIFEST_NAME, SIGNATURE_NAME)
    }
