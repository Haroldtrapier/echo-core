"""Row-Level Security app-side wiring — safe-by-default behavior.

The end-to-end tenant-isolation guarantees (migration 0006 + policies) are proven
against a real Postgres backend; this hermetic suite runs on SQLite, so here we
assert the *application* side is a safe no-op unless explicitly enabled on
Postgres — i.e. enabling the RLS machinery never breaks the default deployment or
the dev/test path.
"""
from __future__ import annotations

from echo import db as dbmod
from echo.db import apply_session_tenant, db_session


def test_apply_session_tenant_noop_on_sqlite(_init_db):
    """On the SQLite test backend the GUC helper must never raise or emit SQL."""
    assert dbmod._IS_POSTGRES is False
    with db_session() as db:
        # Should be a no-op regardless of the flag, because the backend isn't PG.
        apply_session_tenant(db, "tenantA")
        apply_session_tenant(db)  # default tenant
        # Session is still fully usable afterwards.
        db.execute(dbmod.text("SELECT 1"))


def test_session_factories_still_yield_usable_sessions(_init_db):
    """db_session() wiring (apply/clear tenant) leaves a working session."""
    with db_session() as db:
        row = db.execute(dbmod.text("SELECT 1")).scalar()
        assert row == 1


def test_rls_flag_defaults_off():
    """RLS stays opt-in: the default config leaves the app path disabled."""
    # ECHO_RLS_ENABLED is read at import; the hermetic env never sets it.
    from echo.config import ECHO_RLS_ENABLED

    assert ECHO_RLS_ENABLED is False
