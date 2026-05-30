-- Echo Cockpit: job control-panel tables
-- echo_jobs, echo_job_schedules, echo_execution_audits
-- Idempotent — safe to re-run on an existing database.

-- ─── echo_jobs ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS echo_jobs (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        TEXT        NOT NULL DEFAULT 'imani-internal',
    created_by       TEXT        NOT NULL DEFAULT 'apex-operator',
    title            TEXT        NOT NULL,
    channel          TEXT        NOT NULL DEFAULT 'linkedin',
    body             TEXT        NOT NULL,
    subject          TEXT,
    job_metadata     JSONB,
    status           TEXT        NOT NULL DEFAULT 'draft',
    approval_id      UUID,
    dry_run_result   JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE echo_jobs
    ADD COLUMN IF NOT EXISTS tenant_id       TEXT        NOT NULL DEFAULT 'imani-internal',
    ADD COLUMN IF NOT EXISTS created_by      TEXT        NOT NULL DEFAULT 'apex-operator',
    ADD COLUMN IF NOT EXISTS subject         TEXT,
    ADD COLUMN IF NOT EXISTS job_metadata    JSONB,
    ADD COLUMN IF NOT EXISTS approval_id     UUID,
    ADD COLUMN IF NOT EXISTS dry_run_result  JSONB;

CREATE INDEX IF NOT EXISTS idx_echo_jobs_tenant   ON echo_jobs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_echo_jobs_status   ON echo_jobs (status);
CREATE INDEX IF NOT EXISTS idx_echo_jobs_channel  ON echo_jobs (channel);
CREATE INDEX IF NOT EXISTS idx_echo_jobs_created  ON echo_jobs (created_at DESC);

DROP TRIGGER IF EXISTS trg_echo_jobs_updated_at ON echo_jobs;
CREATE TRIGGER trg_echo_jobs_updated_at
    BEFORE UPDATE ON echo_jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── echo_job_schedules ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS echo_job_schedules (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL DEFAULT 'imani-internal',
    echo_job_id     UUID        NOT NULL REFERENCES echo_jobs(id) ON DELETE CASCADE,
    created_by      TEXT        NOT NULL DEFAULT 'apex-operator',
    scheduled_for   TIMESTAMPTZ NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',
    run_count       INTEGER     NOT NULL DEFAULT 0,
    last_run_at     TIMESTAMPTZ,
    last_result     JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE echo_job_schedules
    ADD COLUMN IF NOT EXISTS tenant_id    TEXT        NOT NULL DEFAULT 'imani-internal',
    ADD COLUMN IF NOT EXISTS created_by   TEXT        NOT NULL DEFAULT 'apex-operator',
    ADD COLUMN IF NOT EXISTS last_result  JSONB,
    ADD COLUMN IF NOT EXISTS error        TEXT;

CREATE INDEX IF NOT EXISTS idx_echo_schedules_job      ON echo_job_schedules (echo_job_id);
CREATE INDEX IF NOT EXISTS idx_echo_schedules_status   ON echo_job_schedules (status);
CREATE INDEX IF NOT EXISTS idx_echo_schedules_due      ON echo_job_schedules (scheduled_for) WHERE status = 'pending';

DROP TRIGGER IF EXISTS trg_echo_schedules_updated_at ON echo_job_schedules;
CREATE TRIGGER trg_echo_schedules_updated_at
    BEFORE UPDATE ON echo_job_schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── echo_execution_audits ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS echo_execution_audits (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             TEXT        NOT NULL DEFAULT 'imani-internal',
    echo_job_id           UUID        NOT NULL REFERENCES echo_jobs(id) ON DELETE CASCADE,
    approval_id           UUID,
    workflow_run_id       UUID,
    attempted_by          TEXT        NOT NULL DEFAULT 'apex-operator',
    action                TEXT        NOT NULL DEFAULT 'execute',
    result                TEXT        NOT NULL,
    approval_status       TEXT,
    live_publish_enabled  BOOLEAN     NOT NULL DEFAULT FALSE,
    reason                TEXT,
    request_metadata      JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_echo_audits_job      ON echo_execution_audits (echo_job_id);
CREATE INDEX IF NOT EXISTS idx_echo_audits_tenant   ON echo_execution_audits (tenant_id);
CREATE INDEX IF NOT EXISTS idx_echo_audits_result   ON echo_execution_audits (result);
CREATE INDEX IF NOT EXISTS idx_echo_audits_created  ON echo_execution_audits (created_at DESC);
