-- Navtek eOrder → monday automation
-- 0004_webhook_log.sql — one row per webhook delivery, whatever the outcome.
--
-- Safe to run more than once, same as the earlier migrations.
--
-- Why this exists: the webhook endpoint always returns 200 so monday doesn't
-- retry-storm, which means monday's own automation log shows every run as
-- Success. A duplicate file that was skipped, a removed file, and a fully
-- processed order all look identical from monday's side. The ingest ledger
-- (eorder_ingests) only records real reads — its dedupe index cannot hold a
-- second row for the same file — so skips were invisible everywhere: the
-- exact situation where someone drops a file, sees Success in monday, and
-- nothing on the row or the dashboard explains why nothing happened.
--
-- Service-role only, like everything else here. 0003_grants.sql set default
-- privileges, so a table created after it is covered automatically.

create table if not exists webhook_log (
  id               uuid primary key default gen_random_uuid(),
  monday_item_id   bigint,
  monday_board_id  bigint,
  opportunity_id   text,
  file_name        text,
  -- 'processed' | 'skipped' | 'failed'
  outcome          text not null,
  -- the skip reason ("identical file already read") or the failure detail
  reason           text,
  -- the eOrder Status written when processed ("✅ Read" | "⚠️ Check")
  status           text,
  duration_ms      integer,
  created_at       timestamptz not null default now()
);

create index if not exists webhook_log_created_idx on webhook_log (created_at desc);
create index if not exists webhook_log_item_idx on webhook_log (monday_item_id, created_at desc);

alter table webhook_log enable row level security;
