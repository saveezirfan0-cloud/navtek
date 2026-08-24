"""Setup step 2 must never create a column the board already has.

The live board grew a second ACV and a second Install Commission. Both already
existed — one under a historical title, one already correct — but create_columns
looked only for its own spelling of the title, found nothing, and made a new one
alongside. The app then wrote to its new empty column while the team kept
reading the old populated one, which is worse than not writing at all.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import bootstrap, config  # noqa: E402

BOARD = 18426505553


class FakeMonday:
    def __init__(self, columns):
        self.columns = list(columns)
        self.created = []

    def board_columns(self, board_id):
        return list(self.columns)

    def create_column(self, board_id, title, column_type, settings=None,
                      description=None):
        self.created.append((title, column_type))
        column = {"id": f"new_{len(self.created)}", "title": title,
                  "type": column_type}
        self.columns.append(column)
        return column


def _run(columns, monkeypatch):
    monkeypatch.setattr(config, "ORDERS_BOARD_ID", BOARD)
    monkeypatch.setattr(config, "COLUMNS", dict(config.COLUMNS))
    monday = FakeMonday(columns)
    return bootstrap.create_columns(monday, BOARD), monday


def test_a_column_under_a_historical_title_is_reused_not_duplicated(monkeypatch):
    """"Annual Contract Value" IS the ACV column. Creating a second one titled
    "ACV" splits the field in two and empties the one people read."""
    result, monday = _run(
        [{"id": "legacy_acv", "title": "Annual Contract Value", "type": "numbers"}],
        monkeypatch)
    assert ("ACV", "numbers") not in monday.created
    assert result["column_ids"]["acv"] == "legacy_acv"
    assert any("reused" in line and "Annual Contract Value" in line
               for line in result["log"])


def test_an_exact_title_match_is_still_reused(monkeypatch):
    result, monday = _run(
        [{"id": "acv_1", "title": "ACV", "type": "numbers"}], monkeypatch)
    assert ("ACV", "numbers") not in monday.created
    assert result["column_ids"]["acv"] == "acv_1"


def test_install_commission_is_not_duplicated_either(monkeypatch):
    result, monday = _run(
        [{"id": "ic_1", "title": "Installation Commission", "type": "numbers"}],
        monkeypatch)
    assert not any(t == "Install Commission" for t, _ in monday.created)
    assert result["column_ids"]["install_commission"] == "ic_1"


def test_a_same_named_column_of_the_wrong_type_is_reported_not_duplicated(monkeypatch):
    """Two columns called "ACV" are indistinguishable in every view and
    dropdown on the board — saying so beats making one."""
    result, monday = _run(
        [{"id": "acv_text", "title": "ACV", "type": "text"}], monkeypatch)
    assert not any(t == "ACV" for t, _ in monday.created)
    assert "ACV" in result["failed"]
    assert any("conflict" in line and "not a 'numbers'" in line
               for line in result["log"])


def test_a_genuinely_absent_column_is_still_created(monkeypatch):
    result, monday = _run([], monkeypatch)
    created = {t for t, _ in monday.created}
    assert "ACV" in created and "Site Contact" in created


def test_the_plan_says_reuse_before_anything_is_created(monkeypatch):
    """plan_columns is the "read this before running it" step — if it says
    create where create_columns reuses, it is worse than no plan at all."""
    monkeypatch.setattr(config, "ORDERS_BOARD_ID", BOARD)
    monday = FakeMonday(
        [{"id": "legacy_acv", "title": "Annual Contract Value", "type": "numbers"}])
    plan = {row["key"]: row for row in bootstrap.plan_columns(monday, BOARD)}
    assert plan["acv"]["action"] == "reuse 'Annual Contract Value'"
    assert plan["acv"]["column_id"] == "legacy_acv"
    assert plan["site_contact"]["action"] == "create"
