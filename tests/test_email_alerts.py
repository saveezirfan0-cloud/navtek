"""The ⚠️ Check / ❌ Failed alert emails, end to end through the ingest.

Real files, real parser — a fake monday, a fake store, and the emailer's
logging stub (no provider env is set, conftest scrubs it). What these pin
down: a failed read emails the configured recipients exactly once, a clean
read emails nobody, and the /settings toggles are honoured.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import emailer  # noqa: E402

from test_ingest import KANE, FakeMonday, FakeStore, blob, run  # noqa: E402


class SettingsStore(FakeStore):
    """FakeStore plus the settings + notification-ledger surface the
    emailer uses — the same claim-before-send contract as the real Store."""

    def __init__(self, settings=None, broken=False):
        super().__init__(broken=broken)
        self.settings = settings or {}
        self.notification_claims = set()
        self.events = []

    def get_setting(self, key):
        return self.settings.get(key)

    def claim_notification(self, item_id, kind, payload=None):
        if (item_id, kind) in self.notification_claims:
            return False
        self.notification_claims.add((item_id, kind))
        return True

    def record_event(self, item_id, action, **fields):
        self.events.append((item_id, action, fields))
        return []


RECIPIENTS = {"emails": ["ops@navtek.example"], "notify_check": True,
              "notify_failed": True}


def setup_function(_):
    emailer.SENT.clear()


def test_failed_read_emails_the_configured_recipients():
    store = SettingsStore({emailer.SETTINGS_KEY: RECIPIENTS})
    monday = FakeMonday(b"not an xlsx at all")
    result, _, _ = run(KANE, store=store, monday=monday)
    assert not result["ok"]
    assert result["alert_email"]["sent"] is True
    assert emailer.SENT[-1]["to"] == ["ops@navtek.example"]
    assert "failed" in emailer.SENT[-1]["subject"].lower()
    # The send is on the audit trail too.
    assert any(action == "email_sent" for _, action, _ in store.events)


def test_clean_read_emails_nobody():
    store = SettingsStore({emailer.SETTINGS_KEY: RECIPIENTS})
    result, _, _ = run(KANE, store=store)
    assert result["ok"] and result["status"] == "✅ Read"
    assert result["alert_email"]["sent"] is False
    assert emailer.SENT == []


def test_same_failure_replayed_is_not_re_emailed():
    store = SettingsStore({emailer.SETTINGS_KEY: RECIPIENTS})
    first, _, _ = run(KANE, store=store, monday=FakeMonday(b"broken"))
    assert first["alert_email"]["sent"] is True
    # The same delivery again — new webhook, same file, same failure.
    second, _, _ = run(KANE, store=store, monday=FakeMonday(b"broken"))
    assert second["alert_email"]["sent"] is False
    assert second["alert_email"]["reason"] == "already emailed"
    assert len(emailer.SENT) == 1


def test_no_recipients_configured_means_no_send():
    store = SettingsStore()   # nothing saved on /settings yet
    result, _, _ = run(KANE, store=store, monday=FakeMonday(b"broken"))
    assert result["alert_email"]["sent"] is False
    assert "no notification emails" in result["alert_email"]["reason"]
    assert emailer.SENT == []


def test_failed_toggle_off_is_honoured():
    store = SettingsStore({emailer.SETTINGS_KEY: {
        "emails": ["ops@navtek.example"], "notify_failed": False}})
    result, _, _ = run(KANE, store=store, monday=FakeMonday(b"broken"))
    assert result["alert_email"]["sent"] is False
    assert emailer.SENT == []


def test_store_without_settings_surface_degrades_quietly():
    """An older database (no app_settings table → the plain FakeStore has no
    get_setting) must cost the alert, never the order."""
    result, _, _ = run(KANE, monday=FakeMonday(b"broken"))
    assert result["alert_email"]["sent"] is False


def test_clean_emails_parses_whatever_was_saved():
    assert emailer.clean_emails("a@b.co\nB@b.co, a@b.co; not-an-email") == [
        "a@b.co", "b@b.co"]
    assert emailer.clean_emails(None) == []
    assert emailer.clean_emails(["x@y.zz ", "x@y.zz"]) == ["x@y.zz"]


def test_settings_merge_over_defaults():
    store = SettingsStore({emailer.SETTINGS_KEY: {"emails": ["a@b.co"]}})
    merged = emailer.notification_settings(store)
    assert merged == {"emails": ["a@b.co"], "notify_check": True,
                      "notify_failed": True}
