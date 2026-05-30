-- Echo Core schema — workflow runs, approvals
-- Idempotent: safe to run on a fresh or existing database.
-- Run in Supabase SQL Editor or via `supabase db push`.

-- ─── Extensions ───────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Helper: updated_at trigger function ─────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ─── workflow_runs ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS workflow_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_slug   TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',
    triggered_by    TEXT,
    payload         JSONB,
    result          JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS triggered_by  TEXT,
    ADD COLUMN IF NOT EXISTS payload       JSONB,
    ADD COLUMN IF NOT EXISTS result        JSONB,
    ADD COLUMN IF NOT EXISTS error         TEXT,
    ADD COLUMN IF NOT EXISTS started_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at    TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_workflow_runs_slug    ON workflow_runs (workflow_slug);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_status  ON workflow_runs (status);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_created ON workflow_runs (created_at DESC);

DROP TRIGGER IF EXISTS trg_workflow_runs_updated_at ON workflow_runs;
CREATE TRIGGER trg_workflow_runs_updated_at
    BEFORE UPDATE ON workflow_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── approvals ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS approvals (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID        REFERENCES workflow_runs(id) ON DELETE SET NULL,
    requested_by    TEXT        NOT NULL,
    reason          TEXT,
    status          TEXT        NOT NULL DEFAULT 'pending',
    decision_by     TEXT,
    decision_note   TEXT,
    resume_payload  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS decision_by    TEXT,
    ADD COLUMN IF NOT EXISTS decision_note  TEXT,
    ADD COLUMN IF NOT EXISTS resume_payload JSONB,
    ADD COLUMN IF NOT EXISTS updated_at     TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_approvals_status     ON approvals (status);
CREATE INDEX IF NOT EXISTS idx_approvals_run_id     ON approvals (run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_created    ON approvals (created_at);

DROP TRIGGER IF EXISTS trg_approvals_updated_at ON approvals;
CREATE TRIGGER trg_approvals_updated_at
    BEFORE UPDATE ON approvals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
