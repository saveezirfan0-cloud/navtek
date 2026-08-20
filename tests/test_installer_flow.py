"""The installer workflow: install items, the SLA engine, SMS, reallocation.

Same posture as test_ingest.py — real modules against a fake monday and a fake
database, no network. Each test encodes one rule from the finalisation
prompts, most of which exist because the failure mode is an SMS to the wrong
person at the wrong time about the wrong job.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

import json  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from _lib import columns as columns_mod  # noqa: E402
from _lib import config, holidays_au, notify, portal, sla, sms  # noqa: E402

from test_ingest import AGB, KANE, SOUTHERN, FakeMonday, blob, run  # noqa: E402

BOARD_ID = 99426505553

# The orders board as the installer flow sees it: the app's columns, the
# Installer connect column, and the board's own working Status column carrying
# the existing (unused) 6.1 escalation label.
FLOW_COLUMNS = [
    {"id": "text_contact", "title": "Site Contact", "type": "text"},
    {"id": "phone_site", "title": "Site Phone", "type": "phone"},
    {"id": "text_addr", "title": "Site Address", "type": "text"},
    {"id": "numeric_units", "title": "Units Total", "type": "numbers"},
    {"id": "date_order", "title": "Order Date", "type": "date"},
    {"id": "date_contacted", "title": "Contacted Date", "type": "date"},
    {"id": "date_booked", "title": "Booked Date", "type": "date"},
    {"id": "connect_installer", "title": "Installer", "type": "board_relation"},
    {"id": "color_main", "title": "Status", "type": "status",
     "settings_str": json.dumps({"labels": {
         "1": "1. New Order", "2": "6.1 Installer Esc.", "3": "7. Complete"}})},
]

ACCOUNT_A = {
    "id": "acc-a", "monday_item_id": 111, "account_name": "GPS Tech",
    "coordinator_name": "Gia", "coordinator_mobile": "+61400000001",
    "portal_token": "tok-a", "state": "NSW", "active": True,
}
ACCOUNT_B = {
    "id": "acc-b", "monday_item_id": 222, "account_name": "Dan Wells",
    "coordinator_name": "Dan", "coordinator_mobile": "+61400000002",
    "portal_token": "tok-b", "state": "VIC", "active": True,
}


def make_item(item_id, name="ACME = 4 x VT202", installer=None, dispatched=None,
              contacted=None, units=4, address="12 Example St, Parramatta, NSW 2150"):
    def value(column_id, text):
        return {"id": column_id, "type": "any", "text": text, "value": None}
    return {
        "id": str(item_id),
        "name": name,
        "column_values": [
            value("connect_installer", installer),
            value("date_order", dispatched),
            value("date_contacted", contacted),
            value("numeric_units", str(units) if units else None),
            value("text_addr", address),
            value("text_contact", "Site Person"),
            value("phone_site", "0400 000 000"),
        ],
    }


class FlowMonday:
    """Just enough of monday for the portal, the sweep and the webhooks."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.written = []   # (item_id, values) from set_columns

    def board_columns(self, board_id):
        return FLOW_COLUMNS

    def gql(self, query, variables=None, retries=3):
        if "items_page_by_column_values" in query:
            wanted = (variables or {}).get("v", [None])[0]
            found = [i for i in self.items
                     if _text(i, "connect_installer") == wanted]
            return {"items_page_by_column_values": {"items": found}}
        raise AssertionError(f"unexpected gql in test: {query[:80]}")

    def subitems(self, item_id):
        # Orders in these tests carry no install subitems, so the order row
        # stands in as its single install item (portal.install_items).
        return []

    def item(self, item_id):
        for candidate in self.items:
            if str(candidate["id"]) == str(item_id):
                return candidate
        return None

    def set_columns(self, board_id, item_id, values):
        self.written.append((str(item_id), values))
        return {}

    def post_update(self, item_id, body):
        return "1"


def _text(item, column_id):
    for value in item["column_values"]:
        if value["id"] == column_id:
            return value["text"]
    return None


class FlowStore:
    """In-memory stand-in for Store: accounts, notifications, events, cache."""

    enabled = True
    degraded = None

    def __init__(self, accounts=(), now=None):
        self.accounts = list(accounts)
        self.notifications = {}
        self.events = []
        self.cache = {}
        self.now = now or datetime.now(timezone.utc)

    def installer_accounts(self, active_only=True):
        return [a for a in self.accounts if a.get("active") or not active_only]

    def cache_job(self, monday_item_id, data, installer_account_id=None, **kw):
        self.cache[int(monday_item_id)] = {
            "monday_item_id": int(monday_item_id),
            "data": data,
            "installer_account_id": installer_account_id,
            "refreshed_at": self.now.isoformat(),
        }

    def cache_jobs(self, rows):
        for row in rows:
            self.cache_job(row["monday_item_id"], row["data"],
                           row.get("installer_account_id"))

    def cached_jobs(self, installer_account_id):
        return [row for row in self.cache.values()
                if row["installer_account_id"] == installer_account_id]

    def delete_cached_job(self, monday_item_id):
        self.cache.pop(int(monday_item_id), None)

    def record_event(self, monday_item_id, action, **fields):
        self.events.append({
            "monday_item_id": monday_item_id, "action": action,
            "created_at": self.now.isoformat(), **fields,
        })

    def latest_event(self, monday_item_id, action):
        for event in reversed(self.events):
            if (event["monday_item_id"] == monday_item_id
                    and event["action"] == action):
                return event
        return None

    def claim_notification(self, monday_item_id, kind, payload=None):
        key = (int(monday_item_id), kind)
        if key in self.notifications:
            return False
        self.notifications[key] = payload or {}
        return True

    def was_notified(self, monday_item_id, kind):
        return (int(monday_item_id), kind) in self.notifications

    def account_has_login(self, account_id):
        return False


@pytest.fixture(autouse=True)
def _flow_env(monkeypatch):
    """Fresh column cache, empty SMS outbox, SLA live from 1 Aug 2026."""
    columns_mod.clear_cache()
    sms.SENT.clear()
    monkeypatch.setattr(config, "ORDERS_BOARD_ID", BOARD_ID)
    monkeypatch.setattr(config, "SLA_GO_LIVE_DATE", "2026-08-01")
    monkeypatch.setattr(config, "SLA_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setenv("APP_URL", "https://navtek.example")
    yield
    columns_mod.clear_cache()
    sms.SENT.clear()


# ===========================================================================
# Prompt 1 — one Install item per site, for EVERY order that needs an install
# ===========================================================================

class SubitemRecorder(FakeMonday):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.subitem_values = []

    def create_subitem(self, parent, name, values=None):
        self.subitem_values.append(values or {})
        return super().create_subitem(parent, name, values)


def test_a_single_site_order_gets_no_subitems_the_row_is_the_job():
    """Damon's rule from the first live drops: subitems are per delivery
    SITE, and ~80% of orders are single-site — those get none. The portal
    already treats a subitem-less order as its own single install item."""
    monday = SubitemRecorder(blob(KANE))
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"]
    assert monday.subitems_created == []
    from _lib import portal
    items = portal.install_items(monday, monday.item("123"))
    assert len(items) == 1   # the order row stands in as the install item


@pytest.mark.parametrize("sample", [AGB, SOUTHERN])
def test_orders_with_no_install_create_no_install_items(sample):
    result, monday, _ = run(sample)
    assert result["ok"]
    assert monday.subitems_created == []


def test_multi_site_orders_get_one_install_item_per_site():
    from _lib import mapping
    parsed = {
        "install_required": "Yes", "order_date": "July 2, 2026",
        "company": "QUALITYVEND",
        "multi_site": [{"company": "Site A", "qty": 4},
                       {"company": "Site B", "qty": 8}],
    }
    sites = mapping.install_sites(parsed)
    assert [s["company"] for s in sites] == ["Site A", "Site B"]
    # Single-site → NO install subitems; the order row is the job.
    assert mapping.install_sites({
        "install_required": "Yes", "order_date": "July 2, 2026",
        "company": "KANE", "multi_site": [],
    }) == []


def test_install_sites_is_empty_for_self_install():
    from _lib import mapping
    assert mapping.install_sites({"install_required": "Customer self-install",
                                  "company": "X"}) == []
    assert mapping.install_sites({"install_required": "No", "company": "X"}) == []


# ===========================================================================
# Prompt 6 — Australian business days, per state
# ===========================================================================

def test_melbourne_cup_day_counts_in_sydney_but_not_melbourne():
    # Mon 2 Nov 2026 → Thu 5 Nov 2026. Tue 3 Nov is Melbourne Cup Day.
    start, today = date(2026, 11, 2), date(2026, 11, 5)
    assert portal.business_days_since(start, state="NSW", today=today) == 3
    assert portal.business_days_since(start, state="VIC", today=today) == 2


def test_weekends_and_national_holidays_are_skipped():
    # Thu 24 Dec 2026 → Wed 30 Dec: Fri 25 = Christmas, Mon 28 = Boxing Day
    # substitute, weekend skipped → Tue 29 and Wed 30 only.
    assert portal.business_days_since(
        date(2026, 12, 24), state="NSW", today=date(2026, 12, 30)) == 2


def test_holiday_data_covers_this_year():
    """Fails after the last covered year, so someone extends holidays_au.py
    before the SLA clock silently counts holidays as working days."""
    assert date.today().year <= holidays_au.LAST_COVERED_YEAR
    for year in (holidays_au.LAST_COVERED_YEAR - 1, holidays_au.LAST_COVERED_YEAR):
        assert holidays_au.NATIONAL.get(year), f"no national data for {year}"
        for state in ("NSW", "VIC"):
            assert holidays_au.STATE[state].get(year), f"no {state} data for {year}"


def test_unknown_state_falls_back_to_national_holidays():
    assert holidays_au.holidays_for("QLD", 2026) == holidays_au.NATIONAL[2026]


# ===========================================================================
# Prompt 2 — the SLA sweep and its go-live cutoff
# ===========================================================================

def test_sweep_refuses_to_run_without_the_cutoff(monkeypatch):
    monkeypatch.setattr(config, "SLA_GO_LIVE_DATE", "")
    result = sla.sweep(FlowMonday(), FlowStore([ACCOUNT_A]))
    assert result["swept"] is False
    assert "SLA_GO_LIVE_DATE" in result["reason"]


def test_jobs_dispatched_before_the_cutoff_never_breach():
    # Dispatched a month before go-live and massively overdue: historical
    # backlog, reconciled by hand — the engine must never touch it.
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-07-01")])
    result = sla.sweep(monday, FlowStore([ACCOUNT_A]), today=date(2026, 8, 19))
    assert result["swept"] and result["breaches"] == []
    assert monday.written == []
    assert sms.SENT == []


def test_a_job_past_the_cutoff_breaches_on_business_day_three():
    # Dispatched Tue 4 Aug (after the 1 Aug go-live). On Thu 6 Aug it is
    # 2 business days old — inside SLA. On Fri 7 Aug, day 3 — breach.
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-04")])
    store = FlowStore([ACCOUNT_A])

    ok_day = sla.sweep(monday, store, today=date(2026, 8, 6))
    assert ok_day["breaches"] == []

    breach_day = sla.sweep(monday, store, today=date(2026, 8, 7))
    assert len(breach_day["breaches"]) == 1
    assert breach_day["breaches"][0]["sla_age_business_days"] == 3


def test_a_contacted_job_never_breaches():
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-04",
                                   contacted="2026-08-05")])
    result = sla.sweep(monday, FlowStore([ACCOUNT_A]), today=date(2026, 8, 28))
    assert result["breaches"] == []


def test_shadow_mode_records_but_touches_nothing(monkeypatch):
    monkeypatch.setattr(config, "SLA_NOTIFICATIONS_ENABLED", False)
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-04")])
    store = FlowStore([ACCOUNT_A])
    result = sla.sweep(monday, store, today=date(2026, 8, 14))
    assert result["shadow"] is True
    assert len(result["breaches"]) == 1
    assert any("would escalate" in a for a in result["breaches"][0]["actions"])
    assert monday.written == []          # no status write in shadow
    assert sms.SENT == []                # no SMS in shadow
    # But the breach itself IS recorded — that's the sweep's job.
    assert any(e["action"] == "sla_breach" for e in store.events)


# ===========================================================================
# Prompt 6 — escalation to the existing "6.1 Installer Esc." status
# ===========================================================================

def test_a_breach_escalates_once_with_the_boards_own_label():
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-04")])
    store = FlowStore([ACCOUNT_A])

    first = sla.sweep(monday, store, today=date(2026, 8, 14))
    assert len(first["breaches"]) == 1
    status_writes = [w for w in monday.written
                     if w[1].get("color_main") == {"label": "6.1 Installer Esc."}]
    assert len(status_writes) == 1
    assert any(e["action"] == "escalated" for e in store.events)

    # The next day's sweep sees the same breach and does not re-escalate.
    again = sla.sweep(monday, store, today=date(2026, 8, 17))
    status_writes = [w for w in monday.written
                     if w[1].get("color_main") == {"label": "6.1 Installer Esc."}]
    assert len(status_writes) == 1
    assert len([e for e in store.events if e["action"] == "escalated"]) == 1
    assert again["swept"]


# ===========================================================================
# Prompt 3 — the SMS rule: installer set AND dispatched, exactly once
# ===========================================================================

def test_installer_set_alone_sends_nothing():
    """Texting on installer-set alone chases hardware still in the warehouse."""
    monday = FlowMonday([make_item(1, installer="GPS Tech", dispatched=None)])
    outcome = notify.evaluate(monday, FlowStore([ACCOUNT_A]), 1,
                              today=date(2026, 8, 10))
    assert outcome["sent"] is False
    assert sms.SENT == []


def test_installer_then_dispatch_fires_on_the_dispatch():
    store = FlowStore([ACCOUNT_A])
    monday = FlowMonday([make_item(1, installer="GPS Tech", dispatched=None)])
    notify.evaluate(monday, store, 1, today=date(2026, 8, 10))
    assert sms.SENT == []

    monday.items = [make_item(1, installer="GPS Tech", dispatched="2026-08-10")]
    outcome = notify.evaluate(monday, store, 1, today=date(2026, 8, 10))
    assert outcome["sent"] is True
    assert len(sms.SENT) == 1
    assert sms.SENT[0]["to"] == "+61400000001"


def test_dispatch_then_installer_fires_on_the_allocation():
    store = FlowStore([ACCOUNT_A])
    monday = FlowMonday([make_item(1, installer=None, dispatched="2026-08-10")])
    outcome = notify.evaluate(monday, store, 1, today=date(2026, 8, 11))
    assert outcome["sent"] is False and sms.SENT == []

    monday.items = [make_item(1, installer="GPS Tech", dispatched="2026-08-10")]
    outcome = notify.evaluate(monday, store, 1, today=date(2026, 8, 11))
    assert outcome["sent"] is True
    assert len(sms.SENT) == 1


def test_a_retry_storm_sends_exactly_one_sms():
    store = FlowStore([ACCOUNT_A])
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-10")])
    for _ in range(5):
        notify.evaluate(monday, store, 1, today=date(2026, 8, 11))
    assert len(sms.SENT) == 1


def test_a_future_dispatch_date_does_not_fire():
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-09-01")])
    outcome = notify.evaluate(monday, FlowStore([ACCOUNT_A]), 1,
                              today=date(2026, 8, 11))
    assert outcome["sent"] is False and sms.SENT == []


def test_the_sms_names_the_job_and_carries_the_portal_link():
    store = FlowStore([ACCOUNT_A])
    monday = FlowMonday([make_item(1, name="ACME CIVIL = 4 x VT202",
                                   installer="GPS Tech",
                                   dispatched="2026-08-10")])
    notify.evaluate(monday, store, 1, today=date(2026, 8, 11))
    body = sms.SENT[0]["body"]
    assert "Gia" in body                       # coordinator, not the company
    assert "ACME CIVIL" in body                # customer
    assert "4 units" in body                   # unit count
    assert "Parramatta" in body                # suburb, not "NSW 2150"
    assert "https://navtek.example/j/tok-a" in body   # magic link


def test_pre_cutoff_dispatch_never_texts():
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-07-15")])
    outcome = notify.evaluate(monday, FlowStore([ACCOUNT_A]), 1,
                              today=date(2026, 8, 11))
    assert outcome["sent"] is False and sms.SENT == []


# ===========================================================================
# Prompt 4 — reallocation
# ===========================================================================

def realloc_payload(item_id=1, new=222, old=111):
    def links(monday_item_id):
        if monday_item_id is None:
            return {"linkedPulseIds": []}
        return {"linkedPulseIds": [{"linkedPulseId": monday_item_id}]}
    return {"event": {"pulseId": item_id,
                      "value": links(new), "previousValue": links(old)}}


def test_reallocation_texts_the_new_account_and_moves_the_cache():
    store = FlowStore([ACCOUNT_A, ACCOUNT_B])
    # The item now shows Dan Wells in monday (the change already happened).
    monday = FlowMonday([make_item(1, installer="Dan Wells",
                                   dispatched="2026-08-10")])
    result = notify.handle_installer_change(monday, store, realloc_payload(),
                                            today=date(2026, 8, 11))
    assert result["from"] == "GPS Tech" and result["to"] == "Dan Wells"
    # B is texted like a fresh allocation; A was never notified, so A hears
    # nothing.
    assert [s["to"] for s in sms.SENT] == ["+61400000002"]
    # The cache row belongs to B now — A's portal fallback can't show it.
    assert store.cache[1]["installer_account_id"] == "acc-b"
    assert store.cached_jobs("acc-a") == []
    assert any(e["action"] == "reallocated" for e in store.events)
    event = store.latest_event(1, "reallocated")
    assert event["payload"]["from_account"] == "GPS Tech"
    assert event["payload"]["to_account"] == "Dan Wells"


def test_the_old_account_is_told_only_if_it_had_been_notified():
    store = FlowStore([ACCOUNT_A, ACCOUNT_B])
    # A already got the allocation SMS for this job.
    store.claim_notification(1, "allocated:acc-a", {})
    monday = FlowMonday([make_item(1, installer="Dan Wells",
                                   dispatched="2026-08-10")])
    notify.handle_installer_change(monday, store, realloc_payload(),
                                   today=date(2026, 8, 11))
    tos = sorted(s["to"] for s in sms.SENT)
    assert tos == ["+61400000001", "+61400000002"]   # A's goodbye + B's hello
    goodbye = [s for s in sms.SENT if s["to"] == "+61400000001"][0]
    assert "reassigned" in goodbye["body"]


def test_reallocating_an_undispatched_item_notifies_nobody():
    store = FlowStore([ACCOUNT_A, ACCOUNT_B])
    store.claim_notification(1, "allocated:acc-a", {})
    monday = FlowMonday([make_item(1, installer="Dan Wells", dispatched=None)])
    result = notify.handle_installer_change(monday, store, realloc_payload(),
                                            today=date(2026, 8, 11))
    assert sms.SENT == []
    assert result["notified"] == []
    # The move itself is still on the record.
    assert any(e["action"] == "reallocated" for e in store.events)


def test_reallocation_restarts_the_sla_clock():
    """Being given a job today must not mean inheriting a 40-day breach."""
    store = FlowStore([ACCOUNT_A, ACCOUNT_B],
                      now=datetime(2026, 8, 18, tzinfo=timezone.utc))
    monday = FlowMonday([make_item(1, installer="Dan Wells",
                                   dispatched="2026-08-04")])
    notify.handle_installer_change(monday, store, realloc_payload(),
                                   today=date(2026, 8, 18))

    # Dispatch was 4 Aug — ten business days ago — but the clock now starts at
    # the 18 Aug reallocation: one business day old on the 19th, no breach.
    result = sla.sweep(monday, store, today=date(2026, 8, 19))
    assert result["breaches"] == []

    # Left uncontacted, the NEW clock breaches on its own day 3.
    result = sla.sweep(monday, store, today=date(2026, 8, 21))
    assert len(result["breaches"]) == 1
    assert result["breaches"][0]["clock_start"] == "2026-08-18"
    assert result["breaches"][0]["sla_age_business_days"] == 3


# ===========================================================================
# Prompt 5 — the portal cache stays honest
# ===========================================================================

def test_refresh_item_rewrites_the_cache_row():
    store = FlowStore([ACCOUNT_A])
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-10")])
    result = portal.refresh_item(monday, store, 1)
    assert result["cached"] and result["account"] == "GPS Tech"
    assert store.cache[1]["data"]["dispatched"] == "2026-08-10"

    # The dispatch date changes by direct edit in monday → webhook refreshes.
    monday.items = [make_item(1, installer="GPS Tech", dispatched="2026-08-12")]
    portal.refresh_item(monday, store, 1)
    assert store.cache[1]["data"]["dispatched"] == "2026-08-12"


def test_resync_repulls_every_active_account():
    store = FlowStore([ACCOUNT_A, ACCOUNT_B])
    monday = FlowMonday([
        make_item(1, installer="GPS Tech", dispatched="2026-08-10"),
        make_item(2, installer="Dan Wells", dispatched="2026-08-11"),
    ])
    result = portal.resync(monday, store)
    assert result["ok"] and result["jobs"] == 2
    assert store.cache[1]["installer_account_id"] == "acc-a"
    assert store.cache[2]["installer_account_id"] == "acc-b"


def test_a_live_read_is_fresh_and_a_cache_fallback_says_when():
    store = FlowStore([ACCOUNT_A],
                      now=datetime(2026, 8, 18, 3, 0, tzinfo=timezone.utc))
    monday = FlowMonday([make_item(1, installer="GPS Tech",
                                   dispatched="2026-08-10")])
    live = portal.jobs_for_account(monday, store, ACCOUNT_A)
    assert live["stale"] is False and live["refreshed_at"]

    class DownMonday(FlowMonday):
        def gql(self, *a, **kw):
            raise RuntimeError("monday is down")

    fallback = portal.jobs_for_account(DownMonday(), store, ACCOUNT_A)
    # The cached rows were written at 03:00 on 18 Aug 2026 — hours old.
    assert fallback["stale"] is True
    assert fallback["refreshed_at"] == store.now.isoformat()
    assert len(fallback["action_needed"]) == 1
