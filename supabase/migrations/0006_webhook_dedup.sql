-- Navtek eOrder → monday automation
-- 0006_webhook_dedup.sql — delivery-level dedup for the monday webhook.
--
-- Safe to run more than once. Run it after 0005_installer_flow.sql.
--
-- The ingest already dedupes at the FILE level (opportunity id + sha256), but
-- monday can deliver the same webhook event more than once, and two deliveries
-- racing each other can both pass that check before either records. A claim on
-- the delivery's identity, taken with a unique insert BEFORE processing,
-- serialises them: one insert wins, the other sees the conflict and stops.
-- Claims are cleaned up by age in code, so a genuinely re-fired event works
-- again after an hour.

create table if not exists webhook_deliveries (
  delivery_key text primary key,
  claimed_at   timestamptz not null default now()
);

alter table webhook_deliveries enable row level security;
grant all privileges on table webhook_deliveries to service_role;
