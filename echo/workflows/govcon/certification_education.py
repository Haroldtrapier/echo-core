"""D. Certification Education Workflow.

Produces educational GovCon content around certifications and registrations
(SDVOSB, 8(a), WOSB, HUBZone, SAM.gov, UEI/CAGE, capability statements) as a
reviewable draft. Works with or without an AI key — a curated fallback ensures a
useful draft every time.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.modules.ai_generator import generate_content
from echo.workflows.govcon import pack

TOPICS = {
    "sdvosb": "SDVOSB (Service-Disabled Veteran-Owned Small Business) certification",
    "8a": "the SBA 8(a) Business Development Program",
    "wosb": "WOSB / EDWOSB (Women-Owned Small Business) certification",
    "hubzone": "the HUBZone program",
    "samgov": "SAM.gov registration",
    "uei_cage": "UEI and CAGE codes",
    "capability_statement": "writing an effective capability statement",
}

FALLBACK = {
    "sdvosb": (
        "- What it is: set-aside eligibility for service-disabled veteran-owned firms.\n"
        "- Who qualifies: 51%+ owned/controlled by a service-disabled veteran.\n"
        "- How to get it: verify via SBA (VetCert); keep documentation current.\n"
        "- Why it matters: access to SDVOSB set-aside and sole-source awards."
    ),
    "8a": (
        "- What it is: a 9-year business development program for socially/economically disadvantaged firms.\n"
        "- Who qualifies: 51%+ owned by disadvantaged individuals; size and net-worth limits apply.\n"
        "- How to get it: apply in certify.SBA.gov with financials and narrative.\n"
        "- Why it matters: sole-source awards up to threshold + mentorship."
    ),
    "wosb": (
        "- What it is: set-aside eligibility for women-owned small businesses (EDWOSB adds economic disadvantage).\n"
        "- Who qualifies: 51%+ owned/controlled by women.\n"
        "- How to get it: self-certify or use an approved third-party certifier in certify.SBA.gov.\n"
        "- Why it matters: WOSB/EDWOSB set-asides in eligible NAICS."
    ),
    "hubzone": (
        "- What it is: preference for firms in Historically Underutilized Business Zones.\n"
        "- Who qualifies: principal office in a HUBZone + 35% of employees residing in one.\n"
        "- How to get it: apply and maintain eligibility as maps update.\n"
        "- Why it matters: 10% price evaluation preference + set-asides."
    ),
    "samgov": (
        "- What it is: the System for Award Management — the federal registration of record.\n"
        "- Who needs it: any entity seeking federal awards.\n"
        "- How: register/renew at SAM.gov; renew annually before lapse.\n"
        "- Why it matters: an expired registration removes you from award eligibility."
    ),
    "uei_cage": (
        "- UEI: the Unique Entity ID that replaced DUNS; assigned in SAM.gov.\n"
        "- CAGE: Commercial and Government Entity code identifying your location.\n"
        "- How: both are established/validated through SAM.gov registration.\n"
        "- Why it matters: required on registrations, proposals, and payments."
    ),
    "capability_statement": (
        "- Purpose: a one-page marketing sheet for federal buyers.\n"
        "- Must include: core competencies, differentiators, past performance, and company data (UEI/CAGE/NAICS).\n"
        "- Tips: tailor to the agency; lead with outcomes; keep it to one page.\n"
        "- Why it matters: it's your first impression with contracting officers."
    ),
}


@register
class CertificationEducationWorkflow(pack.GovConWorkflow):
    slug = "certification_education"
    name = "Certification Education"
    description = (
        "Produces educational GovCon content on certifications/registrations "
        "(SDVOSB, 8(a), WOSB, HUBZone, SAM.gov, UEI/CAGE, capability statements) "
        "as a reviewable draft."
    )
    output_type = "draft"
    connector_targets = ("linkedin", "email_resend")
    input_schema = {
        "certification": f"str — one of {list(TOPICS)} (default sdvosb)",
        "brand": "str? — brand voice context",
    }

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        cert = str(payload.get("certification") or payload.get("topic") or "sdvosb").lower()
        cert = cert.replace("(", "").replace(")", "").replace(" ", "_")
        key = cert if cert in TOPICS else "sdvosb"
        subject = TOPICS[key]

        educational = generate_content(
            f"Write a clear, encouraging educational explainer for small GovCon "
            f"contractors about {subject}. Cover what it is, who qualifies, how to "
            f"get it, and why it matters. Use short bullets.",
            system="You are a GovCon certification educator. Be accurate and practical.",
            max_tokens=600,
        )
        if not educational or "AI generation unavailable" in educational:
            educational = FALLBACK[key]

        body = "\n\n".join(
            [
                f"# GovCon Education: {subject}",
                educational,
                "## Next Step",
                "Not sure how this maps to your pipeline? "
                + pack.sturgeon_cta(),
            ]
        )

        queued = pack.queue_draft(
            db,
            workflow=self.slug,
            draft_type="email",
            title=f"Education: {subject}",
            body=body,
            payload=payload,
            topic=subject,
            content_type="certification_education",
            campaign=f"cert_edu_{key}",
        )

        return WorkflowResult(
            success=True,
            data={**queued, "certification": key, "subject": subject},
            message=f"Certification education draft created ({subject}) — pending review",
        )
