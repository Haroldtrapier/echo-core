"""Conversion tracking (Phase 2).

Records conversion events to the Echo analytics stream (always) and forwards
them to GA4 via the Measurement Protocol (only when configured; otherwise no-op).

Canonical event names + payload shape:

    cta_click          {campaign, url, client_id?, source?, medium?, content?}
    sturgeon_handoff   {handoff_id, opportunity_title, agency?, solicitation_number?}
    lead_captured      {lead_id?, source?, campaign?}
    proposal_conversion{handoff_id?, sturgeon_ref?, amount?}

Every conversion is written to ``echo_analytics_events`` as
``event_type = "conversion_<name>"`` so the analytics API and Weekly Tracker can
count them, independent of whether GA4 is wired up.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.integrations import ga4_measurement
from echo.modules import events

log = get_logger("echo.modules.conversion")

CONV_CTA_CLICK = "cta_click"
CONV_STURGEON_HANDOFF = "sturgeon_handoff"
CONV_LEAD_CAPTURED = "lead_captured"
CONV_PROPOSAL_CONVERSION = "proposal_conversion"

KNOWN_CONVERSIONS = frozenset(
    {CONV_CTA_CLICK, CONV_STURGEON_HANDOFF, CONV_LEAD_CAPTURED, CONV_PROPOSAL_CONVERSION}
)


def is_ga4_configured() -> bool:
    return ga4_measurement.is_configured()


def track(
    db: Session,
    conversion: str,
    *,
    metadata: dict[str, Any] | None = None,
    client_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Record a conversion event (analytics always; GA4 if configured)."""
    if conversion not in KNOWN_CONVERSIONS:
        log.warning("Unknown conversion %r (known: %s)", conversion, KNOWN_CONVERSIONS)
    metadata = metadata or {}

    events.record_event(
        db,
        f"conversion_{conversion}",
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
        tenant_id=tenant_id,
        metadata=metadata,
    )

    ga4_result = ga4_measurement.send_event(
        client_id=client_id or user_id or "echo.server",
        name=conversion,
        params={k: v for k, v in metadata.items() if v is not None},
    )
    return {"conversion": conversion, "recorded": True, "ga4": ga4_result}


def track_cta_click(
    db: Session,
    *,
    campaign: str,
    url: str | None = None,
    client_id: str | None = None,
    source: str | None = None,
    medium: str | None = None,
    content: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    return track(
        db,
        CONV_CTA_CLICK,
        metadata={"campaign": campaign, "url": url, "source": source,
                  "medium": medium, "content": content},
        client_id=client_id,
        tenant_id=tenant_id,
    )


def track_sturgeon_handoff(db: Session, handoff: Any, *, tenant_id: str | None = None) -> dict[str, Any]:
    """Record a Sturgeon-handoff conversion for a handoff record."""
    return track(
        db,
        CONV_STURGEON_HANDOFF,
        metadata={
            "handoff_id": getattr(handoff, "id", None),
            "opportunity_title": getattr(handoff, "opportunity_title", None),
            "agency": getattr(handoff, "agency", None),
            "solicitation_number": getattr(handoff, "solicitation_number", None),
        },
        workflow_run_id=getattr(handoff, "workflow_run_id", None),
        tenant_id=tenant_id or getattr(handoff, "tenant_id", None),
    )
