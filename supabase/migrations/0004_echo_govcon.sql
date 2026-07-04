-- Echo GovCon schema — analytics events, Sturgeon handoffs, workflow registry,
-- and approval-draft + workflow-run extensions.
-- Idempotent: safe to run on a fresh or existing database.
-- Run in Supabase SQL Editor or via `supabase db push`.
--
-- IDs are TEXT to match the application ORM (echo.db uses 16/32-char hex ids),
-- so schema created here is compatible with SQLAlchemy create_all().

-- ─── Helper (defined in 0001, re-declared defensively) ───────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ─── approvals: approval-first draft columns ─────────────────────────────────

ALTER TABLE IF EXISTS approvals
    ADD COLUMN IF NOT EXISTS draft_type       TEXT,
    ADD COLUMN IF NOT EXISTS draft_content    TEXT,
    ADD COLUMN IF NOT EXISTS content_post_id  TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_by      TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at      TIMESTAMPTZ;

-- ─── workflow_runs: tenancy, retry engine, completion ────────────────────────

ALTER TABLE IF EXISTS workflow_runs
    ADD COLUMN IF NOT EXISTS tenant_id     TEXT,
    ADD COLUMN IF NOT EXISTS user_id       TEXT,
    ADD COLUMN IF NOT EXISTS retry_count   INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_retries   INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS completed_at  TIMESTAMPTZ;

-- ─── echo_workflows — durable mirror of the in-code registry ─────────────────

CREATE TABLE IF NOT EXISTS echo_workflows (
    workflow_id        TEXT        PRIMARY KEY,
    workflow_name      TEXT        NOT NULL,
    product_area       TEXT        NOT NULL DEFAULT 'echo_core',
    description        TEXT,
    trigger_type       TEXT        NOT NULL DEFAULT 'manual',
    input_schema       JSONB,
    output_type        TEXT,
    approval_required   BOOLEAN     NOT NULL DEFAULT false,
    connector_targets   JSONB,
    required_tier      TEXT        NOT NULL DEFAULT 'free',
    enabled            BOOLEAN     NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_workflows_product_area ON echo_workflows (product_area);
CREATE INDEX IF NOT EXISTS idx_echo_workflows_enabled      ON echo_workflows (enabled);

DROP TRIGGER IF EXISTS trg_echo_workflows_updated_at ON echo_workflows;
CREATE TRIGGER trg_echo_workflows_updated_at
    BEFORE UPDATE ON echo_workflows
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── echo_analytics_events — append-only Echo event stream ───────────────────

CREATE TABLE IF NOT EXISTS echo_analytics_events (
    id                TEXT        PRIMARY KEY,
    event_type        TEXT        NOT NULL,
    workflow_id       TEXT,
    workflow_run_id   TEXT,
    user_id           TEXT,
    tenant_id         TEXT,
    event_metadata    JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_events_type    ON echo_analytics_events (event_type);
CREATE INDEX IF NOT EXISTS idx_echo_events_wf      ON echo_analytics_events (workflow_id);
CREATE INDEX IF NOT EXISTS idx_echo_events_run     ON echo_analytics_events (workflow_run_id);
CREATE INDEX IF NOT EXISTS idx_echo_events_tenant  ON echo_analytics_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_echo_events_created ON echo_analytics_events (created_at DESC);

-- ─── echo_sturgeon_handoffs — GovCon → Sturgeon intake records ───────────────

CREATE TABLE IF NOT EXISTS echo_sturgeon_handoffs (
    id                       TEXT        PRIMARY KEY,
    tenant_id                TEXT        NOT NULL DEFAULT 'imani-internal',
    workflow_run_id          TEXT,
    approval_id              TEXT,
    created_by               TEXT        NOT NULL DEFAULT 'echo_govcon',
    opportunity_title        TEXT        NOT NULL,
    agency                   TEXT,
    solicitation_number      TEXT,
    due_date                 TEXT,
    source_url               TEXT,
    summary                  TEXT,
    requirements             TEXT,
    recommended_next_action  TEXT,
    status                   TEXT        NOT NULL DEFAULT 'pending',
    sturgeon_ref             TEXT,
    forward_error            TEXT,
    extra                    JSONB,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_handoffs_tenant ON echo_sturgeon_handoffs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_echo_handoffs_status ON echo_sturgeon_handoffs (status);

DROP TRIGGER IF EXISTS trg_echo_handoffs_updated_at ON echo_sturgeon_handoffs;
CREATE TRIGGER trg_echo_handoffs_updated_at
    BEFORE UPDATE ON echo_sturgeon_handoffs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
