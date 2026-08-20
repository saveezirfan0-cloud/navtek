"""The paginated webhook-delivery log behind the Deliveries tab.

The log grows by every drop and retry forever, so /webhooks pages server side
— and its failure modes must stay distinct: a missing table says "run the
migration", a broken database must NOT (that hint sends someone to re-run a
migration that was never the problem).
"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from fastapi.testclient import TestClient  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vercel_index_webhooks",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "api", "index.py"),
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

TEST_SECRET = "test-portal-secret"
_module.config.PORTAL_SHARED_SECRET = TEST_SECRET


def client():
    return TestClient(_module.app, raise_server_exceptions=False,
                      headers={"X-Portal-Secret": TEST_SECRET})


class FakeStore:
    """Pages over a fixed row list the way PostgREST would."""

    def __init__(self, rows, degraded=None):
        self.rows = rows
        self.enabled = True
        self.degraded = degraded
        self.calls = []

    def webhook_page(self, limit=25, offset=0, outcome=None, q=None):
        self.calls.append((limit, offset, outcome, q))
        if self.degraded:
            return [], 0
        rows = [r for r in self.rows
                if not outcome or r.get("outcome") == outcome]
        return rows[offset:offset + limit], len(rows)

    def ping(self):
        return {"ok": False, "state": "error", "detail": "fake"}


def _rows(n):
    return [{"monday_item_id": i, "outcome": "processed",
             "created_at": f"2026-08-{i + 1:02d}T00:00:00Z"} for i in range(n)]


def _use(monkeypatch, fake):
    monkeypatch.setattr(_module, "Store", lambda: fake)
    return fake


def test_a_page_carries_its_rows_and_the_whole_logs_total(monkeypatch):
    fake = _use(monkeypatch, FakeStore(_rows(60)))
    data = client().get("/api/py/webhooks?limit=25&offset=25").json()
    assert data["enabled"] is True
    assert data["total"] == 60
    assert len(data["webhooks"]) == 25
    assert data["webhooks"][0]["monday_item_id"] == 25
    assert fake.calls == [(25, 25, None, "")]


def test_limit_and_offset_are_clamped_not_trusted(monkeypatch):
    fake = _use(monkeypatch, FakeStore(_rows(5)))
    client().get("/api/py/webhooks?limit=9999&offset=-3")
    assert fake.calls == [(100, 0, None, "")]


def test_the_outcome_filter_narrows_the_whole_log_not_the_page(monkeypatch):
    rows = _rows(3)
    rows[1]["outcome"] = "skipped"
    fake = _use(monkeypatch, FakeStore(rows))
    data = client().get("/api/py/webhooks?outcome=skipped").json()
    assert data["total"] == 1
    assert [h["outcome"] for h in data["webhooks"]] == ["skipped"]
    # An outcome the schema doesn't know is dropped, not passed to the query.
    client().get("/api/py/webhooks?outcome=exploded")
    assert fake.calls[-1][2] is None


def test_a_missing_table_says_run_the_migration(monkeypatch):
    _use(monkeypatch, FakeStore([], degraded="HTTP 404 reading webhook_log"))
    data = client().get("/api/py/webhooks").json()
    assert data["enabled"] is True
    assert data["webhook_log_ready"] is False


def test_a_broken_database_does_not_masquerade_as_a_missing_migration(monkeypatch):
    _use(monkeypatch, FakeStore([], degraded="HTTP 401 reading webhook_log"))
    data = client().get("/api/py/webhooks").json()
    assert data["enabled"] is False
    assert "webhook_log_ready" not in data


def test_the_log_is_not_public():
    bare = TestClient(_module.app, raise_server_exceptions=False)
    assert bare.get("/api/py/webhooks").status_code == 401
