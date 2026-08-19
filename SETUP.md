# Setup guide

Everything here happens in a web browser. There are no commands to type and
nothing to install on your computer.

Set aside about an hour. You can stop after any numbered part and come back —
nothing half-finished breaks anything.

**You are setting up one web app** that does two jobs:

| | What it does | Who uses it |
|---|---|---|
| **The order flow** | Reads an eOrder dropped on a monday row and fills the row in | Navtek staff, in monday |
| **The installer portal** | Shows an installer their jobs and takes their updates | Installers, on a phone |

Both run from the same address. One GitHub repository, one Vercel project, one
Supabase database.

---

## Before you start

Create free accounts for these if you don't have them. Use the **same email**
for all three, and choose "Sign in with GitHub" on Vercel — it saves a step.

- **GitHub** — github.com — stores the code
- **Supabase** — supabase.com — the database
- **Vercel** — vercel.com — runs the app

You also need to be an **admin on the monday account**, because this creates
columns and a new board.

### Two passwords to make now

You need two random strings. Don't invent them — use a generator, for example
**bitwarden.com/password-generator** with length set to 40.

Generate two and paste them somewhere you can reach for the next hour (a draft
email to yourself is fine):

- **SETUP_KEY** — unlocks the setup page
- **PORTAL_SHARED_SECRET** — lets the two halves of the app talk to each other

---

# Part 1 — Put the code on GitHub

### 1.1 Unzip the pack

Download `navtek-eorder.zip` and unzip it. Inside you'll find:

```
navtek-eorder/
├── api/          ← the Python half: reads eOrders, talks to monday
├── app/          ← the pages you and the installers see
├── lib/          ← shared code for the pages
├── supabase/     ← the database setup
├── samples/      ← real eOrders, for testing
├── README.md
└── SETUP.md      ← this guide
```

### 1.2 Create the repository

1. Go to **github.com/new**
2. **Repository name:** `navtek-eorder`
3. Select **Private**

   Not optional. The pack contains real customer eOrders, and the app reads
   commission figures. Do not make this public.
4. Leave every other box unticked
5. Click **Create repository**

### 1.3 Upload the files

On the empty repository page, click **uploading an existing file**.

Open your unzipped `navtek-eorder` folder, select **everything inside it** —
the contents, not the folder itself — and drag it all onto the upload area.
GitHub keeps the folder structure.

Wait for the whole file list to appear, then click **Commit changes**.

### 1.4 Check what arrived

You should see `api`, `app`, `lib`, `supabase`, `samples`, plus
`package.json`, `requirements.txt`, `next.config.mjs` and `vercel.json` at the
top level.

Click into `api` → `_lib`. There should be nine `.py` files.

**If folders are missing:** your browser didn't handle the folder drag. Use
**Add file → Upload files** and do one folder at a time, committing between
each.

### 1.5 What goes up, and what doesn't

Everything in the zip belongs on GitHub. The zip was built without the things
that don't.

| Upload | Skip |
|---|---|
| `api/`, `app/`, `lib/`, `supabase/`, `samples/` | `node_modules/` — thousands of files Vercel installs itself |
| `package.json`, `requirements.txt` | `.next/` — build output |
| `next.config.mjs`, `vercel.json`, `tsconfig.json` | Any `.pyc` file |
| `README.md`, `SETUP.md` | Any file called `.env` or `.env.local` |
| `.env.example` — a template with no real values in it | |

**The one rule:** never upload a file containing a real password or key.
`.env.example` is a template and is safe. A file called `.env` is not.

---

# Part 2 — Add the parser

The pack ships a placeholder where the real eOrder parser goes. Swap it in now.

1. In your repository, click into **`api`** → **`_lib`**
2. Click **Add file → Upload files**
3. Drag in `eorder_parser.py` — the real one from the build pack
4. Click **Commit changes**

GitHub replaces the placeholder. Click the file to confirm it now begins
`"""Navtek eOrder parser — reference implementation`.

> **Don't have it yet?** Carry on — everything else sets up and the health
> check passes. But nothing will actually read an eOrder until this file is in
> place: the file tester and the monday automation will both return
> *"api/_lib/eorder_parser.py is a placeholder"*. This is the one step the
> order flow cannot work without.

---

# Part 3 — The database

### 3.1 Create the project

1. Go to **supabase.com/dashboard** → **New project**
2. **Name:** `navtek-eorder`
3. **Database Password:** click Generate, then **save it in your password
   manager**. You won't need it for this guide, but you can never see it again.
4. **Region:** Sydney (`ap-southeast-2`)
5. **Create new project**, then wait two or three minutes

### 3.2 Create the tables

1. Left sidebar → **SQL Editor** → **New query**
2. In another tab, open your GitHub repository →
   `supabase` → `migrations` → `0001_init.sql`
3. Click the **copy icon** at the top right of the file
4. Paste into the SQL editor and click **Run**
5. Repeat with `0002_users.sql` — that one creates the login tables
6. Repeat with `0003_grants.sql` — that one gives the service key access to
   the tables. On most projects it is already true and the script changes
   nothing; on projects where it isn't, every key fails with "permission
   denied" until this runs.
7. Repeat with `0004_operations.sql` — webhook dedup, the notification
   ledger the SLA engine uses, and the per-account State column for
   public-holiday-aware SLA clocks.

You want **Success. No rows returned.** That is what a successful table
creation looks like — it isn't an error.

Confirm it: click **Table Editor**. You should see seven tables —
`installer_accounts`, `eorder_ingests`, `portal_events`, `jobs_cache`,
`unknown_order_reasons`, `app_users`, `app_sessions`.

### 3.3 Copy two values

Go to **Project Settings** (gear icon) → **API Keys**.

**Project URL** — looks like `https://abcdefgh.supabase.co`. If it isn't on
this page, check Settings → General, or the **Connect** button at the top of
the dashboard.

**The secret key.** Supabase changed how keys work recently, so you'll see one
of two things:

- A **Secret keys** section with a key starting `sb_secret_…` → copy that
- Only older keys → open the **Legacy API Keys** tab and copy **`service_role`**

Either works. What matters is that it's the **secret** one — never the
publishable or anon key. Only the secret key can write to these tables.

Paste both into your notes. Treat the secret key like a password.

---

# Part 4 — The monday token

1. Open monday.com
2. Click your **avatar**, bottom left
3. Click **Developers**
4. Click **My Access Tokens**
5. Click **Show**, then copy

Can't find Developers? Try **Administration → API**. If neither appears you
aren't an admin and will need someone who is.

> This token can read the commission columns on the orders board. It only ever
> gets typed into Vercel's environment variables, which are encrypted and never
> sent to a browser. Don't paste it into a chat, a document, or a file in the
> repository.

---

# Part 5 — Deploy

### 5.1 Import the repository

1. Go to **vercel.com/new**
2. Find `navtek-eorder` and click **Import**

   Not listed? Click **Adjust GitHub App Permissions** and give Vercel access.

### 5.2 Settings

**Framework Preset** should say **Next.js** on its own. Leave **Root
Directory** as it is — the whole repository is the app.

**Project Name:** `navtek-eorder`.

### 5.3 Environment variables

Expand **Environment Variables** and add these one at a time — name on the
left, value on the right, click **Add**.

| Name | Value |
|---|---|
| `MONDAY_TOKEN` | the monday token from Part 4 |
| `ORDERS_BOARD_ID` | `5834171978` |
| `SUPABASE_URL` | the Project URL from 3.3 |
| `SUPABASE_SECRET_KEY` | the secret key from 3.3 (`SUPABASE_SERVICE_KEY` also works) |
| `PORTAL_SHARED_SECRET` | your second random string |
| `SETUP_KEY` | your first random string |
| `WRITE_ORDER_TYPE` | `false` |
| `WEBHOOK_SECRET` | *(optional but recommended)* a third random string. With it set, the monday webhook URL carries a token and the automation rejects anything else that posts to it. Set it before running Setup step 4 — or set it later and run step 4 again. |
| `CRON_SECRET` | *(optional)* a random string. Vercel sends it with the daily SLA sweep so nothing else can trigger it. |
| `SLA_GO_LIVE_DATE` | *(leave unset until go-live)* `YYYY-MM-DD`. Only jobs dispatched on or after this date ever enter the SLA sweep — everything older is backlog reconciled by hand. Unset = the sweep is off. |
| `SLA_NOTIFICATIONS_ENABLED` | `false`. The sweep runs in shadow mode — recording breaches and logging what it *would* text — until this is explicitly `true`. Read a week of shadow output first. |

Check for stray spaces at the start or end of each pasted value. That is the
single most common cause of "it says my token is wrong".

### 5.4 Deploy

Click **Deploy** and wait two or three minutes.

Copy the address at the top when it finishes — something like
`https://navtek-eorder.vercel.app`. **That is your app.**

### 5.5 Check it worked

Open your app address. You should land on the **sign-in page**, offering to
create the first admin — that's correct, do that next (Part 5½). If it warns
that the database isn't connected, a variable in 5.3 didn't save.

### Part 5½ — Sign in

The app is behind a login. The **first person to open it creates the first
admin account** — it asks for a name, an email, a password of at least 10
characters, and the **SETUP_KEY** (proof you're the person who deployed this,
not just someone who found the address).

After that, nobody else can register themselves. You add everyone on the
**Users** page:

- **Orders** access — sees the Orders dashboard and the file tester. This is
  for your staff.
- **Installer** access — sees the installer portal. Link the login to an
  installer account on the same row, and that login sees exactly that
  account's jobs, nothing else.
- **Admin** — everything, including this Users page and Setup.

Give each new user their starting password directly; any admin can reset it
later on the same page. Switching someone off signs them out everywhere,
immediately.

The magic links from Part 7 still work and don't need a login — an installer
can have a link, a login, or both.

Then open **Orders**. You should see a yellow bar saying setup isn't
finished. That bar is correct at this stage.

If you want the detail, open `/api/py/health` on the end of your address:

```json
{ "ok": true, "missing_secrets": [], "unmapped_columns": ["eorder_file", …] }
```

**`missing_secrets` must be empty.** If it isn't, a variable in 5.3 didn't
save — Settings → Environment Variables, fix it, then **Deployments → ⋯ →
Redeploy**.

The long `unmapped_columns` list is expected. Part 6 fixes it.

---

# Part 6 — Switch the order automation on

Click **Setup** in the top navigation. The page is in two halves. The first
five steps are the order automation — that is all you need for eOrders to start
reading into monday. The installer portal steps below them can wait.

Every button is safe to press twice.

**1 — Preview the board changes.** Lists the columns it would add to TN Orders.
Read it. Anything already there shows as `exists` and is left alone.

**2 — Create the columns.** *This changes the live TN Orders board.* It adds
the missing columns and shows the ID of each. Nothing existing is renamed,
moved or deleted.

**3 — Check the columns were found.** Press **Check columns**. You want
`unmapped: []`.

The app reads column IDs off the board by name, so there is nothing to paste
and no redeploy needed at this step. The `COLUMN_IDS` line in the output is
optional — setting it in Vercel pins the IDs, so that if someone later renames
a column the automation keeps writing to the right one instead of quietly
stopping. Worth doing eventually, not now.

If `unmapped` is not empty, step 2 didn't create everything. Run step 1 again
and compare.

**4 — Switch the automation on.** Paste your app address into the box — just
the address, no `/setup` on the end — and press **Register webhook**.

This is the moment it goes live. It registers against the **eOrder column
only**, so the existing DocuSign `files` column carries on being ignored, and
pressing it twice reuses the existing webhook rather than registering a second
one that would process every file twice.

**5 — Check everything works.** Press **Run the check**. It tests the monday
token, the board, the columns, the parser, the webhook and the database, and
tells you which are working. It is read-only.

The database line may say `warn` rather than `PASS`. That is not blocking:
orders are still read and written to monday. What is lost without it is the
duplicate check and the history on the Orders page.

**If the database is rejected**, open `/api/py/health` and read the
`database` block — it now carries Supabase's own explanation in
`supabase_said`, and `key_looks_like` names what kind of key it was actually
given. Four causes cover nearly every case:

- **`supabase_said` says `permission denied for table …`.** The key is fine —
  it was accepted, and then the database refused the role because its grants
  are missing. No key change helps; run `supabase/migrations/0003_grants.sql`
  in the SQL Editor (health calls this state `no_grants`).
- **`supabase_said` mentions legacy keys being disabled.** The project
  refuses `service_role` keys no matter how correctly they're copied. Copy
  the **`sb_secret_…`** key instead (Project Settings → API Keys → Secret
  keys) and put it in `SUPABASE_SECRET_KEY`. Re-enabling legacy keys on that
  same page also works.
- **`key_looks_like` says the key is cut short or truncated.** The paste
  lost the end of the key. Copy the whole value again.
- **A URL and key from two different Supabase projects** — a mismatched pair
  fails exactly like a wrong key. `/health` proves or rules this out
  (`project_match`), and you can set a second pair and let the app try both:

| Name | Value |
|---|---|
| `SUPABASE_URL_2` | the project URL, copied fresh |
| `SUPABASE_SERVICE_KEY_2` | the Secret key from **that same project** |

Redeploy, then run the check again — `database.using` names the pair that
worked, and you can delete the other.

---

## The installer portal (leave this until later)

Two more steps sit under a separate heading on the setup page. They are for the
installer portal and nothing in the order automation depends on them. Until you
run them the **Installer** column stays empty, and no order is flagged because
of it.

**A — Set up the Installer Accounts board.**

*Already have an installer board?* Add `INSTALLERS_BOARD_ID` to your Vercel
environment variables with that board's ID first, and redeploy. The ID is the
long number in the board's URL: `monday.com/boards/18426336129` →
`18426336129`. Without it, this step looks for a board called exactly
"Installer Accounts" and creates one if it can't find it — which on an account
that already has a differently-named board means two boards to reconcile.

With that set, it **adopts** the board rather than replacing it: adds only the
missing columns, and issues a portal token to any account that doesn't have
one. Existing accounts and tokens are untouched. It seeds the eight known names
only onto a genuinely empty board.

It also adds the **Installer** connect column to TN Orders and links the two
boards. The old free-text `installer` column is left where it is, as history.

**B — Copy the installers into the database.** The portal looks a magic link up
in the database, so an account added in monday stays invisible until this runs.
Run it again whenever you add, deactivate or reissue an account.

---

# Part 7 — Give installers their links *(portal only)*

Click **Installers** in the top navigation. Every account is listed with an
**Open** button that opens their portal exactly as they'd see it.

To send someone their link, open their row and copy the address from the
browser bar — it looks like:

```
https://navtek-eorder.vercel.app/j/xK9mP2vQ8nR4tY7wZ1aB…
```

**That link is their password.** Anyone holding it sees that account's jobs.
To cut access off, change the Portal token in monday and press Setup step 5
again — the old link stops working immediately.

Before sending any out, fill in **Coordinator name**, **mobile** and **email**
on the Installer Accounts board. GPS Tech's coordinator is Jocelyn, who runs
their office — not whoever is on the tools that day. Then press step 5 again.

---

# Part 8 — Test it

### 8.1 Read a file without touching anything

Click **File tester** and drag in the Kane Civil eOrder. You should get back
JSON containing:

```
"opportunity_id": "006VP00000agsnG"
"derived_item_name": "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
"acv": 18144.0
```

This writes nothing anywhere. It's what to reach for whenever a file
misbehaves later.

An error mentioning `NotImplementedError` means the real parser hasn't been
uploaded — Part 2.

### 8.2 The real thing

1. Open **TN Orders** in monday
2. In the current month's group, create a row. **Call it `x`** — the name gets
   overwritten.
3. Drag the Kane Civil eOrder onto the **eOrder** column
4. Wait about twenty seconds, then refresh

The row should be renamed `KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551`,
with contact, installer, dates and commercials filled in, **eOrder Status**
showing ✅ Read, and an Update saying what it read.

Then open the **Orders** page in the app — the read appears there too, with how
long it took.

### 8.3 Four things worth checking

| Test | What should happen |
|---|---|
| Drop the same file again | Nothing changes. No second row. |
| Change a quantity, drop it again | Row updates, Update lists what changed |
| Drop any other spreadsheet | ❌ Failed, an Update explaining why, nothing else touched |
| Drop an eOrder with no installer named | Fills in, ⚠️ Check. **Not an error** — most orders don't name one |

---

# When something goes wrong

| What you see | What it means |
|---|---|
| Sign-in page says the database isn't connected | The Supabase variables from 5.3 didn't save, or `0002_users.sql` hasn't been run (3.2). |
| "Create the first admin" won't accept the key | It wants `SETUP_KEY` exactly as set in Vercel — check for stray spaces. |
| Someone sees "This page isn't switched on for you" | An admin needs to enable Orders or Installer for them on the **Users** page. |
| An installer login shows "No installer account linked" | On **Users**, pick their account in the Installer account column. |
| Yellow bar saying setup isn't finished | Work through Part 6. It disappears on its own. |
| Setup page says SETUP_KEY isn't set | You added it but didn't redeploy. Deployments → ⋯ → Redeploy. |
| `missing_secrets` on `/api/py/health` | A variable didn't save, or has a space in it. Fix, then redeploy. |
| `unmapped_columns` still full after step 2 | A column was created with a different title. `/api/py/health` now lists every ID it resolved and where from — compare against step 1. |
| `orders_board` is not the board you expected | `ORDERS_BOARD_ID` points somewhere else. The ID is the long number in the board's URL. |
| Nothing happens when I drop a file | Step 6 wasn't run, or ran with the wrong address. Run it again. |
| Row fills in but eOrder Status stays blank | The column was renamed. It must be a **Status** column titled exactly `eOrder Status`. Press step 3 to confirm what the app can see. |
| An Update says `This status label doesn't exist` | The status column's labels differ from what the app writes. The app now reads the board's own labels and matches against them (emoji and case don't matter), so this only remains possible if a label like `Read` was renamed to something else entirely — rename it back, or expect that write to be skipped with a warning in the Update. |
| Database `rejected` with a correct-looking key | Read `database.supabase_said` on `/api/py/health` — it is Supabase's own reason. Legacy keys disabled → use the `sb_secret_…` key. Signature cut short → re-paste the whole key. See Part 6 step 5. |
| Database says `no_grants` / `permission denied for table …` | The key works; the database role lost its table grants. Run `supabase/migrations/0003_grants.sql` in the SQL Editor. Keys and environment variables are not the problem. |
| Portal says "This link no longer works" | Step 5 hasn't been run since that account was added, or the token changed. |
| Portal loads but shows no jobs | Nothing is allocated to that account. Set the **Installer** column on a row in TN Orders. |
| `NotImplementedError` about the parser | Part 2. |
| Every button returns a bare `HTTP 500` | The Python function is failing to start. Open `/api/py/diag` — it names the missing package or file. |
| Diag says a package is missing | `requirements.txt` isn't being installed. It must be at the top level of the repository; there is also a copy at `api/requirements.txt`. Confirm both uploaded, then redeploy. |
| Diag says a file is missing from `api/_lib` | Upload it. Folders beginning with an underscore are easy to miss in a drag-and-drop upload. |
| A second Installer Accounts board appeared | `INSTALLERS_BOARD_ID` wasn't set before step 3. Set it, redeploy, delete the empty duplicate, run step 3 again. |
| Step 6: no file column called 'eOrder' | Step 2 hasn't run, or the column was renamed. It must be a **File** column titled exactly `eOrder`. |
| Build fails mentioning `app/api` | Someone added a route handler under `app/api`. This project can't use those — see the note in `next.config.mjs`. |

**First stop: `/api/py/diag`.** Open it on your app address. It is a separate
function with no dependencies, so it answers even when everything else returns
a blank HTTP 500, and it tells you which package or file is missing.

**Then:** Vercel → your project → **Logs**. Every request is there
with its error. In monday, the Update on the item explains what happened in
plain English — that's the first place to look, not the last.

---

# Day-to-day

**Adding an installer:** add a row to the Installer Accounts board, fill in the
coordinator details, put a long random string in Portal token, tick Active,
then press Setup step 5.

**Cutting off access:** change that account's Portal token, press step 5.

**Changing the code:** edit the file on GitHub and commit. Vercel redeploys
within a minute or two, on its own.

**Two things are still undecided**, both explained in the README — the Order
Type rule, and getting an Upsell eOrder into the sample set.
`WRITE_ORDER_TYPE` stays `false` until the first is settled.
