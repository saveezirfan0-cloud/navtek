# Finalisation prompts

Copy-paste prompts to finish the build, one work item per prompt. Run them in
this order against this repository — each is self-contained, and each ends
with the same gate: `python -m pytest tests/ -q` green and
`python scripts/verify.py samples/` unchanged.

They encode the review of Damon's workflow notes, so the traps that were
already caught don't get rebuilt:

**Locked-in decisions — do not relitigate these in any prompt:**
- **No vehicle-count reconciliation.** The Onboarding Vehicles sheet ships
  with TN's template junk rows in every file; the parser filters them and
  zero vehicles is normal. A count check flags 100% of orders.
- **Order Type is never written** until someone states the Rental vs Outright
  rule. `WRITE_ORDER_TYPE` stays false.
- **ACV stays blank when it doesn't apply** — never zero.
- **Existing monday values are never clobbered.**
- **Auth is now built**: logins, per-user Orders/Installer access, server-side
  job ownership. Prompts must not add browser-side filtering or expose the
  monday token.

**Questions for Damon before running the prompts** (answers slot into prompts
2, 3 and 6):
1. The go-live cutoff date — only jobs dispatched after it enter the SLA
   engine. Which date?
2. Confirm the SMS rule: fire when installer is set AND hardware is
   dispatched, whichever happens second. Correct?
3. Which states' public holidays matter (installers operate NSW + VIC today —
   others?).

---

## Prompt 1 — One Install item per order, always

> In this repo, the order flow currently only creates Install items when
> delivery mode is "Multiple Addresses", but the installer workflow (portal,
> SLA clock, SMS) starts from "staff sets the Installer column on an install
> item". That leaves single-site orders — the majority — with no install item
> and two divergent code paths. Change the ingest so that **every order with
> Install Required = Yes gets exactly one Install item per site**: one for a
> single-site order, one per site row for multi-site (e.g. four for a JETS
> order). Single-site installs must carry the same fields multi-site ones do
> (site contact, phone, address, units for that site, dispatch date), sourced
> from the main delivery block. The portal (`api/_lib/portal.py`), the SLA
> age calculation and any future SMS trigger must operate only on this one
> uniform object — remove any branch that treats single-site orders
> specially. Orders with Install Required = No (Change of Ownership, Service
> Only Renewal, customer self-install) create none. Add tests: Kane Civil →
> 1 install item; Qualityvend → 2 (its two sites); AGB and Southern Truck →
> 0. Do not change the parser.

## Prompt 2 — SLA engine with a go-live cutoff

> Add the SLA engine to this repo, with a hard go-live cutoff. Config:
> `SLA_GO_LIVE_DATE` (ISO date, required before the sweep can be enabled) and
> `SLA_BUSINESS_DAYS` (default 2). Rule: only install items whose **dispatch
> date is on or after `SLA_GO_LIVE_DATE`** ever enter the SLA engine —
> everything older is historical backlog that Navtek reconciles with
> installers by hand, and the engine must never text, escalate or flag it.
> The board currently has jobs up to 212 business days overdue; a sweep
> without this cutoff blasts every installer with months-old reminders on
> day one and kills trust in the first hour. Implement the daily sweep as an
> endpoint (`POST /api/py/sla/sweep`, guarded by the portal shared secret)
> that a Vercel cron calls; it computes SLA age per install item and records
> breaches, but notification sending stays behind a separate
> `SLA_NOTIFICATIONS_ENABLED` flag defaulting false so the sweep can run in
> shadow mode first. Log what the sweep *would* send while shadowed. Tests:
> a job dispatched before the cutoff never appears in sweep output no matter
> how overdue; one after the cutoff appears on business day 3.

## Prompt 3 — SMS trigger: installer set AND dispatched

> Add the installer SMS trigger. The rule is one condition with two parts:
> fire when **both** are true — the Installer column is set on the install
> item, **and** the hardware is dispatched (dispatch date present and not in
> the future). Whichever of the two happens second triggers the send; the
> 2-day SLA clock runs from the dispatch date. Never fire on installer-set
> alone: that texts a coordinator about hardware still in the warehouse and
> starts a clock on a job they can't do. Exactly one send per install item —
> record sends in a `notifications` table keyed on (install item id, kind)
> and check it before sending, so webhook retries and re-edits can't
> double-text. Respect the `SLA_GO_LIVE_DATE` cutoff from the SLA engine.
> Wire the send through a provider-agnostic `send_sms(to, body)` in a new
> `api/_lib/sms.py` with a logging stub implementation, so the Twilio/etc
> decision stays a config change. Message content: account coordinator's
> name, customer, suburb, unit count, and the portal link (magic link, or
> `/portal` if the account has a login). Tests for: installer-then-dispatch,
> dispatch-then-installer, retry storm → one SMS.

## Prompt 4 — Reallocation

> Handle installer reallocation. The board shows this happens constantly
> ("Now Dan Wells = SYD (was GPS TECH)"). When the Installer column on an
> install item **changes** from account A to account B: (1) the item
> disappears from A's portal immediately — verify the portal query already
> guarantees this and add a test; (2) B gets the same SMS as a fresh
> allocation, subject to the dispatched-AND-assigned rule from the SMS
> prompt, and a fresh SLA clock starting from the reallocation date, not the
> original dispatch date — being given a job today must not mean inheriting
> someone else's 40-day breach; (3) A gets a short "this job has been
> reassigned, nothing more to do" SMS **only if** A had already been
> notified about the job; (4) the change is recorded in `portal_events` with
> both accounts. Implement via a monday webhook on the Installer column
> (extend `bootstrap.register_webhook` to register it alongside the eOrder
> one, idempotently). Reallocation of an item that was never dispatched
> notifies nobody.

## Prompt 5 — Keep the portal honest: column webhooks + resync

> The portal reads a cache that refreshes on portal loads and write-backs,
> so a direct edit in monday (status, dispatch date, installer) can leave
> the portal stale. Add: (1) monday webhooks on the dispatch date and status
> columns of install items, registered idempotently through the existing
> bootstrap step, handled by a small endpoint that refreshes the cached job
> for that item; (2) a periodic resync (`POST /api/py/portal/resync`,
> secret-guarded, Vercel cron hourly) that re-pulls every open job for every
> active installer account and overwrites `jobs_cache`; (3) a
> `refreshed_at`-based staleness marker the portal shows when its data is
> more than an hour old ("Updated 3h ago — pull to refresh"). Keep the
> existing live-read-first design; this is belt and braces for the fallback
> path, not a replacement.

## Prompt 6 — Australian business days, and the 6.1 escalation status

> Two SLA correctness items. First: business-day arithmetic
> (`business_days_since` in `api/_lib/portal.py`) must skip Australian
> public holidays, which differ by state — otherwise coordinators get chased
> on Melbourne Cup Day. Add `api/_lib/holidays_au.py` with national holidays
> plus per-state ones for at least NSW and VIC (data as code, a dict of date
> → name per state per year, covering this year and next; add a test that
> fails after the last covered year so someone extends it). Each installer
> account carries a `state` (add the column to the Installer Accounts board
> sync and the accounts table; default NSW). SLA age for a job uses the
> installer account's state. Second: when a job breaches SLA without
> installer contact, the escalation path sets the order's status to the
> existing, currently-unused **"6.1 Installer Esc."** status value on the
> orders board — it already shows in the views Navtek staff use daily, so no
> new view is needed. Escalation is once per breach, recorded in
> `portal_events`, and respects the go-live cutoff.

## Prompt 7 — Webhook delivery dedup

> The ingest already has file-level idempotency (opportunity id + sha256:
> identical re-drop does nothing, revised file updates and reports the
> diff). What it lacks is **delivery-level** dedup: monday can fire the same
> webhook event more than once, and two deliveries of the same drop that
> race each other can both pass the `already_ingested` check before either
> records. Add an early idempotency gate keyed on monday's event identity
> (asset id + item id, or the event's trigger uuid if present in the
> payload): claim the key in the database with a unique-insert before
> processing, skip if the claim fails, and expire claims after an hour so a
> genuinely re-fired event eventually works. The gate must fail open when
> the database is down — an order landing twice is recoverable, an order
> not landing is not. Tests: same delivery twice → one ingest; two
> concurrent deliveries → one claim wins; database down → ingest proceeds.

## Prompt 8 — Multi-site quantity check that knows when to shut up

> Review the multi-site quantity handling in the parser/mapping. Per-site
> quantities live in a free-text notes column with formats like "x 4" and
> "8 x VT202s get shipped to Paul (Sydney installs)"; `site_qty()` returns
> None — not 0 — when it can't tell. The rule to enforce: run the
> sites-sum-vs-total check **only when every site row parsed to a number**;
> if any site is None, or the order has no multi-site rows at all (every
> single-site order — their sum would be 0), skip the check silently rather
> than failing it. When the check does run and mismatches, that's a ⚠️ Check
> flag with the numbers in the Update, never a failure. Add tests for: all
> sites parse and match; all parse and mismatch; one site unparseable;
> single-site order. Confirm Qualityvend still parses to its two sites with
> the right quantities.

## Prompt 9 — Close the sample gaps

> The verification set is incomplete and says so on every run: Cosmo Cranes
> (vanity phone number "1300 1 COSMO") and Qualityvend (four-site Multiple
> Addresses) are expected by `fixtures/expected.json` but missing from
> `samples/`, and no Upsell eOrder exists at all, so the Upsell ACV branch
> has never been exercised. When the missing files arrive from Navtek: drop
> them into `samples/`, run `python scripts/verify.py samples/`, and fix any
> divergence in the *expectations* only if the file proves the expectation
> wrong — the parser contract wins otherwise. For the Upsell branch, add the
> new sample to `fixtures/expected.json` including its ACV, and confirm ACV
> appears for Upsell but stays blank for Change of Ownership and Service
> Only Renewal. Do not weaken `verify.py`'s MISSING-file failure — passing
> quietly on a reduced set is the failure mode it exists to prevent.

## Prompt 10 — Pre-go-live check

> Do a pre-go-live review of this repo and report findings without changing
> behaviour. Confirm: the monday token and Supabase keys appear only
> server-side (no NEXT_PUBLIC_, nothing in client components); every
> portal/jobs and portal/action path verifies job ownership on the server
> against the installer account, never by filtering in the browser; the
> setup endpoints all enforce SETUP_KEY; auth endpoints enforce the portal
> shared secret; sessions are hashed at rest; /installers (which lists
> magic-link tokens) is admin-gated; the webhook endpoint returns 200 on
> failure so monday doesn't retry-storm; and no endpoint echoes secrets in
> error bodies. Then check the operational list: Vercel crons configured for
> the SLA sweep and portal resync, `SLA_GO_LIVE_DATE` set,
> `SLA_NOTIFICATIONS_ENABLED` still false until the shadow-mode log has been
> read for a week of real orders, and the samples containing real customer
> data are deleted from the repo before the engagement ends. Output a
> pass/fail table with file:line evidence.
