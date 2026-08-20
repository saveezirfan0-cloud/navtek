"""Webhook signature verification and the paginated read ledger.

The webhook endpoints are reachable from the open internet and drive monday
writes with the account-wide token; with MONDAY_SIGNING_SECRET set, only a
delivery monday actually signed may get in. And /recent's filters must reach
the query — a search that only covers the loaded page is the bug these
replaced.
"""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from fastapi.testclient import TestClient  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vercel_index_hardening",
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


# -- monday webhook signatures ----------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _jwt(secret: str) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iat": 0}).encode())
    sig = _b64(hmac.new(secret.encode(), f"{head}.{body}".encode(),
                        hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def test_a_signed_delivery_gets_in(monkeypatch):
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module, "handle_webhook", lambda payload: {"ok": True})
    response = client().post(
        "/api/py/eorder", json={"event": {"pulseId": 1}},
        headers={"Authorization": _jwt("sign-me")},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_an_unsigned_or_missigned_delivery_is_turned_away(monkeypatch):
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    calls = []
    monkeypatch.setattr(_module, "handle_webhook",
                        lambda payload: calls.append(payload))
    for headers in ({}, {"Authorization": _jwt("some-other-secret")},
                    {"Authorization": "Bearer garbage"}):
        response = client().post("/api/py/eorder",
                                 json={"event": {"pulseId": 1}}, headers=headers)
        assert response.status_code == 401
    assert calls == []


def test_the_challenge_handshake_is_signed_too(monkeypatch):
    """monday signs the registration challenge like any delivery — an
    unsigned challenge must not be echoed, or registration proves nothing."""
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    ok = client().post("/api/py/eorder", json={"challenge": "abc"},
                       headers={"Authorization": _jwt("sign-me")})
    assert ok.json() == {"challenge": "abc"}
    bad = client().post("/api/py/eorder", json={"challenge": "abc"})
    assert bad.status_code == 401


def test_with_no_signing_secret_behaviour_is_unchanged(monkeypatch):
    monkeypatch.setattr(_module, "handle_webhook", lambda payload: {"ok": True})
    response = client().post("/api/py/eorder", json={"event": {"pulseId": 1}})
    assert response.status_code == 200


# -- the paginated, searchable read ledger ----------------------------------

class FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.enabled = True
        self.degraded = None
        self.calls = []

    def ingest_page(self, limit=20, offset=0, status=None, q=None):
        self.calls.append((limit, offset, status, q))
        rows = [r for r in self.rows if not status or r.get("status") == status]
        return rows[offset:offset + limit], len(rows)

    def ingest_counts(self):
        return {s: sum(1 for r in self.rows if r.get("status") == s)
                for s in ("read", "check", "failed")}


def _ingests(n, status="read"):
    return [{"monday_item_id": i, "status": status, "parsed": {},
             "created_at": f"2026-08-{i + 1:02d}T00:00:00Z"} for i in range(n)]


def test_recent_pages_and_counts_the_whole_ledger(monkeypatch):
    fake = FakeStore(_ingests(30) + _ingests(2, "failed"))
    monkeypatch.setattr(_module, "Store", lambda: fake)
    data = client().get("/api/py/recent?limit=10&offset=10&q=kane").json()
    assert data["total"] == 32
    assert len(data["ingests"]) == 10
    assert data["counts"] == {"read": 30, "check": 0, "failed": 2}
    assert fake.calls == [(10, 10, None, "kane")]


def test_recent_rejects_an_unknown_status_rather_than_querying_it(monkeypatch):
    fake = FakeStore(_ingests(3))
    monkeypatch.setattr(_module, "Store", lambda: fake)
    client().get("/api/py/recent?status=exploded")
    assert fake.calls[-1][2] is None


# -- the search pattern is defused, not trusted ------------------------------

def test_search_terms_cannot_break_out_of_the_filter_list():
    from _lib.store import Store
    assert Store._search_pattern("kane civil") == "*kane civil*"
    assert Store._search_pattern("a,b(c)") == "*a b c*"
    assert Store._search_pattern("  ") == ""


# -- retention ---------------------------------------------------------------

def test_purge_is_off_when_retention_is_zero():
    from _lib.store import Store
    store = Store(url="", key="")   # disabled either way — must not matter
    assert store.purge_logs(0) == {"purged": False}
    assert store.purge_logs(None) == {"purged": False}
