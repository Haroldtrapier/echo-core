"""Workflow registry — central store for all registered workflows."""
from __future__ import annotations

from typing import Type

from echo.core.logger import get_logger
from echo.core.workflow import BaseWorkflow

log = get_logger("echo.core.registry")

_REGISTRY: dict[str, Type[BaseWorkflow]] = {}


def register(cls: Type[BaseWorkflow]) -> Type[BaseWorkflow]:
    """Decorator to register a workflow class."""
    if not cls.slug:
        raise ValueError(f"Workflow {cls.__name__} must define a slug")
    _REGISTRY[cls.slug] = cls
    log.info("Registered workflow: %s (%s)", cls.slug, cls.name)
    return cls


def get_workflow(slug: str) -> Type[BaseWorkflow] | None:
    return _REGISTRY.get(slug)


def list_workflows() -> list[Type[BaseWorkflow]]:
    """Return all registered workflow classes."""
    return list(_REGISTRY.values())


def workflow_count() -> int:
    return len(_REGISTRY)


def workflow_metadata(cls: Type[BaseWorkflow]) -> dict:
    """Return the registry-table shape for a workflow class."""
    return {
        "workflow_id": cls.slug,
        "workflow_name": cls.name,
        "product_area": getattr(cls, "product_area", "echo_core"),
        "description": cls.description,
        "trigger_type": getattr(cls, "trigger_type", "manual"),
        "schedule_interval_seconds": getattr(cls, "schedule_interval_seconds", None),
        "input_schema": dict(getattr(cls, "input_schema", {}) or {}),
        "output_type": getattr(cls, "output_type", "none"),
        "approval_required": bool(getattr(cls, "approval_required", False)),
        "connector_targets": list(getattr(cls, "connector_targets", ()) or []),
        "required_tier": getattr(cls, "required_tier", "free"),
        "enabled": bool(getattr(cls, "enabled", True)),
        "webhook_enabled": bool(getattr(cls, "webhook_enabled", False)),
    }


def all_metadata() -> list[dict]:
    return [workflow_metadata(cls) for cls in list_workflows()]


def sync_registry(db) -> int:
    """Upsert the in-code registry into the ``echo_workflows`` table.

    Idempotent — safe to call on every startup. Returns the number of workflows
    synced. Failures are swallowed with a log so a registry-table hiccup never
    prevents the API from serving.
    """
    from echo.db import EchoWorkflow

    synced = 0
    try:
        for cls in list_workflows():
            meta = workflow_metadata(cls)
            row = db.query(EchoWorkflow).filter(
                EchoWorkflow.workflow_id == meta["workflow_id"]
            ).first()
            if row is None:
                row = EchoWorkflow(workflow_id=meta["workflow_id"])
                db.add(row)
            row.workflow_name = meta["workflow_name"]
            row.product_area = meta["product_area"]
            row.description = meta["description"]
            row.trigger_type = meta["trigger_type"]
            row.input_schema = meta["input_schema"]
            row.output_type = meta["output_type"]
            row.approval_required = meta["approval_required"]
            row.connector_targets = meta["connector_targets"]
            row.required_tier = meta["required_tier"]
            row.enabled = meta["enabled"]
            synced += 1
        db.commit()
        log.info("Synced %d workflows into echo_workflows", synced)
    except Exception as exc:  # noqa: BLE001
        log.warning("Registry sync skipped: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return synced
