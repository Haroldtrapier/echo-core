"""Connector execution abstraction (Phase 2).

A thin, uniform layer over the platform publishers in ``echo.modules.publisher``
so the approval→publish flow can target any channel through one interface, with
**dry-run as the default** and a mock connector that never sends anything.

Live sending is still governed globally by ``ECHO_ALLOW_LIVE_PUBLISH`` inside
``publisher.publish`` — this abstraction never bypasses that gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from echo.core.logger import get_logger
from echo.modules import publisher

log = get_logger("echo.modules.connectors")


@dataclass
class ConnectorResult:
    connector: str
    dry_run: bool
    success: bool
    live_url: str | None = None
    detail: dict[str, Any] | None = None
    error: str | None = None


class Connector(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def send(self, content: dict[str, Any], *, dry_run: bool = True) -> ConnectorResult: ...


class _PublisherConnector:
    """Wraps a publisher platform as a connector."""

    def __init__(self, name: str, platform: str) -> None:
        self.name = name
        self._platform = platform

    def is_configured(self) -> bool:
        # Configuration is provider-specific and checked at publish time; the
        # dry-run path always works, so we report True (the live gate still applies).
        return True

    def send(self, content: dict[str, Any], *, dry_run: bool = True) -> ConnectorResult:
        res = publisher.publish(self._platform, content, dry_run=dry_run)
        return ConnectorResult(
            connector=self.name,
            dry_run=res.dry_run,
            success=res.success,
            live_url=res.live_url,
            detail=res.simulated_output,
            error=res.error,
        )


class _NoopConnector:
    """Mock connector — always dry-run, never touches the network."""

    name = "noop"

    def is_configured(self) -> bool:
        return True

    def send(self, content: dict[str, Any], *, dry_run: bool = True) -> ConnectorResult:
        preview = str(content.get("caption", content.get("body", "")))[:200]
        return ConnectorResult(
            connector=self.name,
            dry_run=True,
            success=True,
            detail={"noop": True, "would_send": preview, "sent": False},
        )


# Registry: connector name → instance. Names mirror publisher platforms + 'noop'.
_REGISTRY: dict[str, Connector] = {
    "noop": _NoopConnector(),
    "linkedin": _PublisherConnector("linkedin", "linkedin"),
    "buffer": _PublisherConnector("buffer", "buffer"),
    "facebook": _PublisherConnector("facebook", "facebook"),
    "instagram": _PublisherConnector("instagram", "instagram"),
    "tiktok": _PublisherConnector("tiktok", "tiktok"),
    "email": _PublisherConnector("email", "email"),
    "slack": _PublisherConnector("slack", "slack"),
    "govcon_cms": _PublisherConnector("govcon_cms", "govcon_cms"),
}


def available_connectors() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_connector(name: str) -> Connector | None:
    return _REGISTRY.get(name)
