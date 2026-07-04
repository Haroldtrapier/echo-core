"""Echo Core — FastAPI application entry point.

Start with:
    uvicorn echo.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from echo.config import CORS_ORIGINS, ECHO_ENABLED
from echo.core.logger import get_logger

# Import workflows to trigger registration
import echo.workflows  # noqa: F401

log = get_logger("echo.main")

app = FastAPI(
    title="Echo Core",
    description="GovCon automation backend — workflow engine, publishing gate, and analytics API.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
origins = CORS_ORIGINS if CORS_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    log.info("Echo Core starting up — ECHO_ENABLED=%s", ECHO_ENABLED)
    from echo.db import create_tables
    try:
        create_tables()
        log.info("Database tables verified/created")
    except Exception as exc:  # noqa: BLE001
        log.warning("DB not reachable at startup (will retry on first request): %s", exc)
    from echo.core.registry import sync_registry, workflow_count
    log.info("Registered workflows: %d", workflow_count())
    # Mirror the in-code registry into the echo_workflows table (best-effort),
    # and seed the default (disabled) recurring schedules.
    try:
        from echo.db import db_session
        from echo.scheduling import sync_default_schedules
        with db_session() as db:
            sync_registry(db)
            sync_default_schedules(db)
    except Exception as exc:  # noqa: BLE001
        log.warning("Registry/schedule sync skipped at startup: %s", exc)


@app.on_event("shutdown")
async def shutdown() -> None:
    log.info("Echo Core shutting down")


# Mount the API router
from echo.api.routes import router  # noqa: E402
app.include_router(router, prefix="/api/v1")


# Root redirect to docs
@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"message": "Echo Core API", "docs": "/docs", "health": "/api/v1/health"}
