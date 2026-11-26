"""Phase 1, test T1.2: signed packages verify; one tampered byte fails."""

import zipfile

import pytest

from mimforge.signing import (
    VerificationError,
    export_package,
    generate_keypair,
    load_verified_package,
    read_package,
    verify_package,
)

FILES = {
    "design.json": b'{"platform": "bench-gantry", "span_mm": 600}',
    "controller.py": b"# generated controller (primitive API only)\n",
    "steps.json": b'[{"order": 1, "title": "Set up"}]',
}


@pytest.fixture()
def keys():
    return generate_keypair()


def test_export_verify_round_trip(tmp_path, keys):
    private_pem, public_pem = keys
    package = export_package(FILES, tmp_path / "lesson.tmachine", private_pem)
    manifest = verify_package(package, public_pem)
    assert set(manifest["files"]) == set(FILES)
    payload = load_verified_package(package, public_pem)
    assert payload == FILES


def test_tamper_one_byte_fails_verification_and_load_is_refused(tmp_path, keys):
    private_pem, public_pem = keys
    package = export_package(FILES, tmp_path / "lesson.tmachine", private_pem)
    # Tamper one byte of one payload file: rewrite the zip with a changed file.
    entries = read_package(package)
    entries["controller.py"] = b"# generated controller (primitive API only)\n# tampered"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    with pytest.raises(VerificationError):
        verify_package(package, public_pem)
    with pytest.raises(VerificationError):
        load_verified_package(package, public_pem)


def test_wrong_key_fails_verification(tmp_path, keys):
    private_pem, _public_pem = keys
    _other_private, other_public = generate_keypair()
    package = export_package(FILES, tmp_path / "lesson.tmachine", private_pem)
    with pytest.raises(VerificationError):
        verify_package(package, other_public)


# ------------------------------------------- full spec audit (2026-11-26)


def test_non_package_file_is_a_verification_error(tmp_path):
    """A corrupt/unreadable package raises VerificationError --
    the one refusal type callers handle -- not a raw zip error."""
    private_pem, public_pem = generate_keypair()
    target = tmp_path / "not-a-package.tmachine"
    target.write_bytes(b"this is not a zip file at all")
    with pytest.raises(VerificationError):
        verify_package(target, public_pem)


def test_bad_check_key_is_a_verification_error(tmp_path):
    private_pem, _public_pem = generate_keypair()
    out = export_package(FILES, tmp_path / "pkg.tmachine", private_pem)
    with pytest.raises(VerificationError):
        verify_package(out, b"-----BEGIN PUBLIC KEY-----\nnot a key\n")


def test_signed_non_object_manifest_is_refused(tmp_path):
    """A validly signed manifest that is a JSON list (not an
    object) is refused with VerificationError, not an
    AttributeError from deep inside verification."""
    import json as _json

    from mimforge.signing import (
        MANIFEST_NAME,
        SIGNATURE_NAME,
        build_manifest,
        load_private_key,
        sign_manifest,
    )

    private_pem, public_pem = generate_keypair()
    manifest = ["not", "an", "object"]
    signature = sign_manifest(manifest, load_private_key(private_pem))
    out = tmp_path / "list-manifest.tmachine"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("a.txt", b"a")
        zf.writestr(MANIFEST_NAME, _json.dumps(manifest))
        zf.writestr(SIGNATURE_NAME, signature)
    with pytest.raises(VerificationError):
        load_verified_package(out, public_pem)


def test_reserved_payload_names_are_rejected_at_export(tmp_path):
    from mimforge.signing import PackageError

    private_pem, _ = generate_keypair()
    with pytest.raises(PackageError):
        export_package(
            {"manifest.json": b"{}"}, tmp_path / "x.tmachine", private_pem
        )
    with pytest.raises(PackageError):
        export_package(
            {"signature.sig": b"x"}, tmp_path / "y.tmachine", private_pem
        )


def test_duplicate_entries_are_refused(tmp_path):
    """A zip with two entries under one name is ambiguous: read
    and verification refuse it outright."""
    private_pem, public_pem = generate_keypair()
    out = tmp_path / "dup.tmachine"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("a.txt", b"first")
        zf.writestr("a.txt", b"second")
    with pytest.raises(VerificationError):
        read_package(out)
    with pytest.raises(VerificationError):
        load_verified_package(out, public_pem)
