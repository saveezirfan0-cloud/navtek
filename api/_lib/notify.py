"""When an installer hears about a job, and what they hear.

THE rule (§6.2 / prompt 3), one condition with two parts: the allocation SMS
fires when **both** are true — the Installer column is set on the item, AND
the hardware is dispatched (dispatch date present and not in the future).
Whichever of the two happens second triggers the send. Never on installer-set
alone: that texts a coordinator about hardware still in the warehouse and
starts a clock on a job they can't do.

Exactly one send per (item, account): sends are claimed in the `notifications`
table with a unique insert BEFORE sending, so monday webhook retries and
re-edits can't double-text. The claim key carries the account, so a job
reallocated to a new company texts the new company exactly once too.

Everything respects the SLA go-live cutoff and the shadow-mode flag — see
sla.py for why both exist.
"""

from datetime import date

from . import clock, columns as columns_mod
from . import config, portal, sms


def _dispatched_date(job, today):
    """The job's dispatch date if it makes the job actionable, else None."""
    dispatched = portal._as_date(job.get("dispatched"))
    if not dispatched or dispatched > today:
        return None
    return dispatched


def evaluate(monday, store, item_id, today=None):
    """Check the both-parts rule for one item and send if it just became true.

    Called from every path that can flip either half: the Installer column
    webhook, the dispatch-date webhook, and the ingest of an eOrder that
    arrives with both already set. Safe to call any number of times — the
    notifications claim makes retries free.
    """
    today = today or clock.today()
    item = monday.item(item_id)
    if not item:
        return {"ok": True, "sent": False, "reason": "item no longer exists"}

    cols = columns_mod.resolved(monday)
    account = portal._account_for_item(store, item, cols)
    if not account:
        return {"ok": True, "sent": False, "reason": "no installer allocated"}

    job = portal._shape(item, cols, state=account.get("state"))
    return notify_allocation(store, account, job, today=today)


def notify_allocation(store, account, job, today=None):
    """Send the allocation SMS if the both-parts rule holds. Idempotent."""
    today = today or clock.today()
    item_id = int(job["item_id"])

    dispatched = _dispatched_date(job, today)
    if not dispatched:
        return {"ok": True, "sent": False,
                "reason": "hardware not dispatched yet — no SMS, no clock"}

    go_live = config.sla_go_live()
    if not go_live:
        return {"ok": True, "sent": False,
                "reason": "SLA_GO_LIVE_DATE not set — notifications are off"}
    if dispatched < go_live:
        return {"ok": True, "sent": False,
                "reason": "dispatched before the go-live cutoff — historical backlog"}

    body = _allocation_body(store, account, job)

    if not config.SLA_NOTIFICATIONS_ENABLED:
        print(f"[sms:shadow] would text {account['account_name']} "
              f"({account.get('coordinator_mobile') or 'no mobile'}): {body}")
        return {"ok": True, "sent": False, "shadow": True, "would_send": body}

    key = f"allocated:{account['id']}"
    if not store.claim_notification(item_id, key,
                                    payload={"account": account["account_name"]}):
        return {"ok": True, "sent": False, "reason": "already notified"}

    result = sms.send_sms(account.get("coordinator_mobile"), body)
    store.record_event(item_id, "sms_sent",
                       installer_account_id=account["id"],
                       payload={"kind": key, "body": body, **result})
    return {"ok": result.get("ok", False), "sent": result.get("ok", False),
            "body": body}


def _allocation_body(store, account, job):
    who = account.get("coordinator_name") or account["account_name"]
    units = job.get("units_total")
    where = _suburb(job.get("site_address"))
    parts = [
        f"Hi {who} — new Navtek install: {job.get('customer') or job.get('name')}",
    ]
    if where:
        parts.append(f"in {where}")
    if units:
        parts.append(f"{int(units)} unit{'s' if int(units) != 1 else ''}")
    link = _portal_link(store, account)
    text = ", ".join(parts)
    return f"{text}. Details and actions: {link}" if link else f"{text}."


_AU_STATES = {"nsw", "vic", "qld", "sa", "wa", "tas", "act", "nt"}


def _suburb(address):
    """The suburb out of a one-line address, for the SMS.

    "12 Example St, Parramatta, NSW 2150" → "Parramatta": trailing
    state/postcode segments are dropped, then the last remaining segment is
    the place. Best effort — a None here just shortens the message.
    """
    import re

    if not address:
        return None
    pieces = [p.strip() for p in re.split(r"[,\n]", str(address)) if p.strip()]
    while pieces:
        tokens = pieces[-1].replace(".", " ").split()
        if tokens and all(t.lower() in _AU_STATES or t.isdigit() for t in tokens):
            pieces.pop()
            continue
        break
    if not pieces:
        return None
    if len(pieces) >= 2:
        return pieces[-1]
    words = [w for w in pieces[0].split()
             if w.lower() not in _AU_STATES and not (w.isdigit() and len(w) == 4)]
    return words[-1] if words else None


def _portal_link(store, account):
    """The magic link — or /portal when the account holds a login."""
    base = config.portal_base_url()
    if not base:
        return None
    try:
        if store.account_has_login(account["id"]):
            return f"{base}/portal"
    except Exception:  # noqa: BLE001 - the magic link always works
        pass
    token = account.get("portal_token")
    return f"{base}/j/{token}" if token else f"{base}/portal"


def send_breach_reminder(store, account, job, entry):
    """The sweep's overdue reminder. Once per (item, account, breach)."""
    item_id = int(job["item_id"])
    key = f"breach_sms:{account['id']}:{entry['clock_start']}"
    if not store.claim_notification(item_id, key, payload=entry):
        return False
    who = account.get("coordinator_name") or account["account_name"]
    link = _portal_link(store, account)
    body = (
        f"Hi {who} — the {job.get('customer')} install is "
        f"{entry['sla_age_business_days']} business days old with no customer "
        f"contact logged. Please call them today."
    )
    if link:
        body += f" {link}"
    result = sms.send_sms(account.get("coordinator_mobile"), body)
    store.record_event(item_id, "sms_sent",
                       installer_account_id=account["id"],
                       payload={"kind": key, "body": body, **result})
    return result.get("ok", False)


# --------------------------------------------------------------------------
# Reallocation — the Installer column CHANGED from account A to account B
# --------------------------------------------------------------------------

def handle_installer_change(monday, store, payload, today=None):
    """monday webhook on the Installer column.

    The board shows reallocation happens constantly ("Now Dan Wells = SYD
    (was GPS TECH)"). When the column changes from A to B:

      1. the item leaves A's portal — the live query keys on the column value,
         and the cache row is rewritten here so the fallback path agrees;
      2. B gets the same SMS as a fresh allocation (dispatched-AND-assigned
         rule), and a fresh SLA clock from the reallocation date — recorded as
         a portal_events row that sla_clock_start() reads — not the original
         dispatch date: being given a job today must not mean inheriting
         someone else's 40-day breach;
      3. A gets a short "reassigned, nothing more to do" SMS ONLY if A had
         already been notified about the job;
      4. the change lands in portal_events with both accounts.

    An item that was never dispatched notifies nobody.
    """
    today = today or clock.today()
    event = payload.get("event") or {}
    item_id = event.get("pulseId")
    if not item_id:
        return {"ok": False, "reason": "no pulseId in payload"}

    accounts = store.installer_accounts()
    by_monday_id = {int(a["monday_item_id"]): a for a in accounts
                    if a.get("monday_item_id")}

    def linked(value):
        ids = ((value or {}).get("linkedPulseIds") or []) if isinstance(value, dict) else []
        found = []
        for entry in ids:
            linked_id = entry.get("linkedPulseId") if isinstance(entry, dict) else entry
            account = by_monday_id.get(int(linked_id)) if linked_id else None
            if account:
                found.append(account)
        return found

    new_accounts = linked(event.get("value"))
    old_accounts = linked(event.get("previousValue"))
    account_b = new_accounts[0] if new_accounts else None
    account_a = old_accounts[0] if old_accounts else None

    if account_a and account_b and account_a["id"] == account_b["id"]:
        return {"ok": True, "reason": "installer unchanged"}

    # Rewrite the cache row under the new owner (or drop it) FIRST — the item
    # must leave A's portal even if everything after this fails.
    result = {"ok": True, "item_id": item_id,
              "from": account_a["account_name"] if account_a else None,
              "to": account_b["account_name"] if account_b else None}
    try:
        refreshed = portal.refresh_item(monday, store, item_id)
    except Exception as exc:  # noqa: BLE001
        store.delete_cached_job(int(item_id))
        refreshed = {"ok": False, "reason": str(exc)}
    result["cache"] = refreshed

    item = monday.item(item_id)
    if not item:
        return {**result, "reason": "item no longer exists"}
    cols = columns_mod.resolved(monday)
    job = portal._shape(item, cols,
                        state=(account_b or account_a or {}).get("state"))

    store.record_event(
        int(item_id), "reallocated",
        installer_account_id=account_b["id"] if account_b else None,
        payload={
            "from_account_id": account_a["id"] if account_a else None,
            "from_account": account_a["account_name"] if account_a else None,
            "to_account_id": account_b["id"] if account_b else None,
            "to_account": account_b["account_name"] if account_b else None,
            "date": today.isoformat(),
        },
    )

    # Never dispatched → nobody is texted about anything.
    if not _dispatched_date(job, today):
        return {**result, "notified": [],
                "reason": "never dispatched — nobody notified"}

    notified = []
    if account_b:
        outcome = notify_allocation(store, account_b, job, today=today)
        if outcome.get("sent") or outcome.get("shadow"):
            notified.append(account_b["account_name"])

    if account_a and store.was_notified(int(item_id), f"allocated:{account_a['id']}"):
        if config.SLA_NOTIFICATIONS_ENABLED:
            key = f"reassigned:{account_a['id']}"
            if store.claim_notification(int(item_id), key,
                                        payload={"to": result["to"]}):
                who = account_a.get("coordinator_name") or account_a["account_name"]
                body = (f"Hi {who} — the {job.get('customer')} install has been "
                        f"reassigned. Nothing more to do on this one.")
                outcome = sms.send_sms(account_a.get("coordinator_mobile"), body)
                store.record_event(int(item_id), "sms_sent",
                                   installer_account_id=account_a["id"],
                                   payload={"kind": key, "body": body, **outcome})
                notified.append(account_a["account_name"])
        else:
            print(f"[sms:shadow] would tell {account_a['account_name']} the "
                  f"{job.get('customer')} install was reassigned")

    return {**result, "notified": notified}
