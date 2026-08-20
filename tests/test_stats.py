"""The /stats aggregation behind the dashboard's activity chart.

Aggregated server side (PostgREST doesn't group), so what's pinned here is
the aggregation itself: every day in the window appears exactly once even
with no rows, counts land on the right day, the success rate is reads over
everything, and the percentiles come from the recorded durations.
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from fastapi.testclient import TestClient  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vercel_index_stats",
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
    def __init__(self, rows, degraded=None):
        self.rows = rows
        self.enabled = True
        self.degraded = degraded

    def ingests_since(self, cutoff, limit=2000):
        return [] if self.degraded else self.rows

    def ping(self):
        return {"ok": False, "state": "error", "detail": "fake"}


def _use(monkeypatch, fake):
    monkeypatch.setattr(_module, "Store", lambda: fake)
    return fake


def _day(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


def test_every_day_in_the_window_appears_once_and_counts_land_on_it(monkeypatch):
    _use(monkeypatch, FakeStore([
        {"status": "read", "created_at": f"{_day(0)}T10:00:00Z", "duration_ms": 100},
        {"status": "read", "created_at": f"{_day(0)}T11:00:00Z", "duration_ms": 200},
        {"status": "check", "created_at": f"{_day(1)}T09:00:00Z", "duration_ms": 300},
        {"status": "failed", "created_at": f"{_day(2)}T08:00:00Z", "duration_ms": 400},
    ]))
    data = client().get("/api/py/stats?days=30").json()
    assert data["enabled"] is True
    assert len(data["days"]) == 30
    assert data["days"][-1] == {"date": _day(0), "read": 2, "check": 0, "failed": 0}
    assert data["days"][-2] == {"date": _day(1), "read": 0, "check": 1, "failed": 0}
    assert data["totals"] == {"read": 2, "check": 1, "failed": 1}
    assert data["success_rate"] == 0.5
    assert data["median_ms"] == 300


def test_no_rows_is_a_flat_window_not_an_error(monkeypatch):
    _use(monkeypatch, FakeStore([]))
    data = client().get("/api/py/stats").json()
    assert data["enabled"] is True
    assert len(data["days"]) == 30
    assert data["success_rate"] is None
    assert data["median_ms"] is None


def test_the_window_is_clamped(monkeypatch):
    _use(monkeypatch, FakeStore([]))
    assert len(client().get("/api/py/stats?days=9999").json()["days"]) == 90
    assert len(client().get("/api/py/stats?days=1").json()["days"]) == 7


def test_stats_are_not_public():
    bare = TestClient(_module.app, raise_server_exceptions=False)
    assert bare.get("/api/py/stats").status_code == 401
