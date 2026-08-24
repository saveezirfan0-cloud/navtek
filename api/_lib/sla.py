"""The SLA engine.

Rule: an installer must contact the customer within SLA_BUSINESS_DAYS
(default 2) business days of hardware dispatch — business days per the
installer account's state, holidays included (holidays_au.py).

Two hard guards sit in front of everything here:

* **The go-live cutoff.** Only jobs whose dispatch date is on or after
  SLA_GO_LIVE_DATE ever enter the engine. The board carries jobs up to 212
  business days overdue; a sweep without this cutoff blasts every installer
  with months-old reminders on day one and kills trust in the first hour.
  Everything older is historical backlog Navtek reconciles by hand. No cutoff
  configured means the engine is OFF, not "no cutoff".

* **Shadow mode.** SLA_NOTIFICATIONS_ENABLED defaults false: the sweep still
  runs, computes ages, records breaches — and only LOGS what it would send or
  escalate. It goes live after a week of real orders' shadow output has been
  read and believed.

The daily sweep is called by a Vercel cron via POST /api/py/sla/sweep.
"""

from datetime import date

from . import clock, columns as columns_mod
from . import config, mapping, notify, portal

ESCALATION_LABEL = "6.1 Installer Esc."


def sweep(monday, store, today=None):
    """One pass over every active account's open jobs.

    Returns what it found and what it did (or would do, in shadow mode).
    """
    go_live = config.sla_go_live()
    if not go_live:
        return {
            "ok": False, "swept": False,
            "reason": (
                "SLA_GO_LIVE_DATE is not set (or not an ISO date). The sweep "
                "refuses to run without the cutoff — without it, day one "
                "texts every installer about months-old backlog."
            ),
        }

    today = today or clock.today()
    shadow = not config.SLA_NOTIFICATIONS_ENABLED
    breaches, checked = [], 0

    for account in store.installer_accounts():
        jobs, _ = portal.fetch_jobs(monday, store, account)
        state = account.get("state") or "NSW"
        for job in jobs:
            checked += 1
            entry = _assess(store, account, job, go_live, state, today)
            if not entry:
                continue
            entry["actions"] = _act(monday, store, account, job, entry, shadow)
            breaches.append(entry)

    return {
        "ok": True, "swept": True, "shadow": shadow,
        "go_live": go_live.isoformat(),
        "sla_business_days": config.SLA_BUSINESS_DAYS,
        "jobs_checked": checked,
        "breaches": breaches,
    }


def preview(monday, store, today=None):
    """The engine's state, read-only — the SLA console's data.

    Every job inside the engine's window (dispatched on/after go-live, not
    yet contacted) with its clock and countdown, worst first. Unlike sweep(),
    this records nothing and claims nothing, so refreshing the console can't
    consume the dedup keys the real sweep depends on.
    """
    go_live = config.sla_go_live()
    mode = ("off" if not go_live
            else "live" if config.SLA_NOTIFICATIONS_ENABLED
            else "shadow")
    today = today or clock.today()
    jobs_out, checked = [], 0

    if go_live:
        for account in store.installer_accounts():
            jobs, _ = portal.fetch_jobs(monday, store, account)
            state = account.get("state") or "NSW"
            for job in jobs:
                checked += 1
                dispatched = portal._as_date(job.get("dispatched"))
                if (not dispatched or dispatched < go_live
                        or dispatched > today or job.get("contacted")):
                    continue
                start = portal.sla_clock_start(store, job["item_id"], dispatched)
                age = portal.business_days_since(start, state=state, today=today) or 0
                days_left = config.SLA_BUSINESS_DAYS - age
                jobs_out.append({
                    "item_id": job["item_id"],
                    "customer": job.get("customer"),
                    "account": account["account_name"],
                    "state": state,
                    "dispatched": dispatched.isoformat(),
                    "clock_start": start.isoformat(),
                    "sla_age_business_days": age,
                    "days_left": days_left,
                    "status": ("breached" if days_left < 0
                               else "due_now" if days_left == 0
                               else "on_track"),
                })

    jobs_out.sort(key=lambda j: j["days_left"])
    return {
        "mode": mode,
        "go_live": go_live.isoformat() if go_live else None,
        "sla_business_days": config.SLA_BUSINESS_DAYS,
        "notifications_enabled": config.SLA_NOTIFICATIONS_ENABLED,
        "jobs_checked": checked,
        "jobs": jobs_out,
    }


def _assess(store, account, job, go_live, state, today):
    """Is this job in breach? None, or the breach record."""
    dispatched = portal._as_date(job.get("dispatched"))
    if not dispatched:
        return None                      # nothing to install yet
    if dispatched < go_live:
        return None                      # historical backlog — never enters
    if dispatched > today:
        return None                      # future-dated dispatch
    if job.get("contacted"):
        return None                      # the SLA is about first contact

    start = portal.sla_clock_start(store, job["item_id"], dispatched)
    age = portal.business_days_since(start, state=state, today=today)
    if age is None or age <= config.SLA_BUSINESS_DAYS:
        return None

    return {
        "item_id": job["item_id"],
        "customer": job.get("customer"),
        "account": account["account_name"],
        "state": state,
        "dispatched": dispatched.isoformat(),
        "clock_start": start.isoformat(),
        "sla_age_business_days": age,
    }


def _act(monday, store, account, job, entry, shadow):
    """Record the breach, and escalate — or log what would happen.

    Escalation (§6.1): a breach with no installer contact sets the order's
    status to the existing, currently-unused "6.1 Installer Esc." label on the
    orders board — it already shows in the views Navtek staff use daily, so no
    new view is needed. Once per breach: a fresh clock (a reallocation) is a
    fresh breach, so the dedupe key carries the clock start date.
    """
    actions = []
    item_id = int(job["item_id"])

    # The breach itself is recorded in every mode — that IS the sweep's job.
    # Once per breach: the key carries the clock start, so a fresh clock
    # (a reallocation) is a fresh breach.
    if store.claim_notification(item_id, f"breach:{entry['clock_start']}",
                                payload=entry):
        store.record_event(item_id, "sla_breach",
                           installer_account_id=account["id"], payload=entry)
        actions.append("breach recorded")

    escalation_key = f"escalated:{entry['clock_start']}"

    if shadow:
        already = store.was_notified(item_id, escalation_key)
        actions.append(
            f"shadow: would escalate to '{ESCALATION_LABEL}' and remind "
            f"{account['account_name']}"
            if not already else "shadow: already escalated this breach"
        )
        print(f"[sla:shadow] {entry['account']} / {entry['customer']} "
              f"({item_id}): {entry['sla_age_business_days']} business days "
              f"without contact — {actions[-1]}")
        return actions

    if store.was_notified(item_id, escalation_key):
        actions.append("already escalated this breach")
    else:
        # The claim is taken only AFTER the status write lands. A missing
        # column or label is a configuration problem someone will fix; a claim
        # consumed on the failed attempt would stop the escalation ever firing
        # once they do.
        cols = columns_mod.resolved(monday)
        column_id = cols.get("order_status")
        if not column_id:
            actions.append("no order status column found — escalation label not written")
            return actions

        values = {column_id: mapping.v_status(ESCALATION_LABEL)}
        try:
            labels = columns_mod.status_labels(monday)
            values, dropped = mapping.align_status_values(values, labels)
        except Exception:  # noqa: BLE001 - write unaligned rather than not at all
            dropped = []
        if dropped:
            actions.append(
                f"'{ESCALATION_LABEL}' is not a label on the status column — not written"
            )
            return actions

        monday.set_columns(config.ORDERS_BOARD_ID, item_id, values)
        store.claim_notification(item_id, escalation_key, payload=entry)
        store.record_event(item_id, "escalated",
                           installer_account_id=account["id"], payload=entry)
        actions.append(f"status set to '{ESCALATION_LABEL}'")

    # The breach SMS rides the same allocation pipeline — one send per
    # (item, account), dispatched-and-assigned rule already proven true here.
    reminded = notify.send_breach_reminder(store, account, job, entry)
    if reminded:
        actions.append("breach reminder SMS sent")
    return actions
