-- Echo Cockpit read-model tables
-- Used by: GET /content, GET /publishing-jobs, GET /logs, GET /integration-health
-- Idempotent: safe to run on an existing database.

-- ─── Helper: set_updated_at (idempotent) ─────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ─── content_items ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS content_items (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title            TEXT,
    body             TEXT,
    platform         TEXT,
    status           TEXT        NOT NULL DEFAULT 'draft',
    published        BOOLEAN     NOT NULL DEFAULT FALSE,
    workflow_run_id  UUID        REFERENCES workflow_runs(id) ON DELETE SET NULL,
    metadata         JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE content_items
    ADD COLUMN IF NOT EXISTS title            TEXT,
    ADD COLUMN IF NOT EXISTS body             TEXT,
    ADD COLUMN IF NOT EXISTS platform         TEXT,
    ADD COLUMN IF NOT EXISTS status           TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS published        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS workflow_run_id  UUID REFERENCES workflow_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata         JSONB,
    ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_content_items_status     ON content_items (status);
CREATE INDEX IF NOT EXISTS idx_content_items_published  ON content_items (published);
CREATE INDEX IF NOT EXISTS idx_content_items_platform   ON content_items (platform);
CREATE INDEX IF NOT EXISTS idx_content_items_created    ON content_items (created_at DESC);

DROP TRIGGER IF EXISTS trg_content_items_updated_at ON content_items;
CREATE TRIGGER trg_content_items_updated_at
    BEFORE UPDATE ON content_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── publishing_jobs ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS publishing_jobs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    platform         TEXT        NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'pending',
    dry_run          BOOLEAN     NOT NULL DEFAULT TRUE,
    content          JSONB,
    live_url         TEXT,
    error            TEXT,
    workflow_run_id  UUID        REFERENCES workflow_runs(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE publishing_jobs
    ADD COLUMN IF NOT EXISTS dry_run          BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS content          JSONB,
    ADD COLUMN IF NOT EXISTS live_url         TEXT,
    ADD COLUMN IF NOT EXISTS error            TEXT,
    ADD COLUMN IF NOT EXISTS workflow_run_id  UUID REFERENCES workflow_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_publishing_jobs_status    ON publishing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_publishing_jobs_platform  ON publishing_jobs (platform);
CREATE INDEX IF NOT EXISTS idx_publishing_jobs_created   ON publishing_jobs (created_at DESC);

DROP TRIGGER IF EXISTS trg_publishing_jobs_updated_at ON publishing_jobs;
CREATE TRIGGER trg_publishing_jobs_updated_at
    BEFORE UPDATE ON publishing_jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── automation_logs ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS automation_logs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    level            TEXT        NOT NULL DEFAULT 'info',
    message          TEXT        NOT NULL,
    source           TEXT,
    workflow_run_id  UUID        REFERENCES workflow_runs(id) ON DELETE SET NULL,
    metadata         JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE automation_logs
    ADD COLUMN IF NOT EXISTS source           TEXT,
    ADD COLUMN IF NOT EXISTS workflow_run_id  UUID REFERENCES workflow_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata         JSONB;

CREATE INDEX IF NOT EXISTS idx_automation_logs_level      ON automation_logs (level);
CREATE INDEX IF NOT EXISTS idx_automation_logs_run_id     ON automation_logs (workflow_run_id);
CREATE INDEX IF NOT EXISTS idx_automation_logs_created    ON automation_logs (created_at DESC);

-- ─── integration_health ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS integration_health (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_name  TEXT        NOT NULL,
    status            TEXT        NOT NULL DEFAULT 'unknown',
    details           JSONB,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE integration_health
    ADD COLUMN IF NOT EXISTS details    JSONB,
    ADD COLUMN IF NOT EXISTS checked_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_integration_health_name
    ON integration_health (integration_name);
CREATE INDEX IF NOT EXISTS idx_integration_health_status
    ON integration_health (status);
CREATE INDEX IF NOT EXISTS idx_integration_health_checked
    ON integration_health (checked_at DESC);
