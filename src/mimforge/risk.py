"""Risk assessment generator + teacher sign-off gate (plan Phase 3.3).

A design may not be exported until a teacher has signed its risk
assessment. The assessment merges the platform's generic base hazards
with the hazards a practical's template declares (template data, never
core code). Signing records the teacher, the time, and a SHA-256 over
the canonical assessment text; any later change to the hazards breaks
the signature and re-blocks export.

Enforcement point: call :func:`assert_export_ready` before any
:func:`mimforge.signing.export_package` of a machine design. The
assessment also converts to the core :class:`mimforge.models.SafetyCase`
via :func:`to_safety_case`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mimforge.models import SafetyCase, SafetyLimits


class ExportBlocked(Exception):
    """Raised when an export is attempted without a valid sign-off."""


# Generic platform hazards: true of any bench gantry, whatever it
# carries. Mitigations are the control measures the design must carry.
BASE_HAZARDS: tuple[dict[str, str], ...] = (
    {
        "id": "pinch-carriage",
        "description": "Moving carriage can pinch fingers at the beam track.",
        "severity": "medium",
        "likelihood": "possible",
        "mitigation": "Track guarded; carriage travel interlocked with "
        "the presence zone; teacher-present mode for any run with "
        "learners present.",
    },
    {
        "id": "falling-load",
        "description": "Suspended load can fall if the line or spool fails.",
        "severity": "medium",
        "likelihood": "unlikely",
        "mitigation": "Line rated at 10x the load; pre-run line and spool "
        "check on the checklist; drop zone kept clear.",
    },
    {
        "id": "tip-over",
        "description": "Gantry can tip if the base is unstable or the bench is bumped.",
        "severity": "medium",
        "likelihood": "possible",
        "mitigation": "Feet span the bench depth; base stability checked "
        "before each run; bench kept clear of clutter.",
    },
    {
        "id": "low-voltage",
        "description": "Low-voltage wiring fault in the controller or sensors.",
        "severity": "low",
        "likelihood": "unlikely",
        "mitigation": "Extra-low voltage only; current-limited supply; "
        "short-circuit cut-off; no mains parts in any tier.",
    },
)


@dataclass
class HazardEntry:
    id: str
    description: str
    severity: str  # low | medium | high
    likelihood: str  # unlikely | possible | likely
    mitigation: str
    source: str  # "platform" or "template:<template_id>"


@dataclass
class RiskAssessment:
    practical_id: str
    platform_id: str
    hazards: list[HazardEntry] = field(default_factory=list)
    generated_at: str = ""
    signed_by: str | None = None
    signed_at: str | None = None
    signoff_hash: str | None = None

    @property
    def signed(self) -> bool:
        return self.signed_by is not None and self.verify_signoff()

    def canonical_text(self) -> str:
        """The exact text the sign-off covers (hash input)."""
        payload: dict[str, Any] = {
            "practical_id": self.practical_id,
            "platform_id": self.platform_id,
            "hazards": [
                {
                    "id": h.id,
                    "description": h.description,
                    "severity": h.severity,
                    "likelihood": h.likelihood,
                    "mitigation": h.mitigation,
                    "source": h.source,
                }
                for h in self.hazards
            ],
            "signed_by": self.signed_by,
            "signed_at": self.signed_at,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def verify_signoff(self) -> bool:
        """True only if a sign-off exists and still matches the hazards."""
        if not self.signed_by or not self.signed_at or not self.signoff_hash:
            return False
        expected = hashlib.sha256(self.canonical_text().encode("utf-8")).hexdigest()
        return expected == self.signoff_hash


def generate_risk_assessment(
    practical_id: str,
    platform_id: str,
    template_hazards: list[str] | None = None,
    template_id: str = "",
) -> RiskAssessment:
    """Merge platform base hazards with a template's declared hazards.

    Template hazards arrive as plain description strings (template
    data); they are recorded at severity ``low`` with a mitigation that
    the signing teacher must confirm -- the sign-off is the teacher
    confirming them, not the app asserting them.
    """
    hazards = [
        HazardEntry(
            id=row["id"],
            description=row["description"],
            severity=row["severity"],
            likelihood=row["likelihood"],
            mitigation=row["mitigation"],
            source="platform",
        )
        for row in BASE_HAZARDS
    ]
    for index, description in enumerate(template_hazards or []):
        hazards.append(
            HazardEntry(
                id=f"template-{index + 1}",
                description=description,
                severity="low",
                likelihood="possible",
                mitigation="Mitigation confirmed by the signing teacher "
                "at sign-off (see teacher notes on the template).",
                source=f"template:{template_id or practical_id}",
            )
        )
    return RiskAssessment(
        practical_id=practical_id,
        platform_id=platform_id,
        hazards=hazards,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def sign(assessment: RiskAssessment, teacher_name: str) -> RiskAssessment:
    """Teacher sign-off: records who/when and seals the assessment."""
    name = teacher_name.strip()
    if not name:
        raise ValueError("a teacher name is required to sign")
    assessment.signed_by = name
    assessment.signed_at = datetime.now(timezone.utc).isoformat()
    assessment.signoff_hash = hashlib.sha256(
        assessment.canonical_text().encode("utf-8")
    ).hexdigest()
    return assessment


def assert_export_ready(assessment: RiskAssessment) -> None:
    """Gate: refuse export until a valid teacher sign-off exists."""
    if not assessment.signed:
        raise ExportBlocked(
            "export blocked: no valid teacher sign-off on this risk "
            "assessment. A teacher must review the hazards and sign "
            "before the design can be exported."
        )


def to_safety_case(assessment: RiskAssessment) -> SafetyCase:
    """Core-schema view of the assessment (for project records)."""
    lines = [
        f"Risk assessment for {assessment.practical_id} "
        f"on {assessment.platform_id} ({len(assessment.hazards)} hazards):"
    ]
    for hazard in assessment.hazards:
        lines.append(
            f"- [{hazard.severity}/{hazard.likelihood}] {hazard.description} "
            f"Mitigation: {hazard.mitigation}"
        )
    if assessment.signed_by:
        lines.append(f"Signed by {assessment.signed_by} at {assessment.signed_at}.")
    return SafetyCase(
        limits=SafetyLimits(),
        interlocks=[
            "monitored stop + physical E-stop",
            "teacher-present mode for runs with learners present",
            "speed cap enforced in the controller",
        ],
        risk_assessment="\n".join(lines),
        signed_by_teacher=assessment.signed,
    )
