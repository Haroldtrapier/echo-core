"""E. Lead Nurture Workflow.

Creates a simple 5-touch email nurture sequence — welcome, education, pain point,
Sturgeon CTA, and a proposal/human-review offer — as individually reviewable
drafts. Nothing sends automatically: each email is saved as a draft approval and
a single ``lead_nurture_created`` analytics event records the batch.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.modules import events
from echo.modules.ai_generator import generate_content
from echo.workflows.govcon import pack

SEQUENCE = [
    ("welcome", "Welcome to GovCon Command Center",
     "Write a warm welcome email introducing the value of GovCon Command Center for a new small-business contractor lead."),
    ("education", "Getting your GovCon foundations right",
     "Write an educational email covering SAM.gov, UEI/CAGE, and certifications as the foundation for winning federal work."),
    ("pain_point", "Why most small contractors never win a bid",
     "Write an email that names the real pain points (finding the right opportunities, compliance, proposal effort) and reassures the reader."),
    ("sturgeon_cta", "Turn an opportunity into a proposal",
     "Write an email inviting the reader to send a live opportunity to Sturgeon AI for solicitation analysis, compliance, and a proposal draft."),
    ("offer", "Want a human expert on your next proposal?",
     "Write an email offering proposal credits and an optional human-review purchase for their next bid. Low-pressure, helpful."),
]


@register
class LeadNurtureWorkflow(pack.GovConWorkflow):
    slug = "lead_nurture"
    name = "Lead Nurture Sequence"
    description = (
        "Generates a 5-touch email nurture sequence (welcome → education → pain "
        "point → Sturgeon CTA → proposal/human-review offer) as reviewable drafts."
    )
    output_type = "draft"
    connector_targets = ("email_resend",)
    input_schema = {
        "lead_name": "str? — personalization",
        "brand": "str? — brand voice context",
    }

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        lead_name = payload.get("lead_name") or "there"
        brand = payload.get("brand") or "GovCon Command Center"
        ctx = pack.run_ctx(payload)

        drafts: list[dict[str, Any]] = []
        for step, subject, prompt in SEQUENCE:
            email_body = generate_content(
                f"{prompt}\nGreeting to: {lead_name}. Brand: {brand}. Keep it under 150 words.",
                system="You are a GovCon email marketer. Concise, helpful, no hype.",
                max_tokens=350,
            )
            if not email_body or "AI generation unavailable" in email_body:
                email_body = (
                    f"Hi {lead_name},\n\n{subject}. "
                    "This is a placeholder draft — configure ANTHROPIC_API_KEY for AI-written copy.\n\n"
                    "— " + brand
                )
            if step == "sturgeon_cta":
                email_body += "\n\n" + pack.sturgeon_cta()

            body = f"Subject: {subject}\n\n{email_body}"
            queued = pack.queue_draft(
                db,
                workflow=self.slug,
                draft_type="email",
                title=f"Nurture [{step}]: {subject}",
                body=body,
                payload=payload,
                topic="lead_nurture",
                content_type="nurture_email",
                campaign="lead_nurture",
                extra_metadata={"step": step, "sequence_position": len(drafts) + 1},
            )
            drafts.append({"step": step, "subject": subject, **queued})

        events.record_event(
            db,
            events.EVENT_LEAD_NURTURE_CREATED,
            workflow_id=self.slug,
            workflow_run_id=ctx["run_id"],
            user_id=ctx["user_id"],
            tenant_id=ctx["tenant_id"],
            metadata={"emails": len(drafts), "steps": [d["step"] for d in drafts]},
        )

        return WorkflowResult(
            success=True,
            data={"drafts": drafts, "count": len(drafts)},
            message=f"Lead nurture sequence created ({len(drafts)} email drafts) — pending review",
        )
