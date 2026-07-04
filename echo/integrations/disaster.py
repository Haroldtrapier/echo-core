"""Unified disaster-procurement signal aggregator (Phase 2).

Combines the live FEMA adapter with the NRS/SEMA stubs behind one call, so a
workflow can ask for "all disaster procurement signals" without knowing which
providers are configured. Every provider degrades to an empty list safely, so
this never raises and never requires credentials.
"""
from __future__ import annotations

from typing import Any

from echo.core.logger import get_logger
from echo.integrations import nrs, sema

log = get_logger("echo.integrations.disaster")


def provider_status() -> dict[str, Any]:
    """Report which providers are live vs mock vs disabled."""
    from echo.config import NRS_USE_MOCK, SEMA_USE_MOCK

    def _state(configured: bool, mock: bool) -> str:
        return "live" if configured else ("mock" if mock else "disabled")

    return {
        "fema": "live",  # FEMA OpenFEMA needs no key
        "nrs": _state(nrs.is_configured(), NRS_USE_MOCK),
        "sema": _state(sema.is_configured(), SEMA_USE_MOCK),
    }


def get_all_signals(*, state: str | None = None, limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    """Return signals grouped by provider (each safe/empty when unavailable)."""
    out: dict[str, list[dict[str, Any]]] = {"fema": [], "nrs": [], "sema": []}
    try:
        from echo.integrations.fema import get_disaster_declarations

        out["fema"] = get_disaster_declarations(state=state, limit=limit, days_back=14) or []
    except Exception as exc:  # noqa: BLE001
        log.info("FEMA unavailable (%s)", exc)
    out["nrs"] = nrs.get_procurement_signals(state=state, limit=limit)
    out["sema"] = sema.get_procurement_signals(state=state, limit=limit)
    return out
