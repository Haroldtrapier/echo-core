-- Echo Core migration 0005 — reconcile id column types with the ORM.
--
-- Background: 0001–0003 created primary keys and id references (workflow_runs.id,
-- approvals.id/run_id, content_items.id, publishing_jobs.id, automation_logs.id,
-- integration_health.id, echo_jobs.*, echo_job_schedules.*, echo_execution_audits.*)
-- as UUID with gen_random_uuid() defaults. The runtime ORM (echo.db) uses 32-char
-- hex string ids (VARCHAR(32)) for ALL of these. On a fresh DB the app provisions
-- its own schema via SQLAlchemy create_all() (TEXT ids), so this drift only bites
-- environments that apply the hand-written SQL migrations standalone: there,
-- inserting an ORM-generated hex id into a UUID column fails.
--
-- This migration converts every UUID column in the public schema to TEXT so the
-- SQL-provisioned schema matches the ORM. It is:
--   * generic     — discovers columns and constraints from the catalog, so it
--                   also covers any id column added by a future migration.
--   * idempotent  — a no-op once every id column is TEXT; safe to re-run.
--   * non-lossy   — existing UUID values cast cleanly to their canonical text.
--   * FK-safe     — captures every foreign key verbatim (preserving ON DELETE /
--                   ON UPDATE), drops them so columns can be retyped, then
--                   recreates them against the converted columns.
--
-- Run in order after 0001–0004 (Supabase SQL Editor or `supabase db push`).

-- 0004 created SELECT * compatibility views over workflow_runs / approvals; a
-- dependent view blocks ALTER COLUMN ... TYPE. Drop them here and recreate
-- identically at the end (they carry no data of their own).
DROP VIEW IF EXISTS echo_workflow_runs;
DROP VIEW IF EXISTS echo_approvals;

DO $$
DECLARE
    fk       RECORD;
    col      RECORD;
    fk_defs  TEXT[] := ARRAY[]::TEXT[];
    d        TEXT;
BEGIN
    -- Nothing to do if no UUID columns remain (e.g. a create_all()-only DB, or a
    -- second run of this migration).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND data_type = 'uuid'
    ) THEN
        RAISE NOTICE '0005: no uuid columns in public schema — nothing to reconcile';
        RETURN;
    END IF;

    -- 1) Capture + drop every foreign key in the public schema. Recreating them
    --    verbatim afterwards preserves referential actions exactly; dropping them
    --    all up front means column retyping never trips an FK type dependency,
    --    regardless of drop/convert order.
    FOR fk IN
        SELECT c.conname,
               c.conrelid::regclass::text AS tbl,
               pg_get_constraintdef(c.oid) AS def
          FROM pg_constraint c
         WHERE c.contype = 'f'
           AND c.connamespace = 'public'::regnamespace
    LOOP
        fk_defs := array_append(
            fk_defs,
            format('ALTER TABLE %s ADD CONSTRAINT %I %s', fk.tbl, fk.conname, fk.def)
        );
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', fk.tbl, fk.conname);
    END LOOP;

    -- 2) Convert every UUID column to TEXT. Drop any UUID default first; restore a
    --    hex default on primary-key `id` columns so direct SQL inserts still get an
    --    id in the ORM's 32-char hex style. Reference columns (run_id, *_id) keep
    --    no default — the app always supplies them.
    FOR col IN
        SELECT table_name,
               column_name,
               (column_default IS NOT NULL) AS has_default,
               (column_name = 'id')         AS is_pk_id
          FROM information_schema.columns
         WHERE table_schema = 'public' AND data_type = 'uuid'
         ORDER BY table_name, column_name
    LOOP
        IF col.has_default THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I DROP DEFAULT',
                           col.table_name, col.column_name);
        END IF;
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE TEXT USING %I::text',
                       col.table_name, col.column_name, col.column_name);
        IF col.is_pk_id THEN
            EXECUTE format(
                'ALTER TABLE %I ALTER COLUMN %I SET DEFAULT replace(gen_random_uuid()::text, ''-'', '''')',
                col.table_name, col.column_name);
        END IF;
    END LOOP;

    -- 3) Recreate every foreign key against the now-TEXT columns.
    FOREACH d IN ARRAY fk_defs LOOP
        EXECUTE d;
    END LOOP;

    RAISE NOTICE '0005: reconciled uuid ids to text; recreated % foreign key(s)',
                 coalesce(array_length(fk_defs, 1), 0);
END $$;

-- Recreate the spec-name compatibility views dropped above (mirrors 0004).
DO $$
BEGIN
  IF to_regclass('public.workflow_runs') IS NOT NULL THEN
    EXECUTE 'CREATE OR REPLACE VIEW echo_workflow_runs AS SELECT * FROM workflow_runs';
  END IF;
  IF to_regclass('public.approvals') IS NOT NULL THEN
    EXECUTE 'CREATE OR REPLACE VIEW echo_approvals AS SELECT * FROM approvals';
  END IF;
END $$;

-- ─── Optional: multi-tenant Row-Level Security (opt-in) ──────────────────────
--
-- Echo is single-tenant-by-default (config.DEFAULT_TENANT_ID). Tenant columns
-- exist on the Echo tables, but RLS is intentionally left DISABLED to match the
-- rest of the migrations and because the app connects with a privileged role.
-- When you move to true multi-tenant isolation, enable RLS per tenant table and
-- scope reads/writes to a request-scoped tenant id. Example scaffold (review and
-- adapt the role/claim model to your deployment before enabling — an incorrect
-- policy can lock the application out of its own tables):
--
--   ALTER TABLE echo_analytics_events   ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE echo_sturgeon_handoffs  ENABLE ROW LEVEL SECURITY;
--
--   -- Let the app's service role bypass RLS (Supabase service_role already does).
--   CREATE POLICY tenant_service_all ON echo_analytics_events
--       USING (current_setting('role', true) = 'service_role')
--       WITH CHECK (current_setting('role', true) = 'service_role');
--
--   -- Scope everyone else to the request's tenant (set via SET app.tenant_id).
--   CREATE POLICY tenant_isolation ON echo_analytics_events
--       USING (tenant_id = current_setting('app.tenant_id', true))
--       WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--
-- Repeat per tenant-scoped table. Left commented so this migration stays a
-- safe, application-compatible no-op for RLS until multi-tenancy is turned on.
