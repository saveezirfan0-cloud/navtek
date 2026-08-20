"""Auto-onboarding: a monday row becomes a synced, emailed portal account.

Same posture as test_installer_flow.py — real modules against a fake monday
and a fake database, no network. The rules under test exist because the
manual path (Setup step A, step B, copy the link) kept being half-run: an
account with a token in monday but no database row is invisible to the
portal, and nobody notices until the installer asks where their link is.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

import pytest  # noqa: E402

from _lib import bootstrap, config, emailer, onboarding  # noqa: E402

BOARD_ID = 18426336129

BOARD_COLUMNS = [
    {"id": "status_type", "title": "Type", "type": "status"},
    {"id": "text_coord", "title": "Coordinator name", "type": "text"},
    {"id": "phone_coord", "title": "Coordinator mobile", "type": "phone"},
    {"id": "email_coord", "title": "Coordinator email", "type": "email"},
    {"id": "text_token", "title": "Portal token", "type": "text"},
    {"id": "drop_region", "title": "Region", "type": "dropdown"},
    {"id": "status_state", "title": "State", "type": "status"},
    {"id": "check_active", "title": "Active", "type": "checkbox"},
]


def make_row(item_id, name, token="", active="", email="", coordinator=""):
    def value(column_id, text):
        return {"id": column_id, "text": text}
    return {
        "id": str(item_id),
        "name": name,
        "column_values": [
            value("status_type", "Sole operator"),
            value("text_coord", coordinator),
            value("phone_coord", ""),
            value("email_coord", email),
            value("text_token", token),
            value("drop_region", ""),
            value("status_state", "WA"),
            value("check_active", active),
        ],
    }


class BoardMonday:
    """Just enough of monday for onboarding: one installers board with
    title-addressable columns, items whose writes stick, board webhooks."""

    def __init__(self, items=()):
        self.items = {str(i["id"]): i for i in items}
        self.written = []   # (item_id, values) from set_columns
        self.hooks = []

    def board_columns(self, board_id):
        return BOARD_COLUMNS

    def item(self, item_id):
        return self.items.get(str(item_id))

    def set_columns(self, board_id, item_id, values):
        self.written.append((str(item_id), values))
        item = self.items[str(item_id)]
        for column_id, value in values.items():
            text = value if isinstance(value, str) else (
                "v" if isinstance(value, dict) and value.get("checked") == "true"
                else json.dumps(value))
            for cell in item["column_values"]:
                if cell["id"] == column_id:
                    cell["text"] = text
                    break
        return {}

    def gql(self, query, variables=None, retries=3):
        if "items_page" in query and "columns" in query:
            return {"boards": [{
                "columns": [{"id": c["id"], "title": c["title"],
                             "type": c["type"]} for c in BOARD_COLUMNS],
                "items_page": {"items": [
                    {"id": i["id"], "name": i["name"],
                     "column_values": [{"id": c["id"], "text": c.get("text")}
                                       for c in i["column_values"]]}
                    for i in self.items.values()]},
            }]}
        raise AssertionError(f"unexpected gql in test: {query[:80]}")

    def webhooks(self, board_id):
        return self.hooks

    def create_webhook(self, board_id, url, event, config_json=None):
        hook = {"id": str(len(self.hooks) + 1), "event": event,
                "config": json.dumps(config_json) if config_json else None,
                "url": url}
        self.hooks.append(hook)
        return hook


class OnboardStore:
    """In-memory Store: the accounts mirror, the ledger, the audit trail."""

    enabled = True
    degraded = None

    def __init__(self):
        self.accounts = {}
        self.notifications = {}
        self.events = []

    def upsert_accounts(self, rows):
        for row in rows:
            self.accounts[row["monday_item_id"]] = row
        return rows

    def claim_notification(self, monday_item_id, kind, payload=None):
        key = (int(monday_item_id), kind)
        if key in self.notifications:
            return False
        self.notifications[key] = payload or {}
        return True

    def record_event(self, monday_item_id, action, **fields):
        self.events.append({"monday_item_id": monday_item_id,
                            "action": action, **fields})


def create_event(item_id):
    return {"event": {"type": "create_pulse", "boardId": BOARD_ID,
                      "pulseId": item_id}}


def change_event(item_id, column_id="text_token"):
    return {"event": {"type": "update_column_value", "boardId": BOARD_ID,
                      "pulseId": item_id, "columnId": column_id}}


@pytest.fixture(autouse=True)
def _onboard_env(monkeypatch):
    """A known board, a reachable app URL, and a stubbed email provider —
    provider() must not say "log", or every send is deferred by design."""
    monkeypatch.setattr(config, "INSTALLERS_BOARD_ID", BOARD_ID)
    monkeypatch.setenv("APP_URL", "https://navtek.example")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    delivered = []

    def fake_deliver(recipients, subject, html, text):
        delivered.append({"to": recipients, "subject": subject,
                          "html": html, "text": text})
        return {"ok": True, "provider": "test"}

    monkeypatch.setattr(emailer, "_deliver", fake_deliver)
    emailer.SENT.clear()
    yield delivered
    emailer.SENT.clear()


def test_new_row_gets_token_active_database_row_and_email(_onboard_env):
    monday = BoardMonday([make_row(501, "Saveez", email="sav@example.com",
                                   coordinator="Sav")])
    store = OnboardStore()
    result = onboarding.handle_account_event(monday, store, create_event(501))

    assert result["token_issued"] and result["activated"]
    written = dict(v for _, values in monday.written for v in values.items())
    token = written["text_token"]
    assert len(token) >= 40                      # token_urlsafe(32)
    assert written["check_active"] == {"checked": "true"}

    account = store.accounts[501]                # synced, with the new token
    assert account["portal_token"] == token
    assert account["active"] is True

    assert result["email"]["sent"]
    (email,) = _onboard_env
    assert email["to"] == ["sav@example.com"]
    assert f"https://navtek.example/j/{token}" in email["html"]


def test_the_echo_of_our_own_token_write_changes_nothing(_onboard_env):
    monday = BoardMonday([make_row(501, "Saveez", email="sav@example.com")])
    store = OnboardStore()
    onboarding.handle_account_event(monday, store, create_event(501))
    writes_before = len(monday.written)

    # The token write triggers a change_column_value delivery of its own.
    result = onboarding.handle_account_event(monday, store, change_event(501))

    assert len(monday.written) == writes_before  # nothing re-written
    assert not result["email"]["sent"]           # and nothing re-emailed
    assert len(_onboard_env) == 1


def test_a_change_event_never_reactivates_a_deactivated_account(_onboard_env):
    monday = BoardMonday([make_row(501, "Saveez", token="tok-501", active="",
                                   email="sav@example.com")])
    store = OnboardStore()
    result = onboarding.handle_account_event(
        monday, store, change_event(501, "check_active"))

    assert monday.written == []                  # Active stays unticked
    assert store.accounts[501]["active"] is False
    assert not result["email"]["sent"]           # inactive → no link email
    assert _onboard_env == []


def test_link_emails_itself_when_the_coordinator_email_arrives_later(_onboard_env):
    monday = BoardMonday([make_row(501, "Saveez")])
    store = OnboardStore()
    first = onboarding.handle_account_event(monday, store, create_event(501))
    assert not first["email"]["sent"]
    assert "coordinator email" in first["email"]["reason"]

    for cell in monday.items["501"]["column_values"]:
        if cell["id"] == "email_coord":
            cell["text"] = "sav@example.com"
    second = onboarding.handle_account_event(
        monday, store, change_event(501, "email_coord"))

    assert second["email"]["sent"]
    assert _onboard_env[0]["to"] == ["sav@example.com"]


def test_a_reissued_token_sends_a_fresh_link(_onboard_env):
    monday = BoardMonday([make_row(501, "Saveez", email="sav@example.com")])
    store = OnboardStore()
    onboarding.handle_account_event(monday, store, create_event(501))

    for cell in monday.items["501"]["column_values"]:
        if cell["id"] == "text_token":
            cell["text"] = "reissued-token-abcdef"
    result = onboarding.handle_account_event(monday, store, change_event(501))

    assert result["email"]["sent"]
    assert len(_onboard_env) == 2
    assert "/j/reissued-token-abcdef" in _onboard_env[1]["html"]
    assert store.accounts[501]["portal_token"] == "reissued-token-abcdef"


def test_no_email_provider_defers_the_send_instead_of_burning_it(
        _onboard_env, monkeypatch):
    monkeypatch.delenv("SMTP_HOST")              # provider() says "log" again
    monday = BoardMonday([make_row(501, "Saveez", email="sav@example.com")])
    store = OnboardStore()
    first = onboarding.handle_account_event(monday, store, create_event(501))
    assert first["email"].get("deferred")
    assert store.notifications == {}             # the one-shot claim survives

    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    second = onboarding.handle_account_event(monday, store, change_event(501))
    assert second["email"]["sent"]
    assert len(_onboard_env) == 1


def test_webhook_registration_is_idempotent():
    monday = BoardMonday()
    first = bootstrap.register_installer_webhooks(
        monday, "https://navtek.example", BOARD_ID)
    again = bootstrap.register_installer_webhooks(
        monday, "https://navtek.example", BOARD_ID)

    assert {h["event"] for h in monday.hooks} == {
        "create_item", "change_column_value"}
    assert len(monday.hooks) == 2
    assert all(r.get("webhook_id") for r in first["registered"])
    assert all(r.get("already_registered") for r in again["registered"])
    assert "/api/py/installer-account-change" in monday.hooks[0]["url"]
