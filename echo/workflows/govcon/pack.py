"""Echo GovCon pack — shared helpers for the GovCon automation recipes.

Every GovCon workflow follows the same approval-first shape:

    generate draft  →  queue_draft()  →  ContentItem(pending_review)
                                          + draft Approval (draft_created event)

Nothing publishes on its own. A human approves in the queue; a separate publish /
Sturgeon-handoff action ships it. These helpers keep that shape in one place and
degrade safely when live data providers (SAM.gov / USASpending / FEMA) or AI keys
are absent — so local build/test never needs real credentials.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from echo.config import DEFAULT_TENANT_ID
from echo.core.logger import get_logger
from echo.core.workflow import BaseWorkflow
from echo.modules import sturgeon
from echo.modules.approval import create_draft_approval
from echo.modules.content_store import build_utm_url, create_content_item

log = get_logger("echo.workflows.govcon")

GOVCON_CTA_URL = "https://www.govconcommandcenter.com"


class GovConWorkflow(BaseWorkflow):
    """Base for GovCon pack workflows — sets shared registry metadata."""

    product_area = "echo_govcon"
    approval_required = True
    required_tier = "free"


def run_ctx(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the run context injected by the runner (safe defaults for direct calls)."""
    return {
        "run_id": payload.get("_run_id"),
        "tenant_id": payload.get("_tenant_id") or DEFAULT_TENANT_ID,
        "user_id": payload.get("_user_id"),
    }


def sturgeon_cta() -> str:
    return sturgeon.cta_text()


def queue_draft(
    db: Session,
    *,
    workflow: str,
    draft_type: str,
    title: str,
    body: str,
    payload: dict[str, Any],
    topic: str | None = None,
    content_type: str | None = None,
    campaign: str | None = None,
    cta_text: str | None = None,
    cta_url: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a reviewable draft as a ContentItem + a draft Approval.

    Returns a dict with ``post_id`` and ``approval_id`` — the two handles callers
    surface in their WorkflowResult.
    """
    ctx = run_ctx(payload)
    brand = payload.get("brand") or None
    campaign = campaign or f"govcon_{draft_type}"
    utm = {"source": "govcon", "medium": "automation",
           "campaign": campaign, "content": workflow}
    cta_link = build_utm_url(cta_url or GOVCON_CTA_URL, **utm)

    item = create_content_item(
        db,
        workflow=workflow,
        platform="govcon",
        title=title[:200],
        caption=body,
        topic=topic,
        brand=brand,
        content_type=content_type or draft_type,
        cta_text=cta_text or "Open GovCon Command Center",
        cta_url=cta_link,
        utm=utm,
        status="pending_review",
    )

    approval = create_draft_approval(
        db,
        draft_type=draft_type,
        draft_content=body,
        requested_by=ctx["user_id"] or payload.get("requested_by", "echo_govcon"),
        run_id=ctx["run_id"],
        reason=f"Review {draft_type}: {title}"[:255],
        content_post_id=item.post_id,
        workflow_id=workflow,
        tenant_id=ctx["tenant_id"],
        metadata={"workflow_id": workflow, "title": title, **(extra_metadata or {})},
    )

    return {
        "post_id": item.post_id,
        "content_id": item.id,
        "approval_id": approval.id,
        "status": item.status,
        "draft_type": draft_type,
    }


# ── Safe data-provider wrappers ───────────────────────────────────────────────
# Each returns a plain list and never raises, so a provider outage or missing key
# degrades a brief to "no signals" instead of failing the workflow.


def safe_sam_opportunities(keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    from datetime import datetime, timedelta, timezone

    try:
        from echo.integrations import sam_gov

        now = datetime.now(timezone.utc)
        return sam_gov.search_opportunities(
            " ".join(keywords),
            limit=limit,
            posted_from=(now - timedelta(days=7)).strftime("%m/%d/%Y"),
            posted_to=now.strftime("%m/%d/%Y"),
        ) or []
    except Exception as exc:  # noqa: BLE001
        log.info("SAM.gov unavailable (%s) — brief continues without live opportunities", exc)
        return []


def safe_recent_awards(keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    try:
        from echo.integrations import usaspending

        res = usaspending.search_awards(keywords, limit=limit)
        return (res or {}).get("results", []) or []
    except Exception as exc:  # noqa: BLE001
        log.info("USASpending unavailable (%s) — brief continues without award data", exc)
        return []


def safe_fema_declarations(
    *, state: str | None = None, limit: int = 5, days_back: int = 14
) -> list[dict[str, Any]]:
    try:
        from echo.integrations.fema import get_disaster_declarations

        return get_disaster_declarations(state=state, limit=limit, days_back=days_back) or []
    except Exception as exc:  # noqa: BLE001
        log.info("FEMA unavailable (%s) — brief continues without disaster signals", exc)
        return []


#: Disaster sources folded into ``safe_disaster_declarations``. Each is an
#: ``echo.integrations`` module exposing ``get_disaster_declarations(...)`` with
#: the FEMA field shape. FEMA is always live; NRS/SEMA are provisioned adapters
#: that no-op (return ``[]``) until their ``*_API_URL`` env vars are set.
DISASTER_SOURCES: tuple[str, ...] = ("fema", "nrs", "sema")


def _declaration_key(rec: dict[str, Any]) -> tuple:
    """Dedup key across sources — same state + incident + number/title collide."""
    return (
        str(rec.get("state") or "").upper(),
        str(rec.get("incidentType") or "").lower(),
        str(rec.get("declarationNumber") or rec.get("declarationTitle") or "").lower(),
    )


def safe_disaster_declarations(
    *,
    state: str | None = None,
    limit: int = 5,
    days_back: int = 14,
    sources: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate disaster declarations across FEMA + NRS + SEMA, safely.

    Each source is queried independently; a source that errors or is
    unconfigured contributes nothing (never raises). Results are tagged with a
    ``source`` field, de-duplicated across feeds, and truncated to ``limit``.
    Back-compat: ``safe_fema_declarations`` remains FEMA-only.
    """
    from importlib import import_module

    merged: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for name in sources or DISASTER_SOURCES:
        try:
            mod = import_module(f"echo.integrations.{name}")
            records = mod.get_disaster_declarations(
                state=state, limit=limit, days_back=days_back
            ) or []
        except Exception as exc:  # noqa: BLE001
            log.info("%s disaster feed unavailable (%s) — skipping", name.upper(), exc)
            continue
        for rec in records:
            rec.setdefault("source", name)
            key = _declaration_key(rec)
            if key in seen:
                continue
            seen.add(key)
            merged.append(rec)
    return merged[:limit]
