-- F-1 · Enable Row-Level Security on the five public tables that had none.
--
-- Tables: workflow_runs, approvals, echo_workflows, echo_analytics_events,
--         echo_sturgeon_handoffs
--
-- ---------------------------------------------------------------------------
-- SEVERITY CORRECTION (verified 2026-08-19, do not re-derive)
-- ---------------------------------------------------------------------------
-- The Supabase security advisor reports these as "fully exposed to the anon
-- and authenticated roles". For THESE five tables that is not accurate, and
-- the difference matters for how the fix is written.
--
-- Verified against the live catalog:
--
--   relacl IS NULL on all five  -> no privileges granted to anyone but the owner
--   has_table_privilege('anon',          <tbl>, 'SELECT') = false
--   has_table_privilege('authenticated', <tbl>, 'SELECT') = false
--   has_table_privilege('service_role',  <tbl>, 'SELECT') = false
--   relowner = postgres, relforcerowsecurity = false
--
-- Compare public.govcon_saved_opportunities, which DOES carry grants:
--   {postgres=arwdDxtm/postgres, authenticated=arwd/postgres, service_role=arwd/postgres}
--
-- The advisor's wording assumes Supabase's default GRANTs to anon/authenticated.
-- Those grants were never applied here, because Echo Core provisions its own
-- schema over a direct DATABASE_URL connection (SQLAlchemy create_all) rather
-- than through the Supabase REST layer. PostgREST would refuse these tables on
-- privilege grounds before RLS was ever consulted.
--
-- So this is defence in depth, not an open door. It is still worth doing:
-- the moment anyone runs GRANT ... TO authenticated on one of these tables,
-- the absence of RLS becomes a live cross-tenant leak with no backstop. That
-- is not hypothetical -- Govcon migration 0014_grant_missing_table_privileges
-- did exactly that to four govcon_* tables to clear a "permission denied"
-- error. RLS first means the next such grant fails safe.

-- ---------------------------------------------------------------------------
-- WHY NO POLICIES ARE ADDED
-- ---------------------------------------------------------------------------
-- Echo Core connects as the table OWNER, and an owner bypasses RLS unless
-- FORCE ROW LEVEL SECURITY is set (it is not, and this migration does not set
-- it). echo/config.py:93 states the same safety model, and migration 0006's
-- header documents it. So enabling RLS here cannot lock Echo Core out of its
-- own tables.
--
-- No permissive policy is created, because no non-owner role holds a grant on
-- these tables. A service_role policy would be inert -- service_role cannot
-- reach the table at all -- and adding one would misrepresent the access model
-- to the next reader. Deny-by-default is the honest and tightest state, and it
-- matches the pattern already used and documented elsewhere in this database
-- (sema_nrs_subscribers, webinar_registrations, intelligence_brief_subscribers:
-- "RLS on, no policies = service-role only").
--
-- This composes with 0006 rather than competing with it. echo_enable_rls()
-- targets tables carrying a tenant_id column -- which covers workflow_runs,
-- echo_analytics_events and echo_sturgeon_handoffs, but NOT approvals or
-- echo_workflows, neither of which has that column. Running echo_enable_rls()
-- after this migration is still safe and simply layers tenant policies on top.
--
-- Forward-only and idempotent: ENABLE ROW LEVEL SECURITY is a no-op when RLS
-- is already on.

ALTER TABLE public.workflow_runs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.approvals               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.echo_workflows          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.echo_analytics_events   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.echo_sturgeon_handoffs  ENABLE ROW LEVEL SECURITY;
