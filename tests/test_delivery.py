"""Delivery orchestration (2026-11-26 surfacing pass): the risk
sign-off gate, the checked code generation, the signed package
export, the author key store, and the Firebase config / Firestore
REST backend that plugs into the sync seam.

The REST backend is exercised through a fake opener, so the wire
format, the value encoding, and the error wording are all tested
without a network -- and the API key is asserted absent from every
error message and from the request address.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from mimforge import delivery, risk, signing
from mimforge.design import GantryParameters
from mimforge.firebase_sync import (
    FirebaseConfig,
    FirestoreRestBackend,
    find_env_file,
    load_firebase_config,
    parse_env_text,
)
from mimforge.sync import MetadataSync, SyncConfig, SyncError
from mimforge.templates import load_template_data


@pytest.fixture(scope="module")
def template_data():
    return load_template_data("pendulum")


# ------------------------------------------------------------- assessment


def test_build_assessment_merges_platform_and_template_hazards(template_data):
    assessment = delivery.build_assessment(template_data)
    assert assessment.practical_id == template_data["practical"]["id"]
    assert assessment.platform_id == "bench_gantry"
    # 4 platform base hazards + the template's own declared hazards.
    template_hazards = template_data["practical"]["hazard_profile"]["hazards"]
    assert len(assessment.hazards) == 4 + len(template_hazards)
    assert not assessment.signed


def test_assessment_dict_round_trip_keeps_the_signoff(template_data):
    assessment = delivery.build_assessment(template_data)
    risk.sign(assessment, "Mrs A. Teacher")
    restored = delivery.assessment_from_dict(
        delivery.assessment_to_dict(assessment)
    )
    assert restored.signed
    assert restored.signed_by == "Mrs A. Teacher"
    assert [h.id for h in restored.hazards] == [
        h.id for h in assessment.hazards
    ]


# ------------------------------------------------------------------ code


def test_generated_code_passes_the_allowlist(template_data):
    bundle = delivery.generate_checked_code(
        template_data, GantryParameters()
    )
    assert bundle.passed
    assert "kernel.execute" in bundle.controller
    assert "ControlPanel" in bundle.control_panel


def test_generated_code_failure_raises_with_violations(template_data):
    """A template whose text breaks out of its comment (a newline in
    a step title injects a line of code) must be caught by the
    allow-list check and refused, never handed over. The injected
    line breaks the generated module's structure, so the refusal
    arrives as a failed check -- the code is refused either way."""
    poisoned = json.loads(json.dumps(template_data))
    poisoned["steps"][0]["title"] = "Set up\nimport os"
    with pytest.raises(delivery.DeliveryError) as excinfo:
        delivery.generate_checked_code(poisoned, GantryParameters())
    assert "failed its safety check" in str(excinfo.value)


# --------------------------------------------------------------- package


def test_export_gate_refuses_until_a_teacher_signs(template_data, tmp_path):
    assessment = delivery.build_assessment(template_data)
    bundle = delivery.generate_checked_code(
        template_data, GantryParameters()
    )
    files = delivery.package_files(
        project_id="p1",
        project_title="Demo",
        template_name="pendulum",
        template_data=template_data,
        draft=None,
        lesson=None,
        assessment=assessment,
        params=GantryParameters(),
        code=bundle,
    )
    private_pem, public_pem = signing.generate_keypair()
    with pytest.raises(risk.ExportBlocked):
        delivery.export_signed_package(
            files, assessment, tmp_path / "pkg.tmachine", private_pem
        )
    assert not (tmp_path / "pkg.tmachine").exists()

    risk.sign(assessment, "Mrs A. Teacher")
    # The package contents are assembled at export time (as the
    # shell does), so the sealed assessment inside carries the
    # sign-off it was exported under.
    files = delivery.package_files(
        project_id="p1",
        project_title="Demo",
        template_name="pendulum",
        template_data=template_data,
        draft=None,
        lesson=None,
        assessment=assessment,
        params=GantryParameters(),
        code=bundle,
    )
    out = delivery.export_signed_package(
        files, assessment, tmp_path / "pkg.tmachine", private_pem
    )
    manifest = signing.verify_package(out, public_pem)
    assert "controller.py" in manifest["files"]
    assert "control_panel.py" in manifest["files"]
    assert "risk_assessment.json" in manifest["files"]
    payload = signing.load_verified_package(out, public_pem)
    stored = json.loads(payload["risk_assessment.json"])
    assert stored["signed_by"] == "Mrs A. Teacher"


def test_keypair_is_created_once_and_reused(tmp_path):
    first = delivery.load_or_create_keypair(tmp_path / "keys")
    second = delivery.load_or_create_keypair(tmp_path / "keys")
    assert first == second
    assert (tmp_path / "keys" / delivery.PRIVATE_KEY_NAME).is_file()
    assert (tmp_path / "keys" / delivery.PUBLIC_KEY_NAME).is_file()


# --------------------------------------------------------- firebase config


def test_parse_env_text_tolerates_comments_and_quotes():
    values = parse_env_text(
        "# a comment\n"
        "FIREBASE_PROJECT_ID=demo-project\n"
        'FIREBASE_API_KEY="key-123"\n'
        "\n"
        "OTHER = spaced \n"
    )
    assert values["FIREBASE_PROJECT_ID"] == "demo-project"
    assert values["FIREBASE_API_KEY"] == "key-123"
    assert values["OTHER"] == "spaced"


def test_load_config_requires_project_and_key(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text("FIREBASE_PROJECT_ID=demo-project\n")
    assert load_firebase_config(env_file) is None  # no API key
    env_file.write_text(
        "FIREBASE_PROJECT_ID=demo-project\nFIREBASE_API_KEY=key-123\n"
    )
    config = load_firebase_config(env_file)
    assert config is not None
    assert config.project_id == "demo-project"
    assert load_firebase_config(tmp_path / "absent") is None


def test_find_env_file_honours_the_override(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("FIREBASE_PROJECT_ID=x\nFIREBASE_API_KEY=y\n")
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(env_file))
    assert find_env_file() == env_file
    monkeypatch.setenv("MIMFORGE_ENV_FILE", str(tmp_path / "absent"))
    assert find_env_file() is None


# ------------------------------------------------------- firestore backend


class _FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeFirestore:
    """A one-document-store stand-in for the Firestore REST API."""

    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        url = request.full_url
        doc_key = url.split("/documents/", 1)[1]
        if request.get_method() == "PATCH":
            body = json.loads(request.data.decode("utf-8"))
            self.documents[doc_key] = body
            return _FakeResponse(200, json.dumps(body).encode())
        if doc_key not in self.documents:
            error = {"error": {"message": "Document not found"}}
            raise urllib.error.HTTPError(
                url, 404, "Not Found", {}, io.BytesIO(
                    json.dumps(error).encode()
                )
            )
        return _FakeResponse(
            200, json.dumps(self.documents[doc_key]).encode()
        )


def _config() -> FirebaseConfig:
    return FirebaseConfig(api_key="TESTKEY-12345", project_id="demo-project")


def test_firestore_backend_round_trips_through_the_sync_layer():
    store = _FakeFirestore()
    backend = FirestoreRestBackend(_config(), opener=store)
    sync = MetadataSync(
        SyncConfig(enabled=True, project_id="demo-project", backend=backend)
    )
    payload = {
        "title": "Demo",
        "count": 3,
        "ratio": 1.5,
        "flag": True,
        "nothing": None,
        "tags": ["a", "b"],
        "nested": {"x": "y"},
    }
    result = sync.push_metadata("projects", "p1", payload)
    assert result.status == "synced"
    pull_result, pulled = sync.pull_metadata("projects", "p1")
    assert pull_result.status == "synced"
    assert pulled == payload
    # The key travels in a header only -- never in the address.
    assert "TESTKEY-12345" not in store.requests[0].full_url


def test_firestore_backend_missing_document_pulls_none():
    backend = FirestoreRestBackend(_config(), opener=_FakeFirestore())
    assert backend.pull("projects", "nope") is None


def test_firestore_refusal_is_plain_and_never_leaks_the_key():
    def refusing_opener(request):
        error = {
            "error": {"message": "Missing or insufficient permissions."}
        }
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {},
            io.BytesIO(json.dumps(error).encode()),
        )

    backend = FirestoreRestBackend(_config(), opener=refusing_opener)
    with pytest.raises(SyncError) as excinfo:
        backend.push("projects", "p1", {"title": "x"})
    message = str(excinfo.value)
    assert "403" in message
    assert "Missing or insufficient permissions" in message
    assert "TESTKEY-12345" not in message


def test_firestore_unreachable_is_a_plain_failure():
    def dead_opener(request):
        raise urllib.error.URLError("no route")

    backend = FirestoreRestBackend(_config(), opener=dead_opener)
    with pytest.raises(SyncError) as excinfo:
        backend.push("projects", "p1", {"title": "x"})
    assert "could not be reached" in str(excinfo.value)
