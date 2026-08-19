"""Acceptance criteria, as tests.

These run the real ingest path — real eOrder files, real parser, real mapping —
against a fake monday and a fake database. No network, no credentials.

Each test is one of the numbered acceptance criteria from the build brief.
They exist because every one of these was verified by hand at some point and
then quietly broken by a later change.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

import pytest  # noqa: E402

from _lib import columns as columns_mod  # noqa: E402
from _lib import config, ingest  # noqa: E402

SAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

KANE = "KANE_CIVIL_PTY_LTD__2_07_2026__EOrder.xlsx"
AGB = "AGB_INVESTMENT_GROUP_PTY_LTD__27_07_2026__EOrder.xlsx"
SOUTHERN = "Southern_Truck_Centre__2_07_2026__EOrder.xlsx"

BOARD_ID = 18426505553

# A board carrying the columns this app creates, as a test board would.
BOARD_COLUMNS = [
    {"id": "file_eorder", "title": "eOrder", "type": "file"},
    {"id": "color_status", "title": "eOrder Status", "type": "status"},
    {"id": "text_contact", "title": "Site Contact", "type": "text"},
    {"id": "phone_site", "title": "Site Phone", "type": "phone"},
    {"id": "email_site", "title": "Site Email", "type": "email"},
    {"id": "text_addr", "title": "Site Address", "type": "text"},
    {"id": "email_installer", "title": "Installer Email", "type": "email"},
    {"id": "color_install", "title": "Install Required?", "type": "status"},
    {"id": "numeric_units", "title": "Units Total", "type": "numbers"},
    {"id": "date_order", "title": "Order Date", "type": "date"},
]


class FakeMonday:
    def __init__(self, blob, existing_values=None, existing_name="x"):
        self.blob = blob
        self.written = {}
        self.updates = []
        self.renamed = None
        self.subitems_created = []
        self._existing = existing_values or {}
        self._name = existing_name
        self.downloads = 0

    def board_columns(self, board_id):
        return BOARD_COLUMNS

    def asset_urls(self, item_id, column_id):
        return [{"name": "eorder.xlsx", "public_url": "https://example/x"}]

    def download(self, url):
        self.downloads += 1
        return self.blob

    def item(self, item_id):
        return {
            "id": item_id, "name": self._name,
            "column_values": [{"id": k, "text": v} for k, v in self._existing.items()],
        }

    def find_by_column_value(self, *a):
        return []

    def set_columns(self, board_id, item_id, values):
        self.written.update(values)
        return {}

    def rename(self, board_id, item_id, name):
        self.renamed = name
        return {}

    def subitems(self, item_id):
        return []

    def create_subitem(self, parent, name, values=None):
        self.subitems_created.append(name)
        return {"id": str(len(self.subitems_created)), "board": {"id": "1"}}

    def post_update(self, item_id, body):
        self.updates.append(body)
        return "1"


class FakeStore:
    """Records what it was told, and can pretend the database is broken."""

    def __init__(self, broken=False):
        self.enabled = True
        self.broken = broken
        self.degraded = "simulated failure" if broken else None
        self.ingests = []
        self.unknown_reasons = []

    def already_ingested(self, opportunity_id, file_sha):
        if self.broken:
            return False
        return any(
            i["opportunity_id"] == opportunity_id and i["file_sha256"] == file_sha
            for i in self.ingests
        )

    def previous_parse(self, opportunity_id):
        if self.broken:
            return None
        for i in reversed(self.ingests):
            if i["opportunity_id"] == opportunity_id:
                return i["parsed"]
        return None

    def record_ingest(self, **fields):
        self.ingests.append(fields)
        return []

    def record_unknown_order_reason(self, reason, opp, name):
        self.unknown_reasons.append(reason)

    def installer_accounts(self, active_only=True):
        return []


def blob(filename):
    with open(os.path.join(SAMPLES, filename), "rb") as handle:
        return handle.read()


def run(filename, store=None, monday=None, existing=None):
    columns_mod.clear_cache()
    config.CONFIG_WARNINGS.clear()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = monday or FakeMonday(blob(filename), existing_values=existing)
    store = store if store is not None else FakeStore()
    payload = {"event": {"pulseId": 123, "boardId": BOARD_ID}}
    return ingest.handle_webhook(payload, monday, store), monday, store


# -- criterion 1: a new eOrder populates the row -----------------------------

def test_new_eorder_populates_and_reports_clean():
    result, monday, _ = run(KANE)
    assert result["ok"]
    assert result["status"] == "✅ Read", result.get("warnings")
    assert monday.renamed == "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    assert monday.written["text_contact"] == "Gerard Cahalan"
    assert monday.written["numeric_units"] == "44.0"
    assert monday.written["color_install"] == {"label": "Yes"}
    assert monday.written["date_order"] == {"date": "2026-07-02"}
    assert monday.written["color_status"] == {"label": "✅ Read"}
    assert "Gerard Cahalan" in monday.updates[0]


# -- criterion 2: the same file twice does nothing the second time -----------

def test_identical_file_dropped_twice_is_skipped():
    store = FakeStore()
    first, _, _ = run(KANE, store=store)
    assert first["ok"] and not first.get("skipped")

    second, monday2, _ = run(KANE, store=store)
    assert second["skipped"] == "identical file already read"
    assert monday2.written == {}
    assert monday2.renamed is None
    assert len(store.ingests) == 1


# -- criterion 3: a revised eOrder updates and says what changed -------------

def test_revised_eorder_reports_the_change():
    store = FakeStore()
    run(KANE, store=store)
    # Same order, fewer units — as a re-issued eOrder would be.
    store.ingests[0]["parsed"] = {
        **store.ingests[0]["parsed"],
        "lines": [{"qty": 10, "product": "RE 400 with TN360"}],
    }
    # A re-issued eOrder is a different file, so it hashes differently. Without
    # this the dedupe correctly treats the second drop as the same file.
    store.ingests[0]["file_sha256"] = "an-earlier-version-of-this-order"
    result, monday, _ = run(KANE, store=store)
    assert result["ok"]
    assert any("units" in c for c in result["changes"]), result["changes"]
    assert "Changed since the previous eOrder" in monday.updates[0]


# -- criterion 4: a non-eOrder fails cleanly and touches nothing else --------

def test_a_file_that_is_not_an_eorder_fails_without_writing():
    monday = FakeMonday(b"this is not a spreadsheet")
    result, monday, _ = run(KANE, monday=monday)
    assert not result["ok"]
    assert monday.renamed is None
    # Only the status column is touched, to say it failed.
    assert set(monday.written) <= {"color_status"}
    assert monday.written.get("color_status") == {"label": "❌ Failed"}
    assert "Could not read eOrder" in monday.updates[0]


# -- criterion 5: no installer named is normal, not an error -----------------

@pytest.mark.parametrize("sample", [AGB, SOUTHERN])
def test_orders_with_nothing_to_ship_read_clean(sample):
    result, monday, _ = run(sample)
    assert result["ok"]
    assert result["status"] == "✅ Read", result["warnings"]
    assert monday.written["color_install"] == {"label": "No"}


# -- ACV only on new-revenue reasons (§4.1) ---------------------------------

def test_acv_is_written_for_new_business_and_withheld_otherwise():
    _, kane, _ = run(KANE)
    _, southern, _ = run(SOUTHERN)
    # Board here has no ACV column, so assert on the parse instead.
    assert "ACV $18,144" in kane.updates[0]
    assert "ACV" not in southern.updates[0]


def test_unrecognised_order_reason_is_recorded_not_swallowed():
    store = FakeStore()
    run(SOUTHERN, store=store)
    # "Service Only Renewal" is not an ACV reason — it must be logged so a
    # silently-missing ACV can be traced later.
    assert "Service Only Renewal" in store.unknown_reasons


# -- human edits are never clobbered (§5) -----------------------------------

def test_a_value_already_in_monday_is_left_alone():
    _, monday, _ = run(KANE, existing={"text_contact": "Someone Corrected This"})
    assert "text_contact" not in monday.written
    assert monday.written["numeric_units"] == "44.0"


# -- the database is not on the critical path -------------------------------

def test_the_order_still_lands_when_the_database_is_broken():
    result, monday, _ = run(KANE, store=FakeStore(broken=True))
    assert result["ok"]
    assert result["status"] == "✅ Read"
    assert monday.renamed == "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    assert result["database"] == "simulated failure"


# -- the file is fetched once, and never cached -----------------------------

def test_the_asset_is_downloaded_exactly_once():
    _, monday, _ = run(KANE)
    assert monday.downloads == 1
