"""Delivery orchestration: risk sign-off, checked code, signed export.

This module is the engine behind the shell's Deliver surface. It
composes the pieces the earlier phases built -- the risk assessment
and its teacher sign-off gate (``risk``), the controller / control
panel generator (``codegen``) with its static allow-list check
(``allowlist``), and the Ed25519-signed package export (``signing``)
-- into the three operations a teacher performs when handing a
machine design over:

1. review the risk assessment and sign it (a named teacher only --
   the gate in ``risk`` is used exactly as designed, never weakened);
2. generate the controller code, which is only handed over when the
   allow-list check passes for both artefacts;
3. export the signed ``.tmachine`` package, which the gate refuses
   until a valid sign-off exists.

Everything here is practical-agnostic: hazards, steps and wording all
arrive as template data. Failures raise :class:`DeliveryError` (or
propagate ``risk.ExportBlocked``) with plain-language messages the
shell can show as-is.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import risk, signing
from .allowlist import AllowlistReport, check_source
from .codegen import generate_control_panel, generate_controller
from .design import PLATFORM_ID, GantryParameters
from .risk import HazardEntry, RiskAssessment

__all__ = [
    "CodeBundle",
    "DeliveryError",
    "assessment_from_dict",
    "assessment_to_dict",
    "build_assessment",
    "design_parameters",
    "export_signed_package",
    "generate_checked_code",
    "load_or_create_keypair",
    "package_files",
]

PRIVATE_KEY_NAME = "author_key.pem"
PUBLIC_KEY_NAME = "author_key.pub.pem"


class DeliveryError(Exception):
    """A delivery step failed in a way the user can act on."""


# ------------------------------------------------------------ assessment


def build_assessment(template_data: dict) -> RiskAssessment:
    """The risk assessment for a template: platform base hazards
    merged with the hazards the template itself declares (template
    data, as designed in ``risk.generate_risk_assessment``)."""
    practical = template_data.get("practical", {})
    hazard_profile = practical.get("hazard_profile", {}) or {}
    return risk.generate_risk_assessment(
        practical_id=str(practical.get("id", "")),
        platform_id=str(template_data.get("platform_id") or PLATFORM_ID),
        template_hazards=list(hazard_profile.get("hazards", []) or []),
        template_id=str(template_data.get("template_id", "")),
    )


def assessment_to_dict(assessment: RiskAssessment) -> dict[str, Any]:
    """JSON-safe form of an assessment (for project records)."""
    return asdict(assessment)


def assessment_from_dict(data: dict[str, Any]) -> RiskAssessment:
    """Rebuild an assessment from :func:`assessment_to_dict` output."""
    return RiskAssessment(
        practical_id=str(data.get("practical_id", "")),
        platform_id=str(data.get("platform_id", "")),
        hazards=[
            HazardEntry(
                id=str(h.get("id", "")),
                description=str(h.get("description", "")),
                severity=str(h.get("severity", "")),
                likelihood=str(h.get("likelihood", "")),
                mitigation=str(h.get("mitigation", "")),
                source=str(h.get("source", "")),
            )
            for h in data.get("hazards", []) or []
        ],
        generated_at=str(data.get("generated_at", "")),
        signed_by=data.get("signed_by"),
        signed_at=data.get("signed_at"),
        signoff_hash=data.get("signoff_hash"),
    )


# ------------------------------------------------------------------ code


def design_parameters(params: GantryParameters) -> dict[str, Any]:
    """The design's numeric parameters as plain data for codegen."""
    data = asdict(params)
    low, high = data.pop("suspension_range_mm")
    data["suspension_low_mm"] = low
    data["suspension_high_mm"] = high
    return data


@dataclass
class CodeBundle:
    """Generated code plus the allow-list verdict for each artefact."""

    controller: str
    control_panel: str
    controller_report: AllowlistReport
    panel_report: AllowlistReport

    @property
    def passed(self) -> bool:
        return self.controller_report.passed and self.panel_report.passed

    @property
    def violations(self) -> list[str]:
        found = []
        for label, report in (
            ("controller", self.controller_report),
            ("control panel", self.panel_report),
        ):
            for violation in report.violations:
                found.append(f"{label}: {violation}")
        return found


def generate_checked_code(
    template_data: dict, params: GantryParameters
) -> CodeBundle:
    """Generate both artefacts and run the allow-list check on each.

    Raises :class:`DeliveryError` naming every violation when either
    artefact fails -- failing code is never handed to the caller as
    usable output.
    """
    controller = generate_controller(
        template_data, design_parameters(params)
    )
    panel = generate_control_panel(template_data)
    bundle = CodeBundle(
        controller=controller,
        control_panel=panel,
        controller_report=check_source(controller, "controller"),
        panel_report=check_source(panel, "panel"),
    )
    if not bundle.passed:
        raise DeliveryError(
            "the generated code failed its safety check and was not "
            "saved: " + "; ".join(bundle.violations)
        )
    return bundle


# --------------------------------------------------------------- package


def package_files(
    *,
    project_id: str,
    project_title: str,
    template_name: str,
    template_data: dict,
    draft: dict | None,
    lesson: dict | None,
    assessment: RiskAssessment,
    params: GantryParameters,
    code: CodeBundle,
) -> dict[str, bytes]:
    """The payload files of one delivery package, as name -> bytes."""

    def as_json(payload: Any) -> bytes:
        return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

    files = {
        "project.json": as_json(
            {
                "project_id": project_id,
                "title": project_title,
                "template_name": template_name,
                "template_id": template_data.get("template_id", ""),
            }
        ),
        "template.json": as_json(template_data),
        "risk_assessment.json": as_json(assessment_to_dict(assessment)),
        "design.json": as_json(design_parameters(params)),
        "controller.py": code.controller.encode("utf-8"),
        "control_panel.py": code.control_panel.encode("utf-8"),
    }
    if draft is not None:
        files["draft.json"] = as_json(draft)
    if lesson is not None:
        files["lesson.json"] = as_json(lesson)
    return files


def load_or_create_keypair(directory: str | Path) -> tuple[bytes, bytes]:
    """The author's signing keypair, created on first use and kept
    in ``directory``. Returns (private_pem, public_pem). The private
    key never leaves the author's machine through this module."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    private_path = folder / PRIVATE_KEY_NAME
    public_path = folder / PUBLIC_KEY_NAME
    if private_path.is_file() and public_path.is_file():
        return private_path.read_bytes(), public_path.read_bytes()
    private_pem, public_pem = signing.generate_keypair()
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    return private_pem, public_pem


def export_signed_package(
    files: dict[str, bytes],
    assessment: RiskAssessment,
    out_path: str | Path,
    private_key_pem: bytes,
) -> Path:
    """Write the signed package. The sign-off gate runs first,
    exactly as designed: ``risk.ExportBlocked`` propagates until a
    named teacher's valid sign-off exists."""
    risk.assert_export_ready(assessment)
    return signing.export_package(files, out_path, private_key_pem)
