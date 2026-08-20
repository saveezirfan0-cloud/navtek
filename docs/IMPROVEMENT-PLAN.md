# Improvement plan — August 2026

Written after the Deliveries tab shipped (webhook log moved off the dashboard,
paginated server side). This is the considered answer to "what should this app
do next" across features, layout, UI, and the stack itself.

> **Status: executed, same branch.** Everything below that code could deliver
> has shipped — CI, lint, the smoke test, server-side pagination + search on
> Deliveries / Orders / Activity, monday deep links, the `/orders/[item]`
> detail page, the `/sla` console, Twilio support in `sms.py`, webhook
> signature verification, log retention, dark mode, responsive card tables,
> and saved-toasts on `/users`. The exceptions need the business, not code:
> the Order Type source, the missing Upsell sample, and the two absent sample
> files (Phase 2, item 6) — plus flipping the new switches
> (`MONDAY_SIGNING_SECRET`, `MONDAY_ACCOUNT_SLUG`, `TWILIO_*`,
> `SLA_GO_LIVE_DATE`) in Vercel, which is configuration, not a deploy.

## Where the app stands

- **Stack.** Next.js 16 (App Router, server components) with hand-rolled CSS
  ported from the signed-off prototype; Python FastAPI living in `/api` at the
  repo root (Vercel's two-runtime layout); Supabase spoken to over raw
  PostgREST. monday.com remains the system of record — the database is a
  ledger, never the point.
- **Health.** 151 passing Python tests covering the ingest contract, auth,
  SLA engine and installer flow. No frontend tests, no linter, and no CI —
  the suite only runs when someone remembers to run it.
- **Surface.** Nine pages: Orders, Deliveries, File tester, the two installer
  portals (login and magic-link), Installers, Users, Activity, Setup.

## The framework question: keep it

Nothing in the stack is straining, and the unusual choices exist for
documented reasons:

- The **Next.js + FastAPI split** is load-bearing: every credential lives in
  the Python half, and Vercel's root-`/api` routing is why `app/api` handlers
  are forbidden. A consolidation to one runtime would re-open the question of
  where the monday token lives, for no feature gained.
- **React 19 / Next 16** are current. Server components fit these read-heavy
  dashboards; there is almost no client-side state to justify heavier tooling.
- The **hand-rolled CSS** (~370 lines) is a signed-off visual language with no
  build step. Adopting Tailwind or a component library mid-flight would be a
  redesign wearing a refactor's clothes. Revisit only if the admin surface
  doubles.
- **PostgREST over httpx** instead of an SDK keeps serverless cold starts
  small — deliberate, documented in `store.py`, still right.

What's missing is engineering hygiene around the stack, not a new stack.

## Phase 1 — operability quick wins (days each)

1. **CI.** A GitHub Actions workflow running `pytest`, `tsc --noEmit` and
   `next build` on every push. Highest value-per-line change available.
2. **Lint/format.** ESLint (next/core-web-vitals) + Prettier, enforced in CI.
3. **Deliveries: filter and search.** Outcome chips (Processed / Skipped /
   Failed) and a search box, mirroring the Recent reads tools — pushed into
   the query (`outcome=eq.…`) so they filter the whole log, not one page.
4. **Paginate the Activity tables** the same way `/deliveries` now works.
   They silently cap at 150/50/50 today with no way further back.
5. **Recent reads: server-side pagination + search.** The dashboard search
   only sees the 50 rows loaded; an operator looking for last month's order
   currently can't find it in the app at all.
6. **Deep links to monday.** Every `item 12848642511` should be a link to the
   board row (needs only the account slug as an env var). Done once in a
   shared component, it lights up Deliveries, Activity and Recent reads.
7. ~~Fix the duplicate `crons` key in `vercel.json`~~ — done in this branch;
   the first block was dead JSON.

## Phase 2 — features that close loops (a week or two each)

1. **An order detail page** (`/orders/[item]`). Today a ⚠️ Check row squeezes
   its "why" into one Notes cell. One page per order: parsed payload,
   warnings, revision history, every webhook delivery for that item, link to
   monday. This is the single biggest usability gap.
2. **An SLA console.** The engine runs in shadow mode, but reading its output
   means reading the Activity feed. A dedicated panel — what yesterday's sweep
   *would* have sent, per-job countdown to breach, a loud shadow-vs-live
   banner — is what makes flipping `SLA_NOTIFICATIONS_ENABLED` a decision
   instead of a leap.
3. **A real SMS provider** in `sms.py` (a config change by design), with the
   provider's delivery status written back to the notification ledger.
4. **Webhook authenticity.** The eOrder endpoints echo monday's challenge but
   then accept any caller who knows the URL. Verify the JWT monday sends in
   the `Authorization` header against the signing secret.
5. **Retention.** `webhook_log` and `portal_events` grow forever. A scheduled
   purge (say, 180 days) keeps pagination fast and the database small.
6. **Close the brief's open items** — the Order Type source, the missing
   Upsell sample, the two absent sample files. `verify.py` fails today *by
   design* to keep them visible; they still need answers from the business.

## Phase 3 — UI and layout polish (as capacity allows)

1. **Mobile-friendly admin tables.** `scroll-x` is a stopgap; below ~700px the
   admin tables should collapse to the card layout the portal already proves.
2. **Dark mode.** The palette is already CSS variables in `:root`; a
   `prefers-color-scheme` block is an afternoon, not a project.
3. **Action feedback.** The Users and Installers pages act silently on
   success; a small toast ("Saved — Paul can no longer sign in") closes the
   loop.
4. **Shared table components.** The same `<table>` + pill + `when()` markup is
   hand-copied across four pages. Extract `Pill`, `DataTable`, `Pager` once
   Phase 1's pagination lands everywhere.
5. **A Playwright smoke test** (login → dashboard → deliveries → portal) in
   CI, so a broken build can't reach production quietly.

## Deliberately not doing

No Tailwind/shadcn migration, no tRPC or ORM, no single-runtime rewrite, no
move off Vercel. Each trades weeks of churn against problems this app doesn't
have — and several would fight constraints (`/api` routing, credentials in
Python) that exist for reasons the README documents.
