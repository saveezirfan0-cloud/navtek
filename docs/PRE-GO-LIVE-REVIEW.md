# Pre-go-live review (FINALIZE prompt 10)

Conducted 20 Aug 2026, read-only, against the merged main. Line numbers are
from this commit; the function names are the stable reference.

One FAIL was found during the review and fixed in the same change set (job
ownership on write-backs — see below). Everything else passed as built.

## Security

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | monday token & Supabase keys server-side only; no `NEXT_PUBLIC_`, nothing in client components | **PASS** | No `NEXT_PUBLIC_` anywhere in `app/`, `lib/`, `api/`. Every secret lives in `api/_lib/config.py`; `lib/api.ts:15` and `lib/auth.ts:10` `import "server-only"`, so a client-component import is a build error. The only "SETUP_KEY" in a client file is the label of the input the first admin types it into (`app/login/LoginForm.tsx:25`) — proving knowledge of the key is that form's purpose. |
| 2 | Every portal jobs/action path verifies job ownership server-side, never by browser filtering | **PASS (after fix)** | Job lists: `portal.fetch_jobs` queries monday by the account's own Installer-column value (`api/_lib/portal.py`, `jobs_for_account`) and the cache is filtered by `installer_account_id` server-side. Write-backs: **found FAIL, fixed** — `apply_action` took the `item_id` from the request body unverified, so any valid magic link could write to any orders-board row. Now `portal.require_ownership` (`api/_lib/portal.py:366`) proves the Installer column names the calling account before any write (`apply_action`, `api/_lib/portal.py:428`), falling back to the account's own cache rows when monday is unreachable — silence denies. Same rule added to `/portal/vehicle-list` (`api/index.py:438`), which was minting asset URLs for arbitrary `item_id`s. Endpoints return 403. Tests: `test_a_write_back_to_another_accounts_job_is_refused`, `test_ownership_falls_back_to_the_cache_and_silence_denies`. |
| 3 | Setup endpoints enforce `SETUP_KEY` | **PASS** | Every `/setup/*` route calls `_setup_guard` (8 call sites in `api/index.py`), which 503s when the key is unset and 401s on mismatch. `/api/py/installers` (which lists magic-link tokens) is behind the same guard. |
| 4 | Auth endpoints enforce the portal shared secret | **PASS** | Every `/auth/*`, `/users*`, `/portal/*` route calls `_authorise` (`api/index.py:358`), which **fails closed** — no `PORTAL_SHARED_SECRET` configured means 503, not open — and compares constant-time. The cron routes use `_cron_authorise` with the same fail-closed posture. Failed sign-ins are throttled (8 per 15 min per email). |
| 5 | Sessions hashed at rest | **PASS** | The browser holds an opaque token; the database stores only its SHA-256 (`users.token_sha`, `api/_lib/users.py:62`; `app_sessions.token_sha256`, `supabase/migrations/0002_users.sql`). Passwords are salted PBKDF2-SHA256. |
| 6 | `/installers` (magic-link tokens) gated | **PASS** | `_setup_guard` on the API route; the `/installers` page is admin-only in the web half. |
| 7 | Webhook endpoints return 200 on failure so monday doesn't retry-storm | **PASS** | `/eorder`, `/installer-change`, `/portal/refresh` all return `JSONResponse(result, status_code=200)` on every outcome (`api/index.py:219,253,277`); every delivery is recorded in `webhook_log` so a skip and a success stay distinguishable. Delivery-level dedup (`store.claim_delivery`, keyed on monday's triggerUuid, 60-min expiry, fails open when the database is down) sits in front of the ingest (`api/_lib/ingest.py:138`). |
| 8 | No endpoint echoes secrets in error bodies | **PASS** | The global exception handlers give raw detail only to callers proving the shared secret or setup key (`_caller_is_trusted`, `api/index.py:42`); anonymous callers get a generic line. `WEBHOOK_SECRET` (when set) gates the public webhook endpoints via `?hook=`. |

## Operational

| # | Item | Verdict | Notes |
|---|---|---|---|
| 9 | Vercel crons for SLA sweep + portal resync | **PASS** | `vercel.json` — sweep daily 21:00 UTC (7am AEST), resync hourly at :30. Set `CRON_SECRET` so only Vercel can fire them. |
| 10 | `SLA_GO_LIVE_DATE` set | **OPERATOR** | Deploy-time environment variable; unset = the whole SLA engine is off. Needs Damon's date. `/health` reports the engine's mode. |
| 11 | `SLA_NOTIFICATIONS_ENABLED` stays false until a week of shadow-mode logs has been read | **OPERATOR** | Defaults false. The sweep logs `[sla:shadow]`/`[sms:shadow]` lines to the Vercel function logs; read a week of real orders before flipping. |
| 12 | Samples with real customer data deleted before the engagement ends | **OPERATOR** | `samples/*.xlsx` are real customer eOrders (Kane Civil, AGB, Southern Truck). Delete from the repo — and its git history if the repo outlives the engagement. |

## Prompt 9 (samples) — blocked on Navtek

`fixtures/expected.json` expects Cosmo Cranes and Qualityvend; both files are
still missing from `samples/`, and no Upsell eOrder exists, so `verify.py`
fails by design rather than passing on a reduced set. When the files arrive:
drop them into `samples/`, run `python scripts/verify.py samples/`, and only
change an *expectation* if the file proves it wrong. Do not weaken the
MISSING-file failure.
