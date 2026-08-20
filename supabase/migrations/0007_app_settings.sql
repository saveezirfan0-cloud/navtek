-- Navtek eOrder → monday automation
-- 0007_app_settings.sql — one row per setting, edited from the app itself.
--
-- Safe to run more than once. Run it after 0006_webhook_dedup.sql.
--
-- Why a table and not environment variables: the notification recipients are
-- operational data the admins change from /settings, not deploy-time
-- configuration — "add Sarah to the failure emails" must not require a Vercel
-- redeploy. Secrets stay in the environment; only non-secret, admin-editable
-- values live here.

create table if not exists app_settings (
  key        text primary key,
  value      jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  updated_by text
);

alter table app_settings enable row level security;
-- No policies on purpose: the browser never talks to Supabase directly.
grant all privileges on table app_settings to service_role;
