"""Smoke-test fixtures.

Sets a throwaway SQLite database and a known API key *before* any ``echo``
module is imported (echo.config reads the environment at import time), then
exposes an authenticated FastAPI TestClient. No Postgres / Railway / live API
credentials are required — publishing stays in dry-run because
ECHO_ALLOW_LIVE_PUBLISH is never set.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure the repo root is importable when CI runs bare `pytest` (no `python -m`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must run before importing echo.config (import-time env reads).
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="echo_smoke_"), "smoke.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ECHO_API_KEY"] = "smoke-test-key"
os.environ.pop("ECHO_ALLOW_LIVE_PUBLISH", None)  # stay in dry-run

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from echo.db import create_tables  # noqa: E402
from echo.main import app  # noqa: E402

API_KEY = os.environ["ECHO_API_KEY"]


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    create_tables()
    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def auth() -> dict[str, str]:
    return {"x-echo-key": API_KEY}
