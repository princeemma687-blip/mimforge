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
