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
