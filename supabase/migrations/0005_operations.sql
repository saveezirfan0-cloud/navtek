-- Navtek eOrder → monday automation
-- 0005_operations.sql — delivery dedup, notification ledger, installer state.
--
-- Safe to run more than once, same as the others. Run it in the Supabase SQL
-- Editor after 0004_webhook_log.sql.

-- ---------------------------------------------------------------------------
-- Webhook delivery claims (FINALIZE prompt 7).
--
-- The ingest already dedupes at the FILE level (opportunity id + sha256), but
-- monday can deliver the same webhook event more than once, and two deliveries
-- racing each other can both pass that check before either records. A claim on
-- the delivery's identity, taken with a unique insert BEFORE processing,
-- serialises them: one insert wins, the other sees the conflict and stops.
-- Claims are cleaned up by age in code, so a genuinely re-fired event works
-- again after an hour.
-- ---------------------------------------------------------------------------
create table if not exists webhook_deliveries (
  delivery_key text primary key,
  claimed_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Notification ledger (FINALIZE prompts 2 and 3).
--
-- Exactly-once for anything the app tells a human: a row is claimed here
-- (unique on item + kind) before a send, so webhook retries, re-edits and
-- overlapping sweeps cannot double-text a coordinator. The SLA sweep records
-- its shadow-mode "would send" entries here too, which is what makes shadow
-- mode reviewable before notifications are switched on.
-- ---------------------------------------------------------------------------
create table if not exists notifications (
  id              uuid primary key default gen_random_uuid(),
  monday_item_id  bigint not null,
  kind            text not null,
  payload         jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  unique (monday_item_id, kind)
);

create index if not exists notifications_kind_idx on notifications (kind, created_at desc);

-- ---------------------------------------------------------------------------
-- Installer account state (FINALIZE prompt 6).
--
-- Public holidays differ by state, and SLA age is measured in business days —
-- a VIC coordinator must not be chased on Melbourne Cup Day. Synced from a
-- "State" column on the Installer Accounts board when present; NSW otherwise.
-- ---------------------------------------------------------------------------
alter table installer_accounts add column if not exists state text not null default 'NSW';

-- Same lockdown and access as everything else. The grants are also covered by
-- 0003's default privileges, but a migration should stand on its own.
alter table webhook_deliveries enable row level security;
alter table notifications      enable row level security;
grant all privileges on webhook_deliveries, notifications to service_role;
