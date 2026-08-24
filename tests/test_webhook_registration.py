"""Registering — and RE-registering — the monday webhooks.

The Qualityvend failure of 23 Aug: the automation fired, and this app turned
the delivery away with "?hook= token does not match WEBHOOK_SECRET". The secret
had been rotated, but the token is baked into the URL monday holds, and monday
can neither change a webhook's address nor report it back. Re-running setup
step 4 answered "already registered" and changed nothing, so every order was
being dropped at the door with nothing on the row to show for it.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import bootstrap, config  # noqa: E402

BOARD = 18426505553


class FakeMonday:
    """Records registrations the way monday's API exposes them — note that
    `url` is absent, because monday genuinely does not return it."""

    def __init__(self, existing=None):
        self.hooks = list(existing or [])
        self.created = []
        self.deleted = []
        self._next = 100

    def webhooks(self, board_id):
        return [{k: v for k, v in h.items() if k != "url"} for h in self.hooks]

    def create_webhook(self, board_id, url, event, config_json=None):
        self._next += 1
        hook = {"id": str(self._next), "event": event, "url": url,
                "config": __import__("json").dumps(config_json or {})}
        self.hooks.append(hook)
        self.created.append((url, event))
        return {"id": hook["id"], "board_id": str(board_id)}

    def delete_webhook(self, webhook_id):
        self.deleted.append(str(webhook_id))
        self.hooks = [h for h in self.hooks if str(h["id"]) != str(webhook_id)]
        return {"id": str(webhook_id)}


def _existing(column_id, url):
    import json
    return [{"id": "9", "event": "change_specific_column_value",
             "url": url, "config": json.dumps({"columnId": column_id})}]


def test_an_existing_registration_is_left_alone_by_default():
    """Registering twice would ingest every dropped file twice."""
    monday = FakeMonday(_existing("file_eorder", "https://app/api/py/eorder?hook=old"))
    result = bootstrap._register_column_webhook(
        monday, BOARD, "file_eorder", "https://app/api/py/eorder?hook=new")
    assert result["already_registered"] is True
    assert monday.created == []
    assert monday.deleted == []


def test_force_replaces_a_registration_carrying_a_stale_hook_token():
    """The repair. monday cannot change a webhook's URL, so the only way to
    correct one is to delete it and register again."""
    monday = FakeMonday(_existing("file_eorder", "https://app/api/py/eorder?hook=old"))
    result = bootstrap._register_column_webhook(
        monday, BOARD, "file_eorder", "https://app/api/py/eorder?hook=new",
        force=True)
    assert result.get("replaced") is True
    assert result.get("already_registered") is None
    assert monday.deleted == ["9"]
    assert monday.created == [("https://app/api/py/eorder?hook=new",
                               "change_specific_column_value")]
    # Exactly one registration for the column afterwards — never two.
    assert len(monday.hooks) == 1


def test_force_still_registers_when_there_was_nothing_to_replace():
    monday = FakeMonday()
    result = bootstrap._register_column_webhook(
        monday, BOARD, "file_eorder", "https://app/api/py/eorder?hook=new",
        force=True)
    assert result["webhook_id"]
    assert monday.deleted == []
    assert len(monday.created) == 1


def test_the_registered_url_carries_the_current_secret(monkeypatch):
    """The token comes from config at registration time, which is why rotating
    it without re-registering breaks every delivery."""
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "current-secret")
    monkeypatch.setattr(config, "ORDERS_BOARD_ID", BOARD)
    monday = FakeMonday()
    bootstrap.register_webhook(monday, "https://app/api/py/eorder",
                               board_id=BOARD, file_column_id="file_eorder")
    url, _ = monday.created[0]
    assert url == "https://app/api/py/eorder?hook=current-secret"


def test_board_level_installer_webhooks_are_replaced_under_force(monkeypatch):
    """Board-level events carry no config, so they are matched by event type —
    that path needed the same repair as the column webhooks."""
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "new")
    monkeypatch.setattr(config, "INSTALLERS_BOARD_ID", 18426336129)
    monday = FakeMonday([
        {"id": "7", "event": "create_item", "url": "https://app/x?hook=old",
         "config": None},
        {"id": "8", "event": "change_column_value", "url": "https://app/x?hook=old",
         "config": None},
    ])
    result = bootstrap.register_installer_webhooks(monday, "https://app", force=True)
    assert sorted(monday.deleted) == ["7", "8"]
    assert all(r.get("replaced") for r in result["registered"])
    assert all("hook=new" in url for url, _ in monday.created)
