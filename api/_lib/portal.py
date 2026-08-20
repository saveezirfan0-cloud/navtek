"""Installer portal backend.

What is here: the job list an account can see, the four write-backs the
prototypes show buttons for, and the cache plumbing that keeps the portal
honest when monday is slow or edited directly — a per-item refresh for the
column webhooks and a full resync for the hourly cron.

The shape follows the prototypes exactly — jobs are grouped into "Action needed"
and "Waiting on hardware", and each carries the SLA age in business days that
drives the red chip. Business days are Australian: weekends plus the public
holidays of the installer account's state (holidays_au.py).

The unit of work everywhere in here is the INSTALL ITEM (finalisation Prompt 1):
one per site, single-site orders included. The ingest creates them as subitems;
orders that predate that get one synthesized from the order row. Either way,
everything downstream of install_items() sees the same shape.
"""

import re
from datetime import date, datetime, timedelta, timezone

from . import columns as columns_mod
from . import config, holidays_au, mapping

# Kept as a module name for older imports; the value now follows config.
SLA_BUSINESS_DAYS = config.SLA_BUSINESS_DAYS


def _as_date(when):
    if not when:
        return None
    if isinstance(when, datetime):
        return when.date()
    if isinstance(when, date):
        return when
    try:
        return datetime.fromisoformat(str(when)[:10]).date()
    except ValueError:
        return None


def business_days_since(when, state="NSW", today=None):
    """Business days from `when` to today, skipping the state's public holidays.

    A coordinator must not be chased on Melbourne Cup Day: which days count as
    working days depends on the installer account's state (§6 / prompt 6).
    """
    when = _as_date(when)
    if not when:
        return None
    days, cursor = 0, when
    today = today or date.today()
    while cursor < today:
        cursor += timedelta(days=1)
        if holidays_au.is_business_day(cursor, state):
            days += 1
    return days


def sla_clock_start(store, item_id, dispatched):
    """When this job's SLA clock starts: dispatch, or a later reallocation.

    A job reallocated to a new installer today must not arrive carrying the
    previous installer's 40-day breach — the clock restarts on the
    reallocation date (prompt 4), which lives in portal_events.
    """
    start = _as_date(dispatched)
    if not start:
        return None
    event = None
    try:
        event = store.latest_event(int(item_id), "reallocated")
    except Exception:  # noqa: BLE001 - the ledger is optional, the clock is not
        event = None
    if event:
        realloc = _as_date(event.get("created_at"))
        if realloc and realloc > start:
            return realloc
    return start


def fetch_jobs(monday, store, account):
    """Every open job allocated to this installer account, plus freshness.

    Reads monday live — allocation changes there and the portal must reflect it
    (§6.2). The cache is a fallback for when monday is slow or rate-limiting,
    not the primary path, because a stale job list sends someone to a site that
    was reallocated last week.

    Returns (jobs, refreshed_at_iso). refreshed_at is now for a live read, and
    the oldest cached row's refresh time for a fallback read — the portal shows
    a staleness marker off it.
    """
    cols = columns_mod.resolved(monday)
    column_id = cols.get("installer")

    if column_id:
        # Only the columns _shape() actually reads — the board carries 25+,
        # including raw JSON blobs, and this query runs on a phone's clock.
        # Inlined as literals (our own resolved IDs) rather than a variable:
        # column_values(ids:) wants [String!], which the GraphQL lint in
        # tests/test_graphql.py rightly forbids for column_values FILTERS.
        wanted = [cols.get(k) for k in (
            "site_contact", "site_phone", "site_address", "opportunity_id",
            "order_date", "contacted_date", "booked_date",
            "scheduled_install_date", "units_total", "units_installed",
            "installer",
        )]
        import json as _json
        ids_literal = _json.dumps([c for c in wanted if c])
        try:
            raw = monday.gql(
                f"""
                query ($b: ID!, $c: String!, $v: [String]!) {{
                  items_page_by_column_values (
                    board_id: $b, limit: 100,
                    columns: [{{column_id: $c, column_values: $v}}]
                  ) {{
                    items {{ id name column_values (ids: {ids_literal}) {{ id type text }} }}
                  }}
                }}
                """,
                {
                    "b": str(config.ORDERS_BOARD_ID),
                    "c": column_id,
                    "v": [str(account["account_name"])],
                },
            )
            items = (raw.get("items_page_by_column_values") or {}).get("items") or []
            jobs = []
            for item in items:
                jobs.extend(
                    install_items(monday, item, cols, state=account.get("state"))
                )
            # One batched upsert, keyed by the install item's own id — two
            # sites of one order must not overwrite each other in the cache.
            store.cache_jobs([
                {"monday_item_id": job["install_id"], "data": job,
                 "monday_subitem_id": job.get("subitem_id"),
                 "installer_account_id": account["id"]}
                for job in jobs
            ])
            return jobs, datetime.now(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001 - fall back rather than show nothing
            pass

    rows = store.cached_jobs(account["id"])
    refreshed = min(
        (str(r.get("refreshed_at")) for r in rows if r.get("refreshed_at")),
        default=None,
    )
    return [row["data"] for row in rows], refreshed


def jobs_for_account(monday, store, account, record_view=True):
    """The portal response: fetch_jobs, grouped and counted.

    record_view=False is the admin preview: the 'viewed' audit event answers
    "did the installer actually look", so an admin previewing must not forge it.
    """
    jobs, refreshed_at = fetch_jobs(monday, store, account)

    action, waiting = [], []
    for job in jobs:
        (waiting if job.get("state") == "waiting" else action).append(job)

    action.sort(key=lambda j: -(j.get("overdue_days") or 0))

    if record_view:
        store.record_event(0, "viewed", installer_account_id=account["id"],
                           payload={"jobs": len(jobs)})

    stale = _is_stale(refreshed_at)
    return {
        "account": {
            "name": account["account_name"],
            "coordinator": account.get("coordinator_name"),
        },
        "action_needed": action,
        "waiting": waiting,
        "overdue": sum(
            1 for j in action
            if (j.get("overdue_days") or 0) > config.SLA_BUSINESS_DAYS
        ),
        "sla_days": config.SLA_BUSINESS_DAYS,
        "refreshed_at": refreshed_at,
        "stale": stale,
    }


def _is_stale(refreshed_at):
    """More than an hour old — the portal shows "Updated 3h ago"."""
    if not refreshed_at:
        return True
    try:
        when = datetime.fromisoformat(str(refreshed_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > timedelta(hours=1)


def install_items(monday, item, cols=None, state=None):
    """One order → its uniform list of install-item jobs (Prompt 1).

    An order ingested since install items became universal carries one subitem
    per site — single-site orders included — and each subitem is one job. An
    order from before that carries none, and the order row itself stands in as
    its single install item. Callers never branch on which case it was.
    """
    try:
        subs = monday.subitems(item["id"]) or []
    except Exception:  # noqa: BLE001 - an unreadable subitem list ≠ no jobs
        subs = []
    if not subs:
        return [_shape(item, cols, state=state)]
    return [_shape(item, cols, sub, state=state) for sub in subs]


# Install items are often created bare — monday refuses the column values when
# the subitem board doesn't mirror the parent's IDs — so the per-site quantity
# survives only in the name mapping.subitem_name() built: "GPS Tech — 7 units".
UNITS_IN_NAME = re.compile(r"—\s*(\d+)\s*units?\s*$")


def _shape(item, cols=None, sub=None, state=None):
    """One install item → the fields the portal card renders.

    `sub` is the install subitem when the order carries them. Its own values
    win; the order row fills anything the subitem was created without, which
    is everything when monday refused the subitem's column values. `state` is
    the installer account's state, driving which public holidays the SLA age
    skips.
    """
    cols = cols or config.COLUMNS
    values = {c["id"]: c for c in item.get("column_values", [])}
    sub_values = {c["id"]: c for c in (sub or {}).get("column_values", [])}

    def text(key):
        column_id = cols.get(key)
        if not column_id:
            return None
        own = sub_values.get(column_id, {}).get("text")
        return own or values.get(column_id, {}).get("text")

    dispatched = text("order_date")
    contacted = text("contacted_date")
    booked = text("booked_date")

    units_total = _int(text("units_total"))
    if sub is not None:
        column_id = cols.get("units_total")
        own = _int(sub_values.get(column_id, {}).get("text")) if column_id else None
        named = UNITS_IN_NAME.search(sub.get("name") or "")
        units_total = own or (int(named.group(1)) if named else None) or units_total
    units_installed = _int(text("units_installed"))

    if not dispatched:
        job_state = "waiting"
    elif booked:
        job_state = "booked"
    elif contacted:
        job_state = "contacted"
    else:
        job_state = "new"

    return {
        "item_id": item["id"],
        # The install item's own identity. Write-backs still target item_id —
        # the portal's columns live on the orders board — but caching, React
        # keys and the coming SLA/SMS work key on this.
        "install_id": (sub or {}).get("id") or item["id"],
        "subitem_id": (sub or {}).get("id"),
        "site": (sub or {}).get("name"),
        "name": item["name"],
        "customer": item["name"].split("=")[0].strip(),
        "site_contact": text("site_contact"),
        "site_phone": text("site_phone"),
        "site_address": text("site_address"),
        "opportunity_id": text("opportunity_id"),
        "installer": text("installer"),
        "dispatched": dispatched,
        "contacted": contacted,
        "booked": booked,
        "scheduled": text("scheduled_install_date"),
        "units_total": units_total,
        "units_installed": units_installed or 0,
        "state": job_state,
        "overdue_days": (
            business_days_since(dispatched, state=state or "NSW")
            if not contacted else None
        ),
        # Only show the progress counter on genuinely multi-unit jobs (§6.4).
        "show_counter": bool(units_total and units_total > 1),
    }


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Cache maintenance — the belt and braces behind the live-read-first design
# --------------------------------------------------------------------------

def refresh_item(monday, store, item_id):
    """Re-pull one order and overwrite its install items' cache rows.

    Called by the column webhooks (dispatch date, status, installer) so a
    direct edit in monday reaches the portal's fallback path within seconds
    rather than at the next portal load. Keyed exactly like fetch_jobs — one
    row per install item — so the two writers never fight over row identity.
    """
    item = monday.item(item_id)
    if not item:
        store.delete_cached_job(int(item_id))
        return {"ok": True, "item_id": item_id, "cached": False,
                "reason": "item no longer exists"}

    cols = columns_mod.resolved(monday)
    account = _account_for_item(store, item, cols)
    jobs = install_items(monday, item, cols, state=(account or {}).get("state"))
    store.cache_jobs([
        {"monday_item_id": job["install_id"], "data": job,
         "monday_subitem_id": job.get("subitem_id"),
         "installer_account_id": account["id"] if account else None}
        for job in jobs
    ])
    return {"ok": True, "item_id": item_id, "cached": True,
            "jobs": len(jobs),
            "account": account["account_name"] if account else None}


def _linked_account_names(item, cols):
    """The account names on an item's Installer connect column, lowercased.

    A connect column's text is the linked items' names, comma-joined when
    someone links more than one — split so a legitimate account is never
    denied because a second one shares the column.
    """
    values = {c["id"]: c for c in item.get("column_values", [])}
    column_id = cols.get("installer")
    text = (values.get(column_id, {}).get("text") or "") if column_id else ""
    return {n.strip().lower() for n in text.split(",") if n.strip()}


def _account_for_item(store, item, cols):
    """The installer account an item is allocated to, by the Installer column.

    Name match against the synced accounts — the portal's own query uses the
    same value, so the two can never disagree about whose job this is.
    """
    names = _linked_account_names(item, cols)
    if not names:
        return None
    for account in store.installer_accounts():
        if str(account["account_name"]).strip().lower() in names:
            return account
    return None


def require_ownership(monday, store, account, item_id):
    """Prove server-side that this job is allocated to this account, or raise.

    The portal authenticates the ACCOUNT (magic link or login); this is the
    other half — the item_id in the request body is client input, and without
    this check any valid link could write to any row on the orders board.
    Live monday (the Installer column) is the authority; when monday can't
    answer, the account's own cache rows decide — and silence denies, because
    a write to a job we cannot prove is yours must not happen.
    """
    denied = PermissionError("this job isn't allocated to your account")
    try:
        item = monday.item(item_id)
    except Exception:  # noqa: BLE001 - fall back to the cache
        item = None
    if item is not None:
        names = _linked_account_names(item, columns_mod.resolved(monday))
        if str(account["account_name"]).strip().lower() in names:
            return
        raise denied
    for row in store.cached_jobs(account["id"]):
        data = row.get("data") or {}
        if (str(data.get("item_id")) == str(item_id)
                or str(row.get("monday_item_id")) == str(item_id)):
            return
    raise denied


def resync(monday, store):
    """Re-pull every open job for every active installer account.

    The hourly cron behind the portal's fallback path. Overwrites jobs_cache;
    the live-read-first design is unchanged.
    """
    accounts = store.installer_accounts()
    synced, errors = 0, []
    for account in accounts:
        try:
            jobs, refreshed_at = fetch_jobs(monday, store, account)
            if refreshed_at is None:
                errors.append(f"{account['account_name']}: monday unreachable")
                continue
            synced += len(jobs)
        except Exception as exc:  # noqa: BLE001 - one account must not stop the rest
            errors.append(f"{account['account_name']}: {exc}")
    return {"ok": not errors, "accounts": len(accounts),
            "jobs": synced, "errors": errors}


# --------------------------------------------------------------------------
# Write-backs
# --------------------------------------------------------------------------

ACTIONS = {"contacted", "booked", "progress", "completed", "blocked"}


def apply_action(monday, store, account, item_id, action, value=None, note=None):
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")

    # The account is authenticated; the item_id is not — it is client input,
    # and every write-back must first prove the job is this account's.
    require_ownership(monday, store, account, item_id)

    cols = columns_mod.resolved(monday)
    today = date.today().isoformat()
    values = {}

    def put(key, encoded):
        column_id = cols.get(key)
        if column_id and encoded is not None:
            values[column_id] = encoded

    if action == "contacted":
        put("contacted_date", {"date": today})

    elif action == "booked":
        put("booked_date", {"date": today})
        if value:
            put("scheduled_install_date", mapping.v_date(value))

    elif action == "progress":
        # One number: how many units are fitted so far. Entering the total does
        # NOT complete the job — fitting the last unit and finishing the job are
        # different events (§6.4).
        put("units_installed", mapping.v_number(value))
        put("progress_updated", {"date": today})

    elif action == "completed":
        put("progress_updated", {"date": today})

    if values:
        monday.set_columns(config.ORDERS_BOARD_ID, item_id, values)

    if action in ("completed", "blocked") or note:
        monday.post_update(item_id, _update_text(account, action, value, note))

    store.record_event(
        int(item_id), action,
        installer_account_id=account["id"],
        payload={"value": value, "note": note},
    )

    # The cache must not contradict what the installer just did.
    try:
        refresh_item(monday, store, item_id)
    except Exception:  # noqa: BLE001 - the write-back already landed
        pass

    return {"ok": True, "item_id": item_id, "action": action, "written": len(values)}


def _update_text(account, action, value, note):
    who = account.get("coordinator_name") or account["account_name"]
    headline = {
        "contacted": f"☎ {who} contacted the customer",
        "booked": f"📅 {who} booked the install" + (f" for {value}" if value else ""),
        "progress": f"🔧 {who} reported {value} units fitted",
        "completed": f"✅ {who} marked this install complete",
        "blocked": f"⚠️ {who} cannot proceed",
    }[action]
    return f"{headline}<br>{note}" if note else headline
