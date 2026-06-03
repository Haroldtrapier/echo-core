"""Prospect DM workflow — draft a personalized GovCon outreach DM for approval.

Replaces the rube "Government Contractor Prospect DM Generator" recipe. Like the
other content workflows it is approval-first: it generates the DM and queues it
as a draft (status ``pending_review``). Nothing is sent — review/send happens
downstream once approved.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.ai_generator import generate_prospect_dm
from echo.modules.content_store import create_content_item


@register
class ProspectDMWorkflow(BaseWorkflow):
    slug = "prospect_dm"
    name = "Prospect DM Generator"
    description = (
        "Drafts a personalized LinkedIn outreach DM for a GovCon prospect and "
        "queues it for human approval before sending."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("prospect_name"):
            errors.append("payload.prospect_name is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        prospect_name = payload["prospect_name"]
        company = payload.get("company", "")
        role = payload.get("role", "")
        angle = payload.get("angle", "")
        brand = payload.get("brand") or None

        dm_text = generate_prospect_dm(
            prospect_name, company=company, role=role, angle=angle, brand=brand or "",
        )

        title = f"DM: {prospect_name}" + (f" ({company})" if company else "")
        item = create_content_item(
            db,
            workflow=self.slug,
            platform="linkedin",
            content_type="prospect_dm",
            title=title[:200],
            caption=dm_text,
            topic=angle or "prospect outreach",
            brand=brand,
            status="pending_review",
        )

        return WorkflowResult(
            success=True,
            data={
                "post_id": item.post_id,
                "prospect_name": prospect_name,
                "company": company,
                "dm_text": dm_text,
                "status": item.status,
            },
            message=f"Draft DM for {prospect_name} created (post_id={item.post_id}) — pending approval",
        )
