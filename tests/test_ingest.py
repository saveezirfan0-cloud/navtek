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
    {"id": "text_opp", "title": "Opportunity ID", "type": "text"},
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
    {"id": "numeric_acv", "title": "ACV", "type": "numbers"},
    {"id": "numeric_install", "title": "Install Value", "type": "numbers"},
    {"id": "numeric_installcomm", "title": "Install Commission", "type": "numbers"},
    # The team's own working status. "6.1 Installer Esc." is FIRST, which is
    # why every new row inherited it on the live board.
    {"id": "color_order", "title": "Status", "type": "status",
     "settings_str": json.dumps(
         {"labels": {"1": "6.1 Installer Esc.", "2": "Order placed",
                     "3": "2.0 Booked"}})},
    {"id": "date_order", "title": "Order Date", "type": "date"},
    {"id": "subtasks_1", "title": "Subitems", "type": "subtasks",
     "settings_str": json.dumps({"boardIds": [777]})},
]

SUB_BOARD_ID = 777


class FakeMonday:
    def __init__(self, blob, existing_values=None, existing_name="x",
                 group=None):
        self.blob = blob
        self.written = {}
        self.updates = []
        self.updates_to = []        # (item_id, body) — who each update went to
        self.written_to = []        # (item_id, values) — who each write went to
        self.matches = []           # rows find_by_column_value returns
        self.renamed = None
        self.subitems_created = []
        self.subitem_written = []   # values handed to create_subitem
        self.sub_columns = []       # columns created on the subitem board
        self.moved = None           # (item_id, group_id) after a group move
        self.groups_created = []    # month groups created on the fly
        self._existing = existing_values or {}
        self._name = existing_name
        self._group = group or {"id": "g_docusign",
                                "title": "New Opps/Sent DocuSigns"}
        self.downloads = 0

    def board_columns(self, board_id):
        if str(board_id) == str(SUB_BOARD_ID):
            return list(self.sub_columns)
        return BOARD_COLUMNS

    def create_column(self, board_id, title, column_type, settings=None,
                      description=None):
        assert str(board_id) == str(SUB_BOARD_ID), "only the subitem board grows"
        column = {"id": f"sub_{column_type}_{len(self.sub_columns)}",
                  "title": title, "type": column_type,
                  "settings_str": json.dumps(settings) if settings else None}
        self.sub_columns.append(column)
        return column

    def board_groups(self, board_id):
        from datetime import datetime
        now = datetime.now()
        month = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"][now.month - 1]
        return [{"id": "g_docusign", "title": "New Opps/Sent DocuSigns"},
                {"id": "g_month", "title": f"{month} {now.year}"}]

    def move_to_group(self, item_id, group_id):
        self.moved = (item_id, group_id)
        return {"id": item_id}

    def create_group(self, board_id, name):
        self.groups_created.append(name)
        return f"g_created_{len(self.groups_created)}"

    def asset_urls(self, item_id, column_id):
        return [{"name": "eorder.xlsx", "public_url": "https://example/x"}]

    def download(self, url):
        self.downloads += 1
        return self.blob

    def item(self, item_id):
        return {
            "id": item_id, "name": self._name, "group": dict(self._group),
            "column_values": [{"id": k, "text": v} for k, v in self._existing.items()],
        }

    def find_by_column_value(self, *a):
        return list(self.matches)

    def set_columns(self, board_id, item_id, values, create_labels_if_missing=False):
        if not create_labels_if_missing:
            self._enforce_labels(values)
        self.written.update(values)
        self.written_to.append((str(item_id), values))
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
        self.subitem_written.append(values or {})
        return {"id": str(len(self.subitems_created)),
                "board": {"id": str(SUB_BOARD_ID)}}

    def post_update(self, item_id, body):
        self.updates.append(body)
        self.updates_to.append((str(item_id), body))
        return "1"


class FakeStore:
    """Records what it was told, and can pretend the database is broken."""

    def __init__(self, broken=False):
        self.enabled = True
        self.broken = broken
        self.degraded = "simulated failure" if broken else None
        self.ingests = []
        self.unknown_reasons = []
        self.claims = set()
        self.webhooks = []

    def claim_delivery(self, key, ttl_minutes=60):
        if self.broken:
            return True  # fail open, like the real store
        if key in self.claims:
            return False
        self.claims.add(key)
        return True

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
    ingest._SUB_COLS_CACHE.clear()
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
    # The rename rides in the main mutation now — one round trip, not two.
    assert monday.written["name"] == "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    assert monday.written["text_contact"] == "Gerard Cahalan"
    assert monday.written["numeric_units"] == "44"
    assert monday.written["numeric_acv"] == "18144"        # §4.1: 54,432 / 36mo × 12
    assert monday.written["numeric_install"] == "8000"
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


# -- feedback from the sandbox drops: files land on spare rows ----------------
#
# Staff re-drop a re-issued eOrder on a fresh row at least as often as on the
# original. The opportunity join already redirected the WRITE to the real row,
# but the spare row stayed silent — which reads as "the automation ignored me".

def test_a_file_dropped_on_a_spare_row_points_back_at_the_real_order():
    real_name = "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    monday = FakeMonday(blob(KANE), existing_name=real_name)
    monday.matches = [{"id": "999", "name": real_name}]

    result, _, _ = run(KANE, monday=monday)
    assert result["ok"]
    assert str(result["target_item_id"]) == "999"
    assert result["redirected_from"] == 123
    # The read summary lands on the real order's row…
    assert any(to == "999" and "Read from eOrder" in body
               for to, body in monday.updates_to)
    # …and the spare row is told where the order went and that it can go.
    pointers = [body for to, body in monday.updates_to if to == "123"]
    assert pointers, monday.updates_to
    assert "Matched an existing order" in pointers[0]
    assert "KANE CIVIL" in pointers[0] and "deleted" in pointers[0]
    # …and stamped Duplicate at board level, so it can't pass for a live order.
    assert ("123", {"color_status": {"label": "Duplicate"}}) in monday.written_to


def test_a_duplicate_on_a_spare_row_names_the_real_row():
    store = FakeStore()
    run(KANE, store=store)  # first read, on the real row

    real_name = "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    monday = FakeMonday(blob(KANE), existing_name=real_name)
    monday.matches = [{"id": "999", "name": real_name}]

    second, _, _ = run(KANE, monday=monday, store=store)
    assert second["skipped"] == "identical file already read"
    to, body = monday.updates_to[0]
    assert to == "123" and "Already read" in body
    assert "KANE CIVIL" in body and "spare row can be deleted" in body
    # The spare row is stamped Duplicate — and that is its ONLY write.
    assert monday.written_to == [("123", {"color_status": {"label": "Duplicate"}})]


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
    # Install Required = No → no install items (Prompt 1).
    assert monday.subitems_created == []


# -- Prompt 1: every install order gets one install item per site ------------

def test_single_site_install_orders_get_no_subitems():
    """Damon's rule from the first live drops: subitems are per delivery SITE,
    and ~80% of orders are single-site — the row itself is the job. The portal
    already treats a subitem-less order as its own single install item."""
    result, monday, _ = run(KANE)
    assert result["ok"]
    assert monday.subitems_created == []


# -- ALLOW_DUPLICATE_FILES: the testing escape hatch --------------------------

def test_duplicate_files_are_reprocessed_when_the_flag_is_on(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_DUPLICATE_FILES", True)
    store = FakeStore()
    run(KANE, store=store)

    second, monday2, _ = run(KANE, store=store)
    assert second["ok"] and not second.get("skipped")
    assert second["duplicate_reread"] is True
    # It really re-ran — fields written, no "Already read" brush-off.
    assert monday2.written["text_contact"] == "Gerard Cahalan"
    assert not any("Already read" in u for u in monday2.updates)


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
    assert monday.written["numeric_units"] == "44"


# -- the database is not on the critical path -------------------------------

def test_the_order_still_lands_when_the_database_is_broken():
    result, monday, _ = run(KANE, store=FakeStore(broken=True))
    assert result["ok"]
    assert result["status"] == "✅ Read"
    # The rename rides in the main mutation now — one round trip, not two.
    assert monday.written["name"] == "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
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
    assert monday.written["name"].startswith("KANE CIVIL")


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


# -- the failure path itself must not have failure modes ----------------------

def test_catchall_failures_still_stamp_failed_from_board_columns(monkeypatch):
    """The catch-all path reaches _fail with no resolved columns. It must
    resolve the status column from the board so ❌ Failed shows on the row —
    before, a catastrophic failure left the status blank and the Update was
    the only trace."""
    def explode(*args, **kwargs):
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(ingest, "_run", explode)
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = FakeMonday(blob(KANE))
    result = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": BOARD_ID}}, monday, FakeStore())
    assert not result["ok"]
    assert monday.written.get("color_status") == {"label": "Failed"}
    assert "Could not read eOrder" in monday.updates[0]


def test_the_update_still_posts_when_the_status_write_is_refused():
    """Reporting must not depend on the status column cooperating: if monday
    refuses the ❌ Failed write, the person still needs the explanation."""
    class RefusesWrites(FakeMonday):
        def set_columns(self, board_id, item_id, values):
            raise MondayError("simulated refusal")

    monday = RefusesWrites(b"this is not a spreadsheet")
    result, monday, _ = run(KANE, monday=monday)
    assert not result["ok"]
    assert monday.written == {}
    assert any("Could not read eOrder" in u for u in monday.updates)


def test_events_for_another_board_are_turned_away():
    """The webhook is registered on one board; a delivery naming another —
    misconfiguration or someone probing the public endpoint — must end before
    any monday call is made."""
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = FakeMonday(blob(KANE))
    result = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": 999}}, monday, FakeStore())
    assert not result["ok"]
    assert "not the orders board" in result["reason"]
    assert monday.written == {} and monday.updates == [] and monday.downloads == 0


# -- delivery-level dedup (FINALIZE prompt 7) ---------------------------------

def test_the_same_delivery_twice_ingests_once():
    """monday can fire one event more than once; file-level dedupe can't stop
    two deliveries racing each other, so the delivery itself is claimed first."""
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    store = FakeStore()
    payload = {"event": {"pulseId": 123, "boardId": BOARD_ID,
                         "triggerUuid": "abc-123"}}

    first = ingest.handle_webhook(payload, FakeMonday(blob(KANE)), store)
    assert first["ok"] and not first.get("skipped")

    monday2 = FakeMonday(blob(KANE))
    second = ingest.handle_webhook(payload, monday2, store)
    assert second["ok"]
    assert "duplicate" in second["skipped"]
    assert monday2.written == {} and monday2.downloads == 0


def test_distinct_deliveries_are_not_confused():
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    store = FakeStore()
    a = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": BOARD_ID, "triggerUuid": "one"}},
        FakeMonday(blob(KANE)), store)
    b = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": BOARD_ID, "triggerUuid": "two"}},
        FakeMonday(blob(KANE)), store)
    assert a["ok"] and not a.get("skipped")
    # Same file → the FILE-level dedupe catches it, not the delivery gate.
    assert b["ok"] and b.get("skipped") == "identical file already read"


def test_the_delivery_gate_fails_open_when_the_database_is_down():
    """An order landing twice is recoverable; an order not landing is not."""
    columns_mod.clear_cache()
    config.ORDERS_BOARD_ID = BOARD_ID
    monday = FakeMonday(blob(KANE))
    result = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": BOARD_ID, "triggerUuid": "x"}},
        monday, FakeStore(broken=True))
    assert result["ok"] and not result.get("skipped")
    assert monday.written  # the order landed


def test_transient_monday_failures_do_not_silently_strip_subitem_fields(monkeypatch):
    """gql raises the same MondayError for exhausted rate limits as for
    refused values. Retrying a transient failure bare would create the subitem
    with no site fields — silently, forever, since existing subitems are never
    revisited. Transients must surface as a warning instead."""
    parsed = {
        "opportunity_id": "006TESTTRANSIENT", "company": "QUALITYVEND",
        "derived_item_name": "QUALITYVEND = 12 x AT551",
        "order_reason": "Add-On", "order_date": "July 2, 2026",
        "ship_to_type": "multiple", "install_required": "Yes",
        "site_contact_name": "A Person", "site_contact_phone": "0400000000",
        "multi_site": [{"company": "Site A", "qty": 4}],
        "lines": [{"qty": 4, "product": "AT551 Asset Tracker Service"}],
        "_warnings": [],
    }

    class StubParser:
        ACV_ORDER_REASONS = ["New Business"]

        @staticmethod
        def parse(handle):
            return dict(parsed)

    class RateLimited(FakeMonday):
        def create_subitem(self, parent, name, values=None):
            raise MondayError("monday unavailable after 3 attempts: HTTP 429")

    monkeypatch.setattr(ingest, "_parser", lambda: StubParser)
    result, monday, _ = run(KANE, monday=RateLimited(blob(KANE)))
    assert result["ok"]  # the order itself still lands
    assert monday.subitems_created == []
    assert any("could not create per-site subitems" in w
               for w in result["warnings"])


def test_a_value_refusal_on_subitems_is_reported_not_silent(monkeypatch):
    """The bare retry is for refused values only — and it must say so."""
    parsed = {
        "opportunity_id": "006TESTREFUSED", "company": "QUALITYVEND",
        "derived_item_name": "QUALITYVEND = 12 x AT551",
        "order_reason": "Add-On", "order_date": "July 2, 2026",
        "ship_to_type": "multiple", "install_required": "Yes",
        "site_contact_name": "A Person", "site_contact_phone": "0400000000",
        "multi_site": [{"company": "Site A", "qty": 4}],
        "lines": [{"qty": 4, "product": "AT551 Asset Tracker Service"}],
        "_warnings": [],
    }

    class StubParser:
        ACV_ORDER_REASONS = ["New Business"]

        @staticmethod
        def parse(handle):
            return dict(parsed)

    monkeypatch.setattr(ingest, "_parser", lambda: StubParser)
    result, monday, _ = run(KANE, monday=SubitemValuesRejected(blob(KANE)))
    assert result["ok"]
    assert monday.subitems_created == ["Site A — 4 units"]
    assert any("without its site fields" in w for w in result["warnings"])


def test_fail_with_no_failed_like_label_still_posts_the_update():
    """A hand-made status column may have no label resembling Failed. The
    status write is dropped by alignment, and the Update — the only feedback
    channel left — must still post."""
    class NoFailedLabel(FakeMonday):
        def board_columns(self, board_id):
            columns = [dict(c) for c in BOARD_COLUMNS]
            for column in columns:
                if column["id"] == "color_status":
                    column["settings_str"] = json.dumps(
                        {"labels": {"1": "Fine", "2": "Look at this"}})
            return columns

    monday = NoFailedLabel(b"this is not a spreadsheet")
    result, monday, _ = run(KANE, monday=monday)
    assert not result["ok"]
    assert "color_status" not in monday.written   # dropped, not exploded
    assert any("Could not read eOrder" in u for u in monday.updates)


# -- Damon's first-live-drop feedback, 20 Aug 2026 ----------------------------

def test_site_address_is_the_customer_never_the_ship_to():
    """Kane's hardware ships to 39 Jindalee Cres Nowra — Paul Redmond's
    workshop. The trucks live at 9-13 Underwood Ave Botany. Installers were
    being sent to the workshop."""
    _, kane, _ = run(KANE)
    assert kane.written["text_addr"] == "9-13 Underwood Avenue, Botany NSW 2019"
    assert "Jindalee" not in kane.written["text_addr"]

    _, agb, _ = run(AGB)
    assert agb.written["text_addr"] == "15 Lockwood Street, Merrylands NSW 2160"
    assert "Nothing to Ship" not in agb.written["text_addr"]


def test_phone_lands_with_the_plus_prefix():
    _, monday, _ = run(KANE)
    assert monday.written["phone_site"]["phone"] == "+61437353834"


def test_a_read_order_is_filed_into_the_month_it_was_placed():
    """Rows start out wherever staff created them ("New Opps/Sent DocuSigns")
    and were staying there.

    The month is the ORDER's, not today's. Kane Civil is dated 2 July 2026, so
    it belongs in July however long the file sits before someone drops it —
    filing by datetime.now() put orders in whichever month the paperwork got
    done, which is not what the groups mean.
    """
    class DatedGroups(FakeMonday):
        def board_groups(self, board_id):
            return [{"id": "g_docusign", "title": "New Opps/Sent DocuSigns"},
                    {"id": "g_july", "title": "July 2026"},
                    {"id": "g_now", "title": "August 2026"}]

    result, monday, _ = run(KANE, monday=DatedGroups(blob(KANE)))
    assert result["ok"]
    assert monday.moved == (123, "g_july")


def test_an_order_already_in_a_month_group_stays_put():
    """A revised eOrder months later must not drag an old order forward."""
    monday = FakeMonday(blob(KANE), group={"id": "g_july", "title": "July 2026"})
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"]
    assert monday.moved is None


def test_the_months_group_is_created_when_the_board_lacks_one():
    """On the 1st of a new month the group doesn't exist yet. Leaving the row
    unfiled every month-start was the worse failure — the group is created
    with exactly the title staff would give it."""
    class NoMonthGroups(FakeMonday):
        def board_groups(self, board_id):
            return [{"id": "g_docusign", "title": "New Opps/Sent DocuSigns"}]

    monday = NoMonthGroups(blob(KANE))
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"]
    # The ORDER's month — Kane Civil is dated 2 July 2026 — not today's.
    assert monday.groups_created == ["July 2026"]
    assert monday.moved == (123, "g_created_1")


def test_an_eorder_with_no_readable_date_still_gets_filed():
    """Today's month is the fallback, not the rule: with nothing to go on,
    an unfiled row is worse than one filed under the read date."""
    from datetime import datetime

    class NoMonthGroups(FakeMonday):
        def board_groups(self, board_id):
            return [{"id": "g_docusign", "title": "New Opps/Sent DocuSigns"}]

    monday = NoMonthGroups(blob(KANE))
    original = ingest._order_month
    try:
        ingest._order_month = lambda parsed: None
        result, monday, _ = run(KANE, monday=monday)
    finally:
        ingest._order_month = original
    assert result["ok"]
    now = datetime.now()
    assert monday.groups_created == [f"{ingest.MONTHS[now.month - 1]} {now.year}"]


# -- Setup prepares the install-item field set up front -----------------------

def test_setup_prepares_the_subitem_field_set():
    from _lib import bootstrap
    monday = FakeMonday(blob(KANE))
    ingest._SUB_COLS_CACHE.clear()
    result = bootstrap.prepare_subitem_columns(monday, BOARD_ID)
    assert result["prepared"] is True
    titles = [c["title"] for c in monday.sub_columns]
    assert "Site Address" in titles and "Units Total" in titles
    assert "Site Phone" in titles and "Booked Date" in titles
    # Idempotent — a second run binds what exists and creates nothing new.
    before = len(monday.sub_columns)
    bootstrap.prepare_subitem_columns(monday, BOARD_ID)
    assert len(monday.sub_columns) == before


def test_setup_survives_a_column_type_monday_refuses(monkeypatch):
    """"This column type is not supported yet in the API" on ONE column
    (board_relation, on some accounts) used to abort the whole step with a
    502 and nothing created. Refusals are now logged and skipped."""
    from _lib import bootstrap
    monkeypatch.setattr(config, "INSTALLERS_BOARD_ID", 555)

    class RefusesRelations(FakeMonday):
        def create_column(self, board_id, title, ctype, settings=None,
                          description=None):
            if ctype == "board_relation":
                raise MondayError("This column type is not supported yet in the API")
            return super().create_column(board_id, title, ctype, settings,
                                         description)

    monday = RefusesRelations(blob(KANE))
    ingest._SUB_COLS_CACHE.clear()
    result = bootstrap.prepare_subitem_columns(monday, BOARD_ID)
    assert result["prepared"] is True
    titles = [c["title"] for c in monday.sub_columns]
    assert "Site Address" in titles      # the rest of the field set landed
    assert "Installer" not in titles


def test_create_columns_continues_past_a_refused_type():
    from _lib import bootstrap

    class RefusesFiles:
        def board_columns(self, board_id):
            return []

        def create_column(self, board_id, title, ctype, settings=None,
                          description=None):
            if ctype == "file":
                raise MondayError("This column type is not supported yet in the API")
            return {"id": f"c_{title.lower().replace(' ', '_')}"}

    result = bootstrap.create_columns(RefusesFiles(), BOARD_ID)
    assert "eOrder" in result["failed"] and "Vehicle List" in result["failed"]
    assert result["column_ids"]["eorder_status"]   # everything else landed
    assert any(line.startswith("failed   eOrder") for line in result["log"])


def test_setup_skips_subitem_columns_until_the_board_exists():
    from _lib import bootstrap

    class NoSubitemsYet(FakeMonday):
        def board_columns(self, board_id):
            return [c for c in super().board_columns(board_id)
                    if c["type"] != "subtasks"]

    ingest._SUB_COLS_CACHE.clear()
    result = bootstrap.prepare_subitem_columns(NoSubitemsYet(blob(KANE)), BOARD_ID)
    assert result["prepared"] is False
    assert "first multi-site order" in result["log"][0]


def test_multi_site_subitems_carry_their_fields_on_their_own_board(monkeypatch):
    """The first live drops produced perfectly-named but EMPTY subitems:
    values keyed by the parent board's column ids are refused wholesale by
    the subitem board. The fields are now created there and written with
    ITS ids."""
    parsed = {
        "opportunity_id": "006TESTSUBFIELDS", "company": "QUALITYVEND",
        "derived_item_name": "QUALITYVEND = 12 x AT551",
        "order_reason": "Add-On", "order_date": "July 2, 2026",
        "ship_to_type": "multiple", "install_required": "Yes",
        "site_contact_name": "A Person", "site_contact_phone": "0400000000",
        "multi_site": [
            {"company": "Site A", "qty": 4, "contact": "Alice",
             "phone_e164": "+61400000001", "address": "1 Alpha St, Sydney"},
            {"company": "Site B", "qty": 8, "contact": "Bob",
             "phone_e164": "+61400000002", "address": "2 Beta Rd, Melbourne"},
        ],
        "lines": [{"qty": 12, "product": "AT551 Asset Tracker Service"}],
        "_warnings": [],
    }

    class StubParser:
        ACV_ORDER_REASONS = ["New Business"]

        @staticmethod
        def parse(handle):
            return dict(parsed)

    monkeypatch.setattr(ingest, "_parser", lambda: StubParser)
    result, monday, _ = run(KANE)
    assert result["ok"]
    assert monday.subitems_created == ["Site A — 4 units", "Site B — 8 units"]

    # The install-item fields were created ON THE SUBITEM BOARD…
    titles = {c["title"] for c in monday.sub_columns}
    assert {"Site Contact", "Site Phone", "Site Address",
            "Units Total", "Contacted Date", "Booked Date"} <= titles

    # …and the values were written with ITS column ids, not the parent's.
    first = monday.subitem_written[0]
    assert first, "subitem was created with no values"
    assert all(k.startswith("sub_") for k in first)
    by_title = {c["id"]: c["title"] for c in monday.sub_columns}
    named = {by_title[k]: v for k, v in first.items()}
    assert named["Site Contact"] == "Alice"
    assert named["Site Address"] == "1 Alpha St, Sydney"
    assert named["Units Total"] == "4"
    assert named["Site Phone"]["phone"] == "+61400000001"


# -- every failure is visible on the row (sandbox feedback, 22 Aug) ----------
#
# "A crash that writes nothing looks identical to a job nobody touched."

def test_a_failure_that_reports_nothing_still_stamps_the_row(monkeypatch):
    """The backstop. A path that returns ok:False without saying so on the
    row must still leave ❌ Failed and an Update behind."""
    monkeypatch.setattr(ingest, "_run",
                        lambda *a, **k: {"ok": False, "reason": "boom"})
    result, monday, _ = run(KANE)
    assert result["ok"] is False
    assert monday.written["color_status"] == {"label": "Failed"}
    assert any("boom" in body for body in monday.updates)


def test_the_backstop_does_not_double_report_a_path_that_already_did():
    """A parse failure reports itself; the backstop must stay out of its way
    rather than posting a second Update on the same row."""
    monday = FakeMonday(b"this is not a spreadsheet")
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"] is False
    assert len([b for b in monday.updates if "Could not read eOrder" in b]) == 1


def test_a_board_with_no_eorder_column_says_so_on_the_row(monkeypatch):
    """Previously this returned quietly and the row showed nothing at all."""
    monkeypatch.setattr(columns_mod, "resolved",
                        lambda *a, **k: {"eorder_status": "color_status"})
    result, monday, _ = run(KANE)
    assert result["ok"] is False
    assert "no file column" in result["reason"]
    # Stamped either way: with the board unreadable the label cannot be
    # aligned, and _fail lets monday add it rather than leaving the row blank.
    assert monday.written["color_status"]["label"] in ("Failed", "❌ Failed")
    assert any("eOrder" in body for body in monday.updates)


def test_a_failed_stamp_lands_even_when_the_label_cannot_be_aligned(monkeypatch):
    """The emoji-stripping incident again, on the failure path: an unaligned
    "❌ Failed" is refused wholesale by a board whose label is "Failed", which
    left the row with no stamp at all — the silent row _fail exists to stop."""
    monkeypatch.setattr(columns_mod, "status_labels",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no board")))
    monday = FakeMonday(b"this is not a spreadsheet")
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"] is False
    assert monday.written["color_status"]["label"] in ("Failed", "❌ Failed")


def test_a_delivery_for_another_board_is_logged_rather_than_vanishing():
    """Not stamped — it is not our board — but never silent either."""
    monday = FakeMonday(blob(KANE))
    store = FakeStore()
    config.ORDERS_BOARD_ID = BOARD_ID
    result = ingest.handle_webhook(
        {"event": {"pulseId": 123, "boardId": 999}}, monday, store)
    assert result["ok"] is False
    assert store.webhooks, "the delivery log is how a silent return is found"
    assert "not the orders board" in store.webhooks[-1]["reason"]
    assert monday.written == {}


# -- a deliberate re-read corrects wrong values (sandbox feedback) -----------

def test_a_forced_reread_corrects_a_wrong_value_it_previously_wrote(monkeypatch):
    """merge_preserving protects human edits, but it also froze the app's own
    bad writes: re-dropping the same file produced no diff, so every value was
    filtered out again and a wrong column stayed wrong forever."""
    monkeypatch.setattr(config, "ALLOW_DUPLICATE_FILES", True)
    store = FakeStore()
    run(KANE, store=store)

    # The board now holds a wrong unit count where the eOrder says 44.
    monday = FakeMonday(blob(KANE), existing_values={"numeric_units": "2.0"})
    result, monday, _ = run(KANE, store=store, monday=monday)
    assert result["ok"]
    assert result.get("duplicate_reread") is True
    assert monday.written["numeric_units"] == "44"


def test_an_ordinary_first_read_still_leaves_a_human_edit_alone():
    monday = FakeMonday(blob(KANE), existing_values={"text_contact": "Someone Else"})
    result, monday, _ = run(KANE, monday=monday)
    assert result["ok"]
    assert "text_contact" not in monday.written


# -- Damon's answers, 22 Aug ------------------------------------------------

def test_install_commission_carries_the_eorders_install_figure():
    """It is what Navtek is paid to organise the install — the same number as
    Install Value, which is why it sits apart from Dealer Commission."""
    result, monday, _ = run(KANE)
    assert result["ok"]
    assert monday.written["numeric_installcomm"] == "8000"
    assert monday.written["numeric_install"] == "8000"


def test_a_zero_install_figure_leaves_both_install_columns_blank():
    """Teletrac Navman sometimes organise the install themselves and nothing
    is payable to Navtek. Blank says that; 0 asserts a nil fee."""
    result, monday, _ = run(SOUTHERN)      # Service Only Renewal, install 0
    assert result["ok"]
    assert "numeric_installcomm" not in monday.written
    assert "numeric_install" not in monday.written


def test_acv_stays_empty_on_an_order_reason_that_earns_none():
    """Renewals, changes of ownership and hardware-only carry no ACV — empty,
    never zero, or the new-business average is dragged down."""
    result, monday, _ = run(SOUTHERN)
    assert result["ok"]
    assert "numeric_acv" not in monday.written


def test_the_first_read_stamps_order_placed():
    """A new row inherits the board's first label — "6.1 Installer Esc." — so
    every brand new order read as a stalled job."""
    result, monday, _ = run(KANE)
    assert result["ok"]
    assert monday.written["color_order"] == {"label": "Order placed"}


def test_a_later_read_never_drags_the_working_status_backwards(monkeypatch):
    """The team works this column. An order that has moved on to Booked must
    not be reset by a later eOrder landing on the same order."""
    monkeypatch.setattr(config, "ALLOW_DUPLICATE_FILES", True)
    store = FakeStore()
    run(KANE, store=store)
    monday = FakeMonday(blob(KANE), existing_values={"color_order": "2.0 Booked"})
    result, monday, _ = run(KANE, store=store, monday=monday)
    assert result["ok"]
    assert "color_order" not in monday.written


def test_no_opening_status_when_the_ledger_cannot_prove_it_is_the_first_read():
    """With the database down we cannot tell first from fifth. A missed
    opening status is recoverable; one dragged backwards is a job nobody
    chases."""
    result, monday, _ = run(KANE, store=FakeStore(broken=True))
    assert "color_order" not in monday.written


def test_install_arranged_by_is_never_written():
    """Damon owns that column by hand — the eOrder cannot state who arranges
    the install, and ship-to only says where hardware goes."""
    class WithArrangedBy(FakeMonday):
        def board_columns(self, board_id):
            if str(board_id) == str(SUB_BOARD_ID):
                return list(self.sub_columns)
            return BOARD_COLUMNS + [
                {"id": "color_arranged", "title": "Install Arranged By",
                 "type": "status", "settings_str": json.dumps({"labels": {
                     "1": "Navtek organised", "2": "Teletrac Navman organised",
                     "3": "Customer self-install"}})}]

    result, monday, _ = run(KANE, monday=WithArrangedBy(blob(KANE)))
    assert result["ok"]
    assert "color_arranged" not in monday.written
    assert not any("color_arranged" in v for _, v in monday.written_to)
