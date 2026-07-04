"""Sturgeon handoff — bridge from Echo GovCon into Sturgeon AI.

A handoff carries a GovCon opportunity out of the education/discovery surface
(GovCon Command Center) into Sturgeon's proposal-execution workspace. We persist
a durable ``echo_sturgeon_handoffs`` row for every handoff, record a
``sturgeon_handoff_created`` analytics event, and — only when ``STURGEON_API_URL``
is configured — forward the payload to Sturgeon's intake endpoint.

Design goals:
    * Safe by default: with no Sturgeon URL configured, the handoff is stored
      locally (status=pending) and no network call is made — local build/test
      never needs a real Sturgeon.
    * Non-destructive: this only *creates* intake records. It never touches
      proposal credits, Stripe, or human-review purchase logic.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.config import (
    DEFAULT_TENANT_ID,
    STURGEON_API_KEY,
    STURGEON_API_URL,
    STURGEON_APP_URL,
)
from echo.core.logger import get_logger
from echo.db import EchoSturgeonHandoff
from echo.modules import events

log = get_logger("echo.modules.sturgeon")


def is_forwarding_enabled() -> bool:
    """True when a live Sturgeon intake endpoint is configured."""
    return bool(STURGEON_API_URL)


def cta_text(app_url: str | None = None) -> str:
    """Standard 'analyze in Sturgeon' call-to-action appended to GovCon drafts."""
    return (
        "→ Ready to bid? Send this opportunity to Sturgeon AI to run solicitation "
        f"analysis, compliance, and a proposal draft: {app_url or STURGEON_APP_URL}"
    )


def _forward_to_sturgeon(payload: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    """POST the handoff to Sturgeon. Returns (ok, sturgeon_ref, error)."""
    if not STURGEON_API_URL:
        return False, None, None  # forwarding disabled — caller stores locally
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if STURGEON_API_KEY:
            headers["Authorization"] = f"Bearer {STURGEON_API_KEY}"
        req = urllib.request.Request(
            STURGEON_API_URL.rstrip("/"), data=data, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
        ref = None
        try:
            parsed = json.loads(body)
            ref = parsed.get("id") or parsed.get("ref") or parsed.get("solicitation_id")
        except Exception:  # noqa: BLE001 — Sturgeon may return a bare id
            ref = body.strip()[:255] or None
        log.info("Sturgeon handoff forwarded ref=%s", ref)
        return True, ref, None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        log.warning("Sturgeon forward failed: %s", exc)
        return False, None, str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Sturgeon forward errored: %s", exc)
        return False, None, str(exc)


def create_handoff(
    db: Session,
    *,
    opportunity_title: str,
    agency: str | None = None,
    solicitation_number: str | None = None,
    due_date: str | None = None,
    source_url: str | None = None,
    summary: str | None = None,
    requirements: str | None = None,
    recommended_next_action: str | None = None,
    tenant_id: str | None = None,
    workflow_run_id: str | None = None,
    approval_id: str | None = None,
    created_by: str = "echo_govcon",
    extra: dict[str, Any] | None = None,
) -> EchoSturgeonHandoff:
    """Create (and optionally forward) a Sturgeon handoff record.

    Always persists a durable row and records a ``sturgeon_handoff_created``
    analytics event. If Sturgeon forwarding is configured, attempts the POST and
    records the outcome (forwarded / failed); otherwise leaves it ``pending``.
    """
    tenant_id = tenant_id or DEFAULT_TENANT_ID
    handoff = EchoSturgeonHandoff(
        tenant_id=tenant_id,
        workflow_run_id=workflow_run_id,
        approval_id=approval_id,
        created_by=created_by,
        opportunity_title=opportunity_title,
        agency=agency,
        solicitation_number=solicitation_number,
        due_date=due_date,
        source_url=source_url,
        summary=summary,
        requirements=requirements,
        recommended_next_action=recommended_next_action,
        status="pending",
        extra=extra or {},
    )
    db.add(handoff)
    db.commit()
    db.refresh(handoff)

    # Attempt live forward only when configured.
    if is_forwarding_enabled():
        ok, ref, err = _forward_to_sturgeon(handoff_dict(handoff))
        handoff.status = "forwarded" if ok else "failed"
        handoff.sturgeon_ref = ref
        handoff.forward_error = err
        handoff.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(handoff)

    events.record_event(
        db,
        events.EVENT_STURGEON_HANDOFF_CREATED,
        workflow_id=(extra or {}).get("workflow_id"),
        workflow_run_id=workflow_run_id,
        tenant_id=tenant_id,
        metadata={
            "handoff_id": handoff.id,
            "opportunity_title": opportunity_title,
            "agency": agency,
            "solicitation_number": solicitation_number,
            "status": handoff.status,
            "forwarded": handoff.status == "forwarded",
        },
    )
    return handoff


def handoff_dict(h: EchoSturgeonHandoff) -> dict[str, Any]:
    return {
        "id": h.id,
        "tenant_id": h.tenant_id,
        "workflow_run_id": h.workflow_run_id,
        "approval_id": h.approval_id,
        "created_by": h.created_by,
        "opportunity_title": h.opportunity_title,
        "agency": h.agency,
        "solicitation_number": h.solicitation_number,
        "due_date": h.due_date,
        "source_url": h.source_url,
        "summary": h.summary,
        "requirements": h.requirements,
        "recommended_next_action": h.recommended_next_action,
        "status": h.status,
        "sturgeon_ref": h.sturgeon_ref,
        "forward_error": h.forward_error,
        "extra": h.extra,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
    }
