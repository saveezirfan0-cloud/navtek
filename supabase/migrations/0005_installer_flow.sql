-- Navtek eOrder → monday automation
-- 0005_installer_flow.sql — the installer workflow: SMS dedupe and SLA state.
--
-- Safe to run more than once, same as 0001–0003. Run it in the Supabase SQL
-- Editor after the earlier migrations.

-- ---------------------------------------------------------------------------
-- Notifications — the dedupe ledger behind every SMS and escalation.
--
-- (monday_item_id, kind) is UNIQUE and every send claims its row with a
-- unique insert BEFORE sending: a monday webhook retry storm, or two
-- deliveries racing each other, produce exactly one text. `kind` carries the
-- audience and the episode, e.g.
--
--   allocated:<account uuid>          the "new job" SMS, once per account
--   reassigned:<account uuid>         the "nothing more to do" SMS
--   breach:<clock start date>         the sweep's breach record
--   breach_sms:<account>:<start>      the overdue reminder
--   escalated:<clock start date>      the 6.1 Installer Esc. status write
--
-- so a job reallocated to a new company can text the new company exactly once
-- without re-texting the old one, and a fresh SLA clock (a reallocation) is a
-- fresh breach.
-- ---------------------------------------------------------------------------
-- (monday_item_id, kind) is the PRIMARY KEY, not a surrogate uuid plus a
-- unique index: the claim insert uses PostgREST's ignore-duplicates, which
-- resolves on the primary key — with a uuid PK every "duplicate" would be a
-- brand-new row and the dedupe would never dedupe.
create table if not exists notifications (
  monday_item_id bigint not null,
  kind           text not null,
  payload        jsonb not null default '{}'::jsonb,
  sent_at        timestamptz not null default now(),
  primary key (monday_item_id, kind)
);

create index if not exists notifications_item_idx
  on notifications (monday_item_id, sent_at desc);

alter table notifications enable row level security;

-- ---------------------------------------------------------------------------
-- Installer accounts carry a state: SLA business days skip that state's
-- public holidays (holidays_au.py). Synced from the Installer Accounts
-- board's State column; NSW when blank.
-- ---------------------------------------------------------------------------
alter table installer_accounts
  add column if not exists state text not null default 'NSW';

-- Grants match 0003 — service_role only; anon and authenticated stay locked
-- out (RLS enabled, no policies). If 0003 has been run its default privileges
-- already cover this table; repeated here so this file works standalone.
grant all privileges on table notifications to service_role;
