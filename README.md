# Navtek eOrder

One web app doing two jobs. They are independent — the first runs on its own,
and is the one that matters now.

- **The order flow.** Drop a Teletrac Navman eOrder onto a row in **TN Orders
  2026/2025/2024** (`5834171978`) and the row fills itself in. Needs: the
  parser, the board columns, the webhook. Nothing else.
- **The installer portal.** A magic link per installer account showing their
  jobs, taking contacted / booked / progress / complete back to the board.
  Later. With no Installer Accounts board configured, the order flow skips
  allocation entirely rather than flagging every order as unmatched.

Built to the Aug 2026 build brief. Section references below point at it.

**Setting this up? Read [SETUP.md](SETUP.md)** — the whole thing, in a browser,
with no commands.

---

## Shape

One GitHub repository, one Vercel project, one Supabase database.

```
                 ┌───────────────────────────────────────┐
  monday ────────▶  /api/py/*        Python (FastAPI)    │
  webhook        │  parser · monday client · all secrets  │
                 │            ▲                           │
                 │            │ server-side fetch         │
                 │  /  /setup /installers /j/[token]      │
  installer ─────▶            Next.js pages               │
  magic link     └───────────────────────────────────────┘
                              │
                              ▼
                           Supabase
```

| Path | What it is |
|---|---|
| `api/index.py` | Every HTTP route the Python half serves, under `/api/py/*` |
| `api/_lib/` | Parser, monday client, mapping, matching, storage, bootstrap |
| `app/` | Pages — dashboard, setup, installers, file tester, portal |
| `lib/api.ts` | Server-only client for the Python half |
| `supabase/` | Schema: ingest ledger, audit trail, job cache |

### Why the split is where it is

The Python half owns every credential. The monday token is account-wide and
reaches the commission columns on the orders board, so it lives in one process
and the browser never sees it — `lib/api.ts` imports `server-only` to make that
a build error rather than a code review.

**Two structural constraints, both non-obvious:**

1. **The Python functions must live in `/api` at the repository root**, not in
   `app/api`. That is how Vercel runs two runtimes in one project.
2. **Nothing may use `app/api` route handlers.** Once a project has Python
   functions under root `/api`, Vercel routes that whole prefix to them and
   `app/api` handlers stop resolving. Use server components and server actions
   instead. Both pages that need to write do exactly that.

`vercel.json` pins `includeFiles: api/_lib/**` so the shared modules ship with
the function rather than relying on directory-walking behaviour.

---

## The parser

`api/_lib/eorder_parser.py` **is a placeholder**. Copy the reference
implementation from the build pack into that exact path, unchanged.

Two things in it are load-bearing and documented in its own docstring —
`load_workbook_tolerant()` (TN's template emits a workbook GUID that hard-fails
strict xlsx parsers; Excel opens the files fine) and `find()` (every value is
located by searching for its *label*, never by cell reference, so a template
revision that inserts a row doesn't break things silently). Read both before
touching it.

Everything else depends only on the key set documented under `PARSER CONTRACT`
at the top of `api/_lib/mapping.py`. Field access goes through a fallback
helper, so a renamed key degrades to a `⚠️ Check` flag rather than a 500 — but
the contract is what to check first if output looks thin.

---

## Routes

| | |
|---|---|
| `/login` | Sign in. First visit ever offers to create the first admin (needs `SETUP_KEY`). |
| `/` | Dashboard — every eOrder read, with status and timing. Needs **Orders** access. |
| `/try` | Drop an eOrder in, see what the parser reads. Writes nothing. Needs **Orders** access. |
| `/portal` | The installer portal for a **logged-in** installer user — their linked account's jobs. |
| `/users` | Who can sign in and what each login sees. Admin only. |
| `/setup` | Board setup. Admin only, plus `SETUP_KEY` for the board-changing steps. |
| `/installers` | Accounts and their magic links. Admin only. |
| `/j/[token]` | The installer portal via magic link — no login, the link is the password |
| `/api/py/eorder` | monday webhook |
| `/api/py/parse` | xlsx in, JSON out. No monday, no database. |
| `/api/py/health` | What's configured and what isn't |

### Logins and access

Two switches per user, flipped by an admin on `/users`: **Orders** (dashboard +
file tester) and **Installer** (the portal, which also needs the login linked
to exactly one installer account — the server scopes every job list and
write-back to that account). Admins see everything, manage users, and cannot
remove their own admin access or deactivate themselves.

Sessions are opaque tokens in an httpOnly cookie; the database stores only
their SHA-256, passwords only as PBKDF2 hashes (`supabase/migrations/
0002_users.sql`). Deactivating a user signs them out everywhere on their next
click. Magic links (`/j/[token]`) are unchanged and independent — an installer
can hold a link, a login, or both.

`/parse` is deliberately dependency-free — it is how you check a file without
writing anything anywhere, and what Make would call if the flow ever moves
there (§3.3).

---

## Testing

```bash
python -m pytest tests/ -q         # 59 tests, no network, no credentials
python scripts/verify.py samples/  # extraction gate against real eOrders
```

`tests/test_ingest.py` runs the real ingest path — real eOrder files, real
parser, real mapping — against a fake monday and a fake database, and encodes
the brief's acceptance criteria directly: a new order populates and reads
clean, the same file twice is skipped, a revision reports what changed, a
non-eOrder fails without touching anything else, an order with nothing to ship
is not an error, ACV appears only on new-revenue reasons, a value already in
monday is never overwritten, and the order still lands when the database is
down. Each of those was verified by hand once and then quietly broken by a
later change; that is why they are tests now.

Or use `/try` in the browser, which needs no local setup at all.

---

## Decisions baked in

**Order Type is not written.** `WRITE_ORDER_TYPE=false` by default. monday's
values are compound (`New Business | Rental`) and the eOrder supplies only the
first half; the Kane Civil file is headed "OUTRIGHT ORDER FORM" while its monday
row reads `New Business | Rental`, so the form title isn't a usable source (§4).
A blank prompts someone to fill it in; a wrong value doesn't.

**ACV is a calculation, and stays empty when it doesn't apply.** Never a zero —
a zero is a real measurement that drags a new-business target average down
(§4.1). Any order reason outside `ACV_ORDER_REASONS` is logged to
`unknown_order_reasons`, because the failure mode otherwise is silent.

**Installer allocation is a suggestion, never an assertion.** Where the ship-to
is confidently a known account we pre-fill; below the match threshold we write
nothing and flag Check rather than routing an SMS to the wrong company (§6.2).
A missing installer is *not* an error — only 1 of 5 sample orders named one
(§8.1).

**Existing monday values are never clobbered.** First read fills blanks only. A
revised eOrder may correct fields, and says what it changed in the Update.

**Progress is one number, not a checklist.** Shown only when `Units Total > 1`,
and entering the total does not auto-complete the job — fitting the last unit
and finishing the job are different events (§6.4).

---

## Still open

- **Order Type**: where Rental vs Outright comes from. Blocks §4.
- **An Upsell eOrder** for the sample set. That ACV branch has no test
  exercising it; `verify.py` says so on every run rather than passing quietly.
- **Two samples are missing** from `samples/` — Cosmo Cranes (the vanity-phone
  case, `1300 1 COSMO`) and Qualityvend (the four-site Multiple Addresses
  case). Their expectations are already in `fixtures/expected.json`, so
  `verify.py` reports them as MISSING and fails rather than passing on a
  reduced set.
- **§8 of the brief** lists the multi-site sample as *Qantas Road Express /
  Upsell*, but the file in the pack is *Qualityvend / Add-On*, which is what
  §4.1 and the parser agree on. Worth correcting — as written it implies the
  Upsell branch has a sample when it doesn't.
