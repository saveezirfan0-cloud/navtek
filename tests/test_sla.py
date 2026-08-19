"""The SLA engine's two hard rules, as tests.

1. The go-live cutoff is absolute: a job dispatched before it never enters
   the engine no matter how overdue — the board carries jobs hundreds of
   business days late, and sweeping them would blast every installer with
   months-old reminders on day one.
2. Business days are AUSTRALIAN business days, per state: a VIC coordinator
   must not be chased on Melbourne Cup Day.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import sla  # noqa: E402
from _lib.holidays_au import LAST_COVERED_YEAR, holidays_for, is_business_day  # noqa: E402
from _lib.portal import business_days_since  # noqa: E402

CUTOFF = date(2026, 8, 1)
TODAY = date(2026, 8, 19)  # a Wednesday


def job(item_id="1", dispatched="2026-08-14", contacted=None, name="X = 4 x AT551"):
    return {"item_id": item_id, "name": name, "customer": "X",
            "dispatched": dispatched, "contacted": contacted}


# -- the cutoff --------------------------------------------------------------

def test_a_job_dispatched_before_the_cutoff_is_never_swept():
    # 2026-03-02 is ~120 business days before TODAY — exactly the backlog the
    # cutoff exists to protect.
    out = sla.breaches([job(dispatched="2026-03-02")], "NSW", CUTOFF, 2, TODAY)
    assert out == []


def test_a_job_after_the_cutoff_breaches_on_business_day_three():
    # Dispatched Friday 14 Aug; Mon 17, Tue 18, Wed 19 = 3 business days > 2.
    out = sla.breaches([job(dispatched="2026-08-14")], "NSW", CUTOFF, 2, TODAY)
    assert len(out) == 1
    assert out[0]["age_business_days"] == 3


def test_a_job_within_the_sla_does_not_breach():
    # Dispatched Monday 17 Aug; Tue 18, Wed 19 = 2 business days, not > 2.
    out = sla.breaches([job(dispatched="2026-08-17")], "NSW", CUTOFF, 2, TODAY)
    assert out == []


def test_a_contacted_job_never_breaches():
    out = sla.breaches(
        [job(dispatched="2026-08-10", contacted="2026-08-11")],
        "NSW", CUTOFF, 2, TODAY)
    assert out == []


def test_undispatched_and_unparseable_dates_are_skipped():
    out = sla.breaches(
        [job(dispatched=None), job(dispatched="not a date")],
        "NSW", CUTOFF, 2, TODAY)
    assert out == []


# -- Australian business days ------------------------------------------------

def test_melbourne_cup_counts_for_vic_but_not_nsw():
    # Dispatched Fri 30 Oct 2026; today Wed 4 Nov. Mon 2, Tue 3 (Melbourne
    # Cup), Wed 4: VIC counts 2 business days, NSW counts 3.
    dispatched = "2026-10-30"
    today = date(2026, 11, 4)
    assert business_days_since(dispatched, "VIC", today) == 2
    assert business_days_since(dispatched, "NSW", today) == 3
    # And so the same job breaches a 2-day SLA in NSW but not (yet) in VIC.
    cutoff = date(2026, 8, 1)
    assert sla.breaches([job(dispatched=dispatched)], "NSW", cutoff, 2, today)
    assert not sla.breaches([job(dispatched=dispatched)], "VIC", cutoff, 2, today)


def test_good_friday_is_nobodys_business_day():
    assert not is_business_day(date(2026, 4, 3), "NSW")
    assert not is_business_day(date(2026, 4, 3), "VIC")


def test_an_unknown_state_falls_back_to_nsw_rather_than_crashing():
    assert holidays_for("TAS") == holidays_for("NSW")
    assert holidays_for(None) == holidays_for("NSW")


def test_the_holiday_data_covers_this_year():
    """Fails once the calendar outruns the data, so someone extends
    holidays_au.py deliberately instead of the SLA quietly counting
    public holidays as business days."""
    assert date.today().year <= LAST_COVERED_YEAR, (
        f"holidays_au.py covers up to {LAST_COVERED_YEAR} — add "
        f"{date.today().year} (and next year) before relying on the SLA engine."
    )


# -- the sweep glue ----------------------------------------------------------

class SweepStore:
    def __init__(self):
        self.notified = []
        self.enabled = True
        self.degraded = None

    def installer_accounts(self, active_only=True):
        return [{"id": "a1", "account_name": "GPS Tech", "monday_item_id": 1,
                 "coordinator_name": "Jocelyn", "coordinator_mobile": "+614",
                 "state": "NSW"}]

    def record_notification(self, item_id, kind, payload=None):
        key = (str(item_id), kind)
        if key in self.notified:
            return False
        self.notified.append(key)
        return True

    def cache_jobs(self, rows):
        return []

    def cached_jobs(self, account_id):
        return []

    def record_event(self, *a, **k):
        return []


def test_the_sweep_is_off_until_the_go_live_date_is_set(monkeypatch):
    from _lib import config
    monkeypatch.setattr(config, "SLA_GO_LIVE_DATE", "")
    result = sla.sweep(monday=None, store=SweepStore())
    assert result["enabled"] is False
    assert "SLA_GO_LIVE_DATE" in result["detail"]


def test_the_sweep_records_each_breach_exactly_once(monkeypatch):
    from _lib import config, portal
    monkeypatch.setattr(config, "SLA_GO_LIVE_DATE", "2026-08-01")
    monkeypatch.setattr(config, "SLA_NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(
        portal, "jobs_for_account",
        lambda monday, store, account, record_view=True: {
            "action_needed": [job(dispatched="2026-08-14")],
            "waiting": [], "overdue": 1,
            "account": {"name": "GPS Tech", "coordinator": "Jocelyn"},
        })
    store = SweepStore()
    first = sla.sweep(monday=None, store=store, today=TODAY)
    assert len(first["breaches"]) == 1
    assert len(first["newly_recorded"]) == 1
    assert len(first["would_send"]) == 1          # shadow mode: logged, not sent
    assert first["notifications_enabled"] is False

    second = sla.sweep(monday=None, store=store, today=TODAY)
    assert len(second["breaches"]) == 1           # still in breach…
    assert second["newly_recorded"] == []         # …but never re-recorded
    assert second["would_send"] == []
