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

import json  # noqa: E402

import pytest  # noqa: E402

from _lib import columns as columns_mod  # noqa: E402
from _lib import config, ingest  # noqa: E402
from _lib.monday import MondayError  # noqa: E402

SAMPLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

KANE = "KANE_CIVIL_PTY_LTD__2_07_2026__EOrder.xlsx"
AGB = "AGB_INVESTMENT_GROUP_PTY_LTD__27_07_2026__EOrder.xlsx"
SOUTHERN = "Southern_Truck_Centre__2_07_2026__EOrder.xlsx"

BOARD_ID = 18426505553

# A board carrying the columns this app creates, as a test board would. The
# status labels are PLAIN — no emoji — because that is what monday actually
# produces when this app's bootstrap creates the column: the emoji in the
# requested labels are stripped. The production incident of 19 Aug 2026 was
# the code writing "✅ Read" against a board that only knows "Read".
BOARD_COLUMNS = [
    {"id": "file_eorder", "title": "eOrder", "type": "file"},
    {"id": "color_status", "title": "eOrder Status", "type": "status",
     "settings_str": json.dumps(
         {"labels": {"1": "Read", "2": "Check", "3": "Failed"}})},
    {"id": "text_contact", "title": "Site Contact", "type": "text"},
    {"id": "phone_site", "title": "Site Phone", "type": "phone"},
    {"id": "email_site", "title": "Site Email", "type": "email"},
    {"id": "text_addr", "title": "Site Address", "type": "text"},
    {"id": "email_installer", "title": "Installer Email", "type": "email"},
    {"id": "color_install", "title": "Install Required?", "type": "status",
     "settings_str": json.dumps(
         {"labels": {"1": "Yes", "2": "No", "3": "Customer self-install"}})},
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
        self._enforce_labels(values)
        self.written.update(values)
        return {}

    def _enforce_labels(self, values):
        """Real monday refuses the WHOLE mutation over one unknown label.

        The fake used to accept anything, which is why the emoji-label bug
        reached production with a green test suite.
        """
        labels = {
            c["id"]: list(json.loads(c["settings_str"])["labels"].values())
            for c in self.board_columns(None)
            if c["type"] == "status" and c.get("settings_str")
        }
        for column_id, value in values.items():
            allowed = labels.get(column_id)
            if (allowed is not None and isinstance(value, dict)
                    and "label" in value and value["label"] not in allowed):
                enum = ", ".join(
                    f"{i}: {label}" for i, label in enumerate(allowed, start=1))
                raise MondayError(
                    "This status label doesn't exist, possible statuses "
                    f"are: {{{enum}}}"
                )

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
        self.webhooks = []

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

    def record_webhook(self, **fields):
        self.webhooks.append(fields)
        return []

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
    # Written as the board's own label — the code's "✅ Read" aligned to "Read".
    assert monday.written["color_status"] == {"label": "Read"}
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
    # The skip must be VISIBLE — a person re-dropping the file sees Success in
    # monday's automation log, and without this notice concludes the app broke.
    assert any("Already read" in u for u in monday2.updates)


# -- every webhook delivery leaves a trace, including the invisible ones ------

def test_webhook_log_records_processed_and_skipped_outcomes():
    store = FakeStore()
    run(KANE, store=store)
    run(KANE, store=store)  # duplicate — skipped, absent from the ingest ledger

    assert [w["outcome"] for w in store.webhooks] == ["processed", "skipped"]
    skipped = store.webhooks[1]
    assert skipped["reason"] == "identical file already read"
    assert skipped["opportunity_id"] == "006VP00000agsnG"
    assert len(store.ingests) == 1  # the ledger itself still holds one read


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
    assert monday.written.get("color_status") == {"label": "Failed"}
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


# -- removals must not trigger anything (monday has no "uploaded" trigger) ---

def test_removing_a_file_does_nothing():
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = FakeMonday(blob(KANE))
    payload = {"event": {"pulseId": 123, "boardId": BOARD_ID,
                         "value": {"files": []}}}
    result = ingest.handle_webhook(payload, monday, FakeStore())
    # Success, so monday does not retry it as a failure.
    assert result["ok"]
    assert "removed" in result["skipped"]
    assert monday.written == {}
    assert monday.renamed is None
    assert monday.updates == []
    assert monday.downloads == 0


def test_an_empty_file_column_does_nothing():
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID

    class NoFiles(FakeMonday):
        def asset_urls(self, item_id, column_id):
            return []

    monday = NoFiles(blob(KANE))
    result = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": BOARD_ID}}, monday, FakeStore())
    assert result["ok"]
    assert monday.written == {}
    assert monday.updates == []


def test_an_upload_still_runs_when_files_are_present():
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = FakeMonday(blob(KANE))
    payload = {"event": {"pulseId": 123, "boardId": BOARD_ID,
                         "value": {"files": [{"name": "eorder.xlsx"}]}}}
    result = ingest.handle_webhook(payload, monday, FakeStore())
    assert result["ok"] and result["status"] == "✅ Read"
    assert monday.renamed.startswith("KANE CIVIL")


def test_odd_column_settings_never_crash_label_parsing():
    """json.loads accepts "null" and "[]"; .get on the result raised inside
    resolved(), outside ingest's guards — one odd status column on the board
    failed every ingest. Found in adversarial review before it shipped far.

    Unrecognised shapes must come back None ("unknown"), not [] ("no
    labels") — the writer drops labels a column doesn't have but passes
    through columns it knows nothing about, so conflating the two would
    silently discard every status write to such a column."""
    from _lib.columns import _parse_labels
    assert _parse_labels(None) is None
    assert _parse_labels("") is None
    assert _parse_labels("null") is None
    assert _parse_labels("[]") is None
    assert _parse_labels("not json at all") is None
    assert _parse_labels('{"labels":{"1":"Read","2":null}}') == ["Read"]
    assert _parse_labels('{"labels":{}}') == []   # genuinely no labels


# -- status labels are the board's, not the code's (incident of 19 Aug 2026) --

class EmojiBoard(FakeMonday):
    """A board whose status labels DID keep their emoji."""

    def board_columns(self, board_id):
        columns = [dict(c) for c in BOARD_COLUMNS]
        for column in columns:
            if column["id"] == "color_status":
                column["settings_str"] = json.dumps(
                    {"labels": {"1": "✅ Read", "2": "⚠️ Check", "3": "❌ Failed"}})
        return columns


def test_a_board_with_emoji_labels_gets_the_emoji_spelling():
    result, monday, _ = run(KANE, monday=EmojiBoard(blob(KANE)))
    assert result["ok"]
    assert monday.written["color_status"] == {"label": "✅ Read"}


class ForeignLabels(FakeMonday):
    """A board whose Install Required column has labels this app never writes."""

    def board_columns(self, board_id):
        columns = [dict(c) for c in BOARD_COLUMNS]
        for column in columns:
            if column["id"] == "color_install":
                column["settings_str"] = json.dumps(
                    {"labels": {"1": "Installed by us", "2": "Not needed"}})
        return columns


def test_an_unmatchable_label_is_dropped_and_reported_not_fatal():
    """One unknown label used to fail the whole mutation — every field lost,
    the order stamped Failed, and the only trace a MondayError in an Update.
    And a dropped value is a silent field loss, so the row must flag ⚠️ Check
    — the at-a-glance filter is the whole point of the status column."""
    result, monday, _ = run(KANE, monday=ForeignLabels(blob(KANE)))
    assert result["ok"]
    assert "color_install" not in monday.written          # dropped, not fatal
    assert monday.written["text_contact"] == "Gerard Cahalan"   # rest landed
    assert monday.written["color_status"] == {"label": "Check"}
    assert result["status"] == "⚠️ Check"
    assert any("does not exist" in w and "install_required" in w
               for w in result["warnings"])


# -- multi-site subitems must not take down the order (§8.4) -----------------

class SubitemValuesRejected(FakeMonday):
    """Subitems live on their own board; the parent board's column IDs are
    invalid there, so real monday rejects any subitem write that carries them."""

    def create_subitem(self, parent, name, values=None):
        if values:
            raise MondayError("Column not found on this board")
        return super().create_subitem(parent, name, values)


def test_multi_site_orders_survive_subitem_column_rejection(monkeypatch):
    parsed = {
        "opportunity_id": "006TESTMULTI", "company": "QUALITYVEND",
        "derived_item_name": "QUALITYVEND = 12 x AT551",
        "order_reason": "Add-On", "order_date": "July 2, 2026",
        "ship_to_type": "multiple", "install_required": "Yes",
        "site_contact_name": "A Person", "site_contact_phone": "0400000000",
        "multi_site": [{"company": "Site A", "qty": 4},
                       {"company": "Site B", "qty": 8}],
        "lines": [{"qty": 12, "product": "AT551 Asset Tracker Service"}],
        "_warnings": [],
    }

    class StubParser:
        ACV_ORDER_REASONS = ["New Business"]

        @staticmethod
        def parse(handle):
            return dict(parsed)

    monkeypatch.setattr(ingest, "_parser", lambda: StubParser)
    result, monday, _ = run(KANE, monday=SubitemValuesRejected(blob(KANE)))
    assert result["ok"], result.get("reason")
    # Both sites exist as subitems, created bare after the values were refused.
    assert monday.subitems_created == ["Site A — 4 units", "Site B — 8 units"]
    assert monday.written["color_status"] == {"label": "Check"}
