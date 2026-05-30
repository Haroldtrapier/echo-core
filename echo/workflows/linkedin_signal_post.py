"""LinkedIn signal post workflow — generate and publish (or dry-run) a LinkedIn post."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.ai_generator import generate_linkedin_post
from echo.modules.publisher import publish


@register
class LinkedInSignalPostWorkflow(BaseWorkflow):
    slug = "linkedin_signal_post"
    name = "LinkedIn Signal Post"
    description = (
        "Generates a GovCon-focused LinkedIn post via Claude and publishes it "
        "(dry-run by default; live when ECHO_ALLOW_LIVE_PUBLISH=true)."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("topic"):
            errors.append("payload.topic is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        topic = payload["topic"]
        brand = payload.get("brand", "")
        dry_run = payload.get("dry_run", True)

        post_text = generate_linkedin_post(topic, brand=brand)

        result = publish(
            "linkedin",
            {"body": post_text, "caption": post_text},
            dry_run=dry_run,
        )

        return WorkflowResult(
            success=result.success,
            data={
                "post_text": post_text,
                "dry_run": result.dry_run,
                "simulated_output": result.simulated_output,
                "live_url": result.live_url,
            },
            message=(
                f"LinkedIn post {'simulated' if result.dry_run else 'published'} "
                f"({'success' if result.success else 'failed'})"
            ),
        )
