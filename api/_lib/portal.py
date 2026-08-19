"""Installer portal backend.

Phase 1 builds the foundation, not the product (brief §9). What is here: the job
list an account can see, and the four write-backs the prototypes already show
buttons for. What is not here: SMS, SLA escalation, assigned-technician.

The shape follows the prototypes exactly — jobs are grouped into "Action needed"
and "Waiting on hardware", and each carries the SLA age in business days that
drives the red chip.

The unit of work everywhere in here is the INSTALL ITEM (finalisation Prompt 1):
one per site, single-site orders included. The ingest creates them as subitems;
orders that predate that get one synthesized from the order row. Either way,
everything downstream of install_items() sees the same shape.
"""

import re
from datetime import date, datetime, timedelta

from . import columns as columns_mod
from . import config, mapping

SLA_BUSINESS_DAYS = 2


def business_days_since(when):
    if not when:
        return None
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when[:10]).date()
        except ValueError:
            return None
    if isinstance(when, datetime):
        when = when.date()
    days, cursor = 0, when
    today = date.today()
    while cursor < today:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def jobs_for_account(monday, store, account, record_view=True):
    """Every open job allocated to this installer account.

    Reads monday live — allocation changes there and the portal must reflect it
    (§6.2). The cache is a fallback for when monday is slow or rate-limiting,
    not the primary path, because a stale job list sends someone to a site that
    was reallocated last week.

    record_view=False is the admin preview: the 'viewed' audit event answers
    "did the installer actually look", so an admin previewing must not forge it.
    """
    cols = columns_mod.resolved(monday)
    column_id = cols.get("installer")
    jobs = []

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
            jobs = []
            for item in items:
                jobs.extend(install_items(monday, item, cols))
            for job in jobs:
                # Keyed by the install item's own id — two sites of one order
                # must not overwrite each other in the cache.
                store.cache_job(
                    job["install_id"], job, installer_account_id=account["id"]
                )
        except Exception:  # noqa: BLE001 - fall back rather than show nothing
            jobs = [row["data"] for row in store.cached_jobs(account["id"])]
    else:
        jobs = [row["data"] for row in store.cached_jobs(account["id"])]

    action, waiting = [], []
    for job in jobs:
        (waiting if job.get("state") == "waiting" else action).append(job)

    action.sort(key=lambda j: -(j.get("overdue_days") or 0))

    if record_view:
        store.record_event(0, "viewed", installer_account_id=account["id"],
                           payload={"jobs": len(jobs)})

    return {
        "account": {
            "name": account["account_name"],
            "coordinator": account.get("coordinator_name"),
        },
        "action_needed": action,
        "waiting": waiting,
        "overdue": sum(1 for j in action if (j.get("overdue_days") or 0) > SLA_BUSINESS_DAYS),
    }


def install_items(monday, item, cols=None):
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
        return [_shape(item, cols)]
    return [_shape(item, cols, sub) for sub in subs]


# Install items are often created bare — monday refuses the column values when
# the subitem board doesn't mirror the parent's IDs — so the per-site quantity
# survives only in the name mapping.subitem_name() built: "GPS Tech — 7 units".
UNITS_IN_NAME = re.compile(r"—\s*(\d+)\s*units?\s*$")


def _shape(item, cols=None, sub=None):
    """One install item → the fields the portal card renders.

    `sub` is the install subitem when the order carries them. Its own values
    win; the order row fills anything the subitem was created without, which
    is everything when monday refused the subitem's column values.
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
        state = "waiting"
    elif booked:
        state = "booked"
    elif contacted:
        state = "contacted"
    else:
        state = "new"

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
        "dispatched": dispatched,
        "contacted": contacted,
        "booked": booked,
        "scheduled": text("scheduled_install_date"),
        "units_total": units_total,
        "units_installed": units_installed or 0,
        "state": state,
        "overdue_days": business_days_since(dispatched) if not contacted else None,
        # Only show the progress counter on genuinely multi-unit jobs (§6.4).
        "show_counter": bool(units_total and units_total > 1),
    }


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


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
