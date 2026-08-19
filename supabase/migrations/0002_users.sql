-- Navtek eOrder → monday automation
-- 0002_users.sql — logins for the web app.
--
-- Safe to run more than once, same as 0001: every object is created only if
-- absent. Run it in the Supabase SQL Editor after 0001_init.sql.
--
-- Two kinds of people sign in:
--   * Navtek staff — see the Orders dashboard and the file tester. Admins also
--     manage users, installers and setup.
--   * Installer users — see the installer portal for the ONE installer account
--     their login is linked to. This sits alongside the magic links, it does
--     not replace them: an installer can hold a login, a link, or both.
--
-- Access is per-user and admin-controlled: `can_orders` shows the order side,
-- `can_installer` shows the portal side. An admin sees everything.
--
-- Passwords are held as PBKDF2-SHA256 hashes, never plaintext. Sessions store
-- only the SHA-256 of the browser token, so a database read alone cannot be
-- replayed as a login.

create table if not exists app_users (
  id                   uuid primary key default gen_random_uuid(),
  email                text unique not null,          -- always lowercased
  name                 text not null,
  password_hash        text not null,                 -- pbkdf2_sha256$iter$salt$hash
  is_admin             boolean not null default false,
  can_orders           boolean not null default false,
  can_installer        boolean not null default false,
  installer_account_id uuid references installer_accounts (id),
  active               boolean not null default true,
  created_at           timestamptz not null default now(),
  last_login_at        timestamptz
);

create index if not exists app_users_email_idx on app_users (email);

create table if not exists app_sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references app_users (id) on delete cascade,
  token_sha256 text unique not null,
  user_agent   text,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null
);

create index if not exists app_sessions_token_idx   on app_sessions (token_sha256);
create index if not exists app_sessions_user_idx    on app_sessions (user_id);
create index if not exists app_sessions_expires_idx on app_sessions (expires_at);

-- Service role only, like everything else. RLS on, no policies.
alter table app_users    enable row level security;
alter table app_sessions enable row level security;
