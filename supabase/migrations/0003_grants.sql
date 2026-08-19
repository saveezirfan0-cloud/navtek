-- Navtek eOrder → monday automation
-- 0003_grants.sql — restore the service role's access to the app's tables.
--
-- Safe to run more than once, same as 0001 and 0002.
--
-- Why this exists: production health showed
--
--     "supabase_said": "permission denied for table eorder_ingests"
--
-- with a valid service_role key from the right project. "Permission denied"
-- is a Postgres error, not an auth error — the key was ACCEPTED, and then the
-- service_role role was refused table access because it holds no GRANTs on
-- these tables. On a standard Supabase project service_role is granted
-- everything in schema public automatically via default privileges; on this
-- project those grants were missing, and every key of every generation fails
-- identically until they are restored, which looks exactly like a wrong key.
--
-- This grants only to service_role. anon and authenticated stay locked out on
-- purpose: RLS is enabled with no policies (0001, 0002) and the browser never
-- talks to Supabase directly — everything goes through the parser service,
-- which holds the secret key.

grant usage on schema public to service_role;

grant all privileges on all tables    in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

-- And keep it true for tables created by future migrations.
alter default privileges in schema public grant all on tables    to service_role;
alter default privileges in schema public grant all on sequences to service_role;
