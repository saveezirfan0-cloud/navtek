-- Navtek eOrder → monday automation
-- 0001_init.sql
--
-- Safe to run more than once: every object is created only if absent. The
-- Supabase SQL editor aborts the whole script on the first error, so without
-- this a half-finished first run could never be completed — only restarted
-- from a clean database.
--
-- monday.com remains the system of record for orders and installer allocation.
-- Supabase holds only what monday cannot: an idempotency ledger, an audit trail,
-- and a render cache so the installer portal does not hammer the monday API.
--
-- Everything here is service-role only. RLS is enabled with no policies, so an
-- anon or authenticated key sees nothing. The portal reaches this through the
-- parser service, never from the browser (see the security note in §10 of the
-- build brief: the monday token grants access to commission columns).

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Installer accounts — mirror of the monday "Installer Accounts" board.
-- The unit of allocation is an ACCOUNT, not a person (brief §6.1). Sole
-- operators collapse to a single row where account == coordinator.
-- ---------------------------------------------------------------------------
create table if not exists installer_accounts (
  id                 uuid primary key default gen_random_uuid(),
  monday_item_id     bigint unique not null,
  account_name       text not null,
  account_type       text,                    -- 'Company' | 'Sole operator'
  coordinator_name   text,
  coordinator_mobile text,                    -- E.164
  coordinator_email  text,
  portal_token       text unique not null,
  region             text,
  active             boolean not null default true,
  -- normalised name for fuzzy matching against eOrder ship-to values
  match_key          text,
  synced_at          timestamptz not null default now()
);

create index if not exists installer_accounts_match_key_idx on installer_accounts (match_key);
create index if not exists installer_accounts_active_idx on installer_accounts (active) where active;

-- ---------------------------------------------------------------------------
-- Ingest ledger — one row per eOrder file we have read.
--
-- Idempotency (acceptance criterion 2): the same file dropped twice hashes to
-- the same sha256 and is skipped. A revised eOrder (criterion 3) hashes
-- differently, so it lands as a new row and we diff `parsed` against the most
-- recent prior row for the same opportunity_id to report what changed.
-- ---------------------------------------------------------------------------
create table if not exists eorder_ingests (
  id               uuid primary key default gen_random_uuid(),
  opportunity_id   text,
  monday_item_id   bigint,
  monday_board_id  bigint,
  file_name        text,
  file_sha256      text not null,
  parsed           jsonb,
  -- 'read' | 'check' | 'failed'  → maps to the eOrder Status column
  status           text not null,
  warnings         jsonb not null default '[]'::jsonb,
  changed_fields   jsonb not null default '[]'::jsonb,
  error            text,
  duration_ms      integer,
  created_at       timestamptz not null default now()
);

-- The idempotency key. Null opportunity_id (a failed parse) is allowed through
-- repeatedly — those we always want to re-attempt and re-report.
create unique index if not exists eorder_ingests_dedupe_idx
  on eorder_ingests (opportunity_id, file_sha256)
  where opportunity_id is not null;

create index if not exists eorder_ingests_opp_idx on eorder_ingests (opportunity_id, created_at desc);
create index if not exists eorder_ingests_item_idx on eorder_ingests (monday_item_id);

-- ---------------------------------------------------------------------------
-- Portal events — append-only audit of what installers did and when.
--
-- The monday columns (Contacted Date, Booked Date, Units Installed) hold
-- current state; this holds the history behind it, which is what you need when
-- an installer says "I called them weeks ago" and the SLA report disagrees.
-- ---------------------------------------------------------------------------
create table if not exists portal_events (
  id                   uuid primary key default gen_random_uuid(),
  installer_account_id uuid references installer_accounts (id),
  monday_item_id       bigint not null,
  monday_subitem_id    bigint,
  -- 'viewed' | 'contacted' | 'booked' | 'progress' | 'completed' | 'blocked'
  action               text not null,
  payload              jsonb not null default '{}'::jsonb,
  user_agent           text,
  created_at           timestamptz not null default now()
);

create index if not exists portal_events_item_idx on portal_events (monday_item_id, created_at desc);
create index if not exists portal_events_account_idx on portal_events (installer_account_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Job cache — denormalised snapshot the portal renders from.
--
-- Refreshed on write-back and on a short TTL. Without this every portal page
-- load is a multi-second monday query, on a phone, in a truck yard.
-- ---------------------------------------------------------------------------
create table if not exists jobs_cache (
  monday_item_id       bigint primary key,
  monday_subitem_id    bigint,
  installer_account_id uuid references installer_accounts (id),
  data                 jsonb not null,
  refreshed_at         timestamptz not null default now()
);

create index if not exists jobs_cache_account_idx on jobs_cache (installer_account_id);

-- ---------------------------------------------------------------------------
-- Unrecognised order reasons — the silent-failure guard from brief §4.1.
--
-- An order reason outside ACV_ORDER_REASONS produces no ACV and no error. That
-- is invisible until targets look light at quarter end, so every unmatched
-- value is recorded here for someone to look at.
-- ---------------------------------------------------------------------------
create table if not exists unknown_order_reasons (
  id             uuid primary key default gen_random_uuid(),
  order_reason   text not null,
  opportunity_id text,
  file_name      text,
  seen_at        timestamptz not null default now()
);

create index if not exists unknown_order_reasons_reason_idx on unknown_order_reasons (order_reason);

-- ---------------------------------------------------------------------------
-- Lock everything down. Service role bypasses RLS; nothing else gets in.
-- ---------------------------------------------------------------------------
alter table installer_accounts    enable row level security;
alter table eorder_ingests        enable row level security;
alter table portal_events         enable row level security;
alter table jobs_cache            enable row level security;
alter table unknown_order_reasons enable row level security;
