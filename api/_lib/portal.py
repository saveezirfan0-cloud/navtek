"""Installer portal backend.

What is here: the job list an account can see, the four write-backs the
prototypes show buttons for, and the cache plumbing that keeps the portal
honest when monday is slow or edited directly — a per-item refresh for the
column webhooks and a full resync for the hourly cron.

The shape follows the prototypes exactly — jobs are grouped into "Action needed"
and "Waiting on hardware", and each carries the SLA age in business days that
drives the red chip. Business days are Australian: weekends plus the public
holidays of the installer account's state (holidays_au.py).
"""

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
        try:
            raw = monday.gql(
                """
                query ($b: ID!, $c: String!, $v: [String]!) {
                  items_page_by_column_values (
                    board_id: $b, limit: 100,
                    columns: [{column_id: $c, column_values: $v}]
                  ) {
                    items { id name column_values { id type text value } }
                  }
                }
                """,
                {
                    "b": str(config.ORDERS_BOARD_ID),
                    "c": column_id,
                    "v": [str(account["account_name"])],
                },
            )
            items = (raw.get("items_page_by_column_values") or {}).get("items") or []
            jobs = [_shape(item, cols, state=account.get("state")) for item in items]
            for job in jobs:
                store.cache_job(
                    job["item_id"], job, installer_account_id=account["id"]
                )
            return jobs, datetime.now(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001 - fall back rather than show nothing
            pass

    rows = store.cached_jobs(account["id"])
    refreshed = min(
        (str(r.get("refreshed_at")) for r in rows if r.get("refreshed_at")),
        default=None,
    )
    return [row["data"] for row in rows], refreshed


def jobs_for_account(monday, store, account):
    jobs, refreshed_at = fetch_jobs(monday, store, account)

    action, waiting = [], []
    for job in jobs:
        (waiting if job.get("state") == "waiting" else action).append(job)

    action.sort(key=lambda j: -(j.get("overdue_days") or 0))

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


def _shape(item, cols=None, state=None):
    """One monday item → the uniform install-job object.

    Everything downstream — the portal card, the SLA sweep, the SMS trigger —
    reads this one shape; there is deliberately no single-site special case.
    """
    cols = cols or config.COLUMNS
    values = {c["id"]: c for c in item.get("column_values", [])}

    def text(key):
        column_id = cols.get(key)
        return values.get(column_id, {}).get("text") if column_id else None

    dispatched = text("order_date")
    contacted = text("contacted_date")
    booked = text("booked_date")

    units_total = _int(text("units_total"))
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
    """Re-pull one item and overwrite its cache row.

    Called by the column webhooks (dispatch date, status, installer) so a
    direct edit in monday reaches the portal's fallback path within seconds
    rather than at the next portal load.
    """
    item = monday.item(item_id)
    if not item:
        store.delete_cached_job(int(item_id))
        return {"ok": True, "item_id": item_id, "cached": False,
                "reason": "item no longer exists"}

    cols = columns_mod.resolved(monday)
    account = _account_for_item(store, item, cols)
    job = _shape(item, cols, state=(account or {}).get("state"))
    store.cache_job(
        int(item_id), job,
        installer_account_id=account["id"] if account else None,
    )
    return {"ok": True, "item_id": item_id, "cached": True,
            "account": account["account_name"] if account else None}


def _account_for_item(store, item, cols):
    """The installer account an item is allocated to, by the Installer column.

    Exact name match against the synced accounts — the portal's own query uses
    the same value, so the two can never disagree about whose job this is.
    """
    values = {c["id"]: c for c in item.get("column_values", [])}
    column_id = cols.get("installer")
    name = (values.get(column_id, {}).get("text") or "").strip() if column_id else ""
    if not name:
        return None
    for account in store.installer_accounts():
        if str(account["account_name"]).strip().lower() == name.lower():
            return account
    return None


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
