"""B. Opportunity-to-Content — turn an opportunity/topic into review-ready content.

Takes an opportunity, solicitation, keyword, agency, or market topic and produces
a LinkedIn post, a short email/newsletter blurb, a "what this means for
contractors" summary, and a Sturgeon CTA — bundled into one reviewable draft that
must be approved before anything publishes.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.modules.ai_generator import generate_content
from echo.workflows.govcon import pack


@register
class OpportunityToContentWorkflow(pack.GovConWorkflow):
    slug = "opportunity_to_content"
    name = "Opportunity-to-Content"
    description = (
        "Turns an opportunity, solicitation, agency, or market topic into a "
        "LinkedIn post, an email blurb, a 'what this means for contractors' "
        "summary, and a Sturgeon CTA — queued as one reviewable draft."
    )
    output_type = "draft"
    connector_targets = ("linkedin", "email_resend", "buffer")
    input_schema = {
        "topic": "str — opportunity title, solicitation, agency, or market topic (required)",
        "agency": "str? — agency context",
        "brand": "str? — brand voice context",
    }

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not (payload.get("topic") or payload.get("opportunity")):
            errors.append("payload.topic (or payload.opportunity) is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        topic = payload.get("topic") or payload.get("opportunity")
        agency = payload.get("agency")
        brand = payload.get("brand") or ""
        ctx = f"{topic}" + (f" (agency: {agency})" if agency else "")

        linkedin_post = generate_content(
            f"Write a concise, engaging LinkedIn post for GovCon contractors about: {ctx}. "
            f"End with a soft CTA. Brand: {brand}",
            system="You are a B2G/GovCon content strategist.",
            max_tokens=500,
        )
        email_blurb = generate_content(
            f"Write a 3-4 sentence email/newsletter blurb for GovCon contractors about: {ctx}.",
            system="You are a GovCon newsletter editor. Be concise and useful.",
            max_tokens=300,
        )
        what_it_means = generate_content(
            f"In 3-5 bullet points, explain what this means for small/mid GovCon "
            f"contractors and what they should do next: {ctx}.",
            system="You are a GovCon capture advisor.",
            max_tokens=400,
        )

        body = "\n\n".join(
            [
                f"# Opportunity-to-Content: {topic}",
                "## LinkedIn Post",
                linkedin_post,
                "## Email / Newsletter Blurb",
                email_blurb,
                "## What This Means for Contractors",
                what_it_means,
                "## Analyze in Sturgeon",
                pack.sturgeon_cta(),
            ]
        )

        queued = pack.queue_draft(
            db,
            workflow=self.slug,
            draft_type="linkedin_post",
            title=f"Content: {topic}",
            body=body,
            payload=payload,
            topic=topic,
            content_type="opportunity_content",
            campaign="opportunity_to_content",
        )

        return WorkflowResult(
            success=True,
            data={
                **queued,
                "linkedin_post": linkedin_post,
                "email_blurb": email_blurb,
                "what_it_means": what_it_means,
            },
            message=(
                f"Opportunity content drafted (approval_id={queued['approval_id']}) — "
                "pending review before publishing"
            ),
        )
