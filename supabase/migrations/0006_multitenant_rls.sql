-- Echo Core migration 0006 — multi-tenant Row-Level Security (opt-in switch).
--
-- Echo is single-tenant-by-default (config.DEFAULT_TENANT_ID). This migration
-- installs the RLS machinery but DOES NOT enable it on migrate — applying 0006 is
-- a no-op for every existing deployment. Enabling is a deliberate, reversible
-- operator action:
--
--     SELECT echo_enable_rls();     -- turn tenant isolation ON  (idempotent)
--     SELECT echo_disable_rls();    -- turn it OFF               (idempotent)
--
-- Tenant scoping is driven by a per-session GUC, set by the application when
-- ECHO_RLS_ENABLED=true (see echo.db.apply_session_tenant):
--
--     SET LOCAL app.current_tenant = '<tenant-id>';
--
-- Safety model:
--   * The app provisions its schema via create_all(), so it connects as the
--     table OWNER, which bypasses RLS regardless — enabling RLS cannot lock the
--     standard deployment out of its own tables.
--   * For non-owner roles (e.g. a Supabase anon/authenticated role, or a
--     least-privilege app role), the policy isolates by tenant: a row is visible
--     when its tenant_id matches app.current_tenant, OR when tenant_id IS NULL
--     (unassigned / shared / legacy single-tenant data) — so a caller that has
--     set its tenant is never locked out of default rows, and un-scoped callers
--     see only shared rows, never another tenant's tagged data.
--
-- The function is catalog-driven: it applies to every public table that has a
-- tenant_id column, including tables added by future migrations.

CREATE OR REPLACE FUNCTION echo_enable_rls() RETURNS void
LANGUAGE plpgsql AS $fn$
DECLARE
    t RECORD;
    n INT := 0;
BEGIN
    FOR t IN
        SELECT c.relname AS tbl
          FROM pg_class c
          JOIN pg_namespace ns ON ns.oid = c.relnamespace
          JOIN information_schema.columns col
            ON col.table_schema = 'public'
           AND col.table_name = c.relname
           AND col.column_name = 'tenant_id'
         WHERE ns.nspname = 'public'
           AND c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tbl);
        EXECUTE format('DROP POLICY IF EXISTS echo_tenant_isolation ON public.%I', t.tbl);
        EXECUTE format($p$
            CREATE POLICY echo_tenant_isolation ON public.%I
                USING (
                    tenant_id IS NULL
                    OR tenant_id = current_setting('app.current_tenant', true)
                )
                WITH CHECK (
                    tenant_id IS NULL
                    OR tenant_id = current_setting('app.current_tenant', true)
                )
        $p$, t.tbl);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'echo_enable_rls: tenant isolation enabled on % table(s)', n;
END;
$fn$;

CREATE OR REPLACE FUNCTION echo_disable_rls() RETURNS void
LANGUAGE plpgsql AS $fn$
DECLARE
    t RECORD;
    n INT := 0;
BEGIN
    FOR t IN
        SELECT c.relname AS tbl
          FROM pg_class c
          JOIN pg_namespace ns ON ns.oid = c.relnamespace
          JOIN information_schema.columns col
            ON col.table_schema = 'public'
           AND col.table_name = c.relname
           AND col.column_name = 'tenant_id'
         WHERE ns.nspname = 'public'
           AND c.relkind = 'r'
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS echo_tenant_isolation ON public.%I', t.tbl);
        EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t.tbl);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'echo_disable_rls: tenant isolation disabled on % table(s)', n;
END;
$fn$;

-- Intentionally NOT called here — enabling is an explicit operator action.
-- To turn tenant isolation on now:   SELECT echo_enable_rls();
