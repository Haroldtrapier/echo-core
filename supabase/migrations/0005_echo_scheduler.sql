-- Echo scheduler (Phase 2) — recurring workflow schedules.
-- Idempotent + additive: safe to run on a fresh or existing Echo database.
-- NOTE: apply only to a DEDICATED Echo Core database — never to shared/Sturgeon DBs.

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS echo_schedules (
    id                TEXT        PRIMARY KEY,
    name              TEXT        NOT NULL,
    workflow_slug     TEXT        NOT NULL,
    interval_minutes  INTEGER     NOT NULL DEFAULT 1440,
    payload           JSONB,
    enabled           BOOLEAN     NOT NULL DEFAULT false,   -- disabled by default
    tenant_id         TEXT        NOT NULL DEFAULT 'imani-internal',
    last_run_at       TIMESTAMPTZ,
    next_run_at       TIMESTAMPTZ,
    last_run_id       TEXT,
    run_count         INTEGER     NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_schedules_slug    ON echo_schedules (workflow_slug);
CREATE INDEX IF NOT EXISTS idx_echo_schedules_enabled ON echo_schedules (enabled);

DROP TRIGGER IF EXISTS trg_echo_schedules_updated_at ON echo_schedules;
CREATE TRIGGER trg_echo_schedules_updated_at
    BEFORE UPDATE ON echo_schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
