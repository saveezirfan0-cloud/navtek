"""SLA engine, with a hard go-live cutoff (FINALIZE prompt 2).

Only jobs whose dispatch date is on or after SLA_GO_LIVE_DATE ever enter the
engine. Everything older is historical backlog Navtek reconciles by hand —
the board carries jobs hundreds of business days overdue, and a sweep without
this cutoff would blast every installer with months-old reminders on day one
and kill trust in the first hour.

The sweep runs in shadow mode until SLA_NOTIFICATIONS_ENABLED is turned on:
it computes and RECORDS breaches (the notifications ledger makes each one
once-ever per job), and logs what it would have sent. Read a week of shadow
output against real orders before flipping the flag.
"""

from datetime import datetime

from . import config, portal, sms


def _parse_date(text):
    try:
        return datetime.fromisoformat(str(text)[:10]).date()
    except (TypeError, ValueError):
        return None


def breaches(jobs, state, cutoff, sla_days, today=None):
    """Which of these shaped portal jobs are in breach. Pure — fully testable.

    A job breaches when it was dispatched on/after the cutoff, nobody has
    contacted the customer, and more than `sla_days` business days (weekends
    and `state`'s public holidays excluded) have passed since dispatch.
    """
    out = []
    for job in jobs:
        dispatched = _parse_date(job.get("dispatched"))
        if not dispatched or dispatched < cutoff:
            continue  # pre-go-live backlog: never swept, never texted
        if job.get("contacted"):
            continue
        age = portal.business_days_since(dispatched, state, today)
        if age is not None and age > sla_days:
            out.append({
                "item_id": job["item_id"],
                "name": job.get("name"),
                "customer": job.get("customer"),
                "dispatched": job.get("dispatched"),
                "age_business_days": age,
                "state": state,
            })
    return out


def _message(account, breach):
    who = account.get("coordinator_name") or account.get("account_name")
    return (
        f"Navtek: {breach.get('customer') or breach.get('name')} was dispatched "
        f"{breach.get('dispatched')} and hasn't been contacted — "
        f"{breach['age_business_days']} business days. Please call them today. "
        f"({who})"
    )


def sweep(monday, store, today=None):
    """One pass over every active installer account's open jobs."""
    if not config.SLA_GO_LIVE_DATE:
        return {"enabled": False, "detail":
                "SLA_GO_LIVE_DATE is not set, so the sweep is off. Set it to "
                "the go-live date (YYYY-MM-DD) — only jobs dispatched on or "
                "after it are ever swept."}
    cutoff = _parse_date(config.SLA_GO_LIVE_DATE)
    if not cutoff:
        return {"enabled": False, "detail":
                f"SLA_GO_LIVE_DATE ({config.SLA_GO_LIVE_DATE!r}) is not a "
                f"date. Use YYYY-MM-DD."}

    checked, found, newly_recorded, would_send = 0, [], [], []
    for account in store.installer_accounts():
        data = portal.jobs_for_account(monday, store, account, record_view=False)
        jobs = data["action_needed"]  # waiting jobs have no dispatch date yet
        state = (account.get("state") or "NSW").upper()
        checked += len(jobs)
        for breach in breaches(jobs, state, cutoff, config.SLA_BUSINESS_DAYS, today):
            breach["account"] = account["account_name"]
            found.append(breach)
            # The ledger is the exactly-once guarantee: one row per (job,
            # kind), forever, checked by unique insert — retries, overlapping
            # sweeps and redeploys can't double-record or double-text.
            if not store.record_notification(breach["item_id"], "sla_breach", breach):
                continue
            newly_recorded.append(breach)
            message = _message(account, breach)
            to = account.get("coordinator_mobile")
            if config.SLA_NOTIFICATIONS_ENABLED:
                sms.send_sms(to, message)
            else:
                would_send.append({"to": to, "message": message})
                print(f"[sla shadow] would text {to}: {message}")

    return {
        "enabled": True,
        "cutoff": cutoff.isoformat(),
        "notifications_enabled": config.SLA_NOTIFICATIONS_ENABLED,
        "jobs_checked": checked,
        "breaches": found,
        "newly_recorded": newly_recorded,
        "would_send": would_send,
    }
