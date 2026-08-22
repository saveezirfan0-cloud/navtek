"""Webhook admission control and the paginated read ledger.

The webhook endpoints are reachable from the open internet and drive monday
writes with the account-wide token. Two locks guard them, and the rule that
outranks both: never answer monday with a 4xx. monday deactivates a webhook
automation whose endpoint returns an authentication error, so a mismatched
secret has to cost one delivery, not the integration — which is what happened
when MONDAY_SIGNING_SECRET was set against personal-token webhooks that monday
never signs. And /recent's filters must reach the query — a search that only
covers the loaded page is the bug these replaced.
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


class RejectionLog:
    """Stands in for the delivery log so a drop can be asserted on."""

    def __init__(self):
        self.rows = []

    def record_webhook(self, **fields):
        self.rows.append(fields)
        return []


def _catch_rejections(monkeypatch):
    log = RejectionLog()
    monkeypatch.setattr(_module, "Store", lambda: log)
    return log


def test_a_signed_delivery_gets_in(monkeypatch):
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module, "handle_webhook", lambda payload: {"ok": True})
    response = client().post(
        "/api/py/eorder", json={"event": {"pulseId": 1}},
        headers={"Authorization": _jwt("sign-me")},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_an_unsigned_delivery_gets_in_because_monday_never_signed_it(monkeypatch):
    """The regression this file exists for.

    monday only signs webhooks created through an app's OAuth token. Ours are
    created with the personal API token, so every real delivery arrives with no
    Authorization header — and rejecting those is what got the automation
    deactivated. Absent is normal; only present-and-wrong is a rejection.
    """
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_REQUIRED", False)
    log = _catch_rejections(monkeypatch)
    monkeypatch.setattr(_module, "handle_webhook", lambda payload: {"ok": True})
    response = client().post("/api/py/eorder", json={"event": {"pulseId": 1}})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert log.rows == []


def test_a_missigned_delivery_is_dropped_with_200_not_401(monkeypatch):
    """A wrong signature costs the delivery. It must not cost the automation:
    monday deactivates an endpoint that answers an auth error."""
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    log = _catch_rejections(monkeypatch)
    calls = []
    monkeypatch.setattr(_module, "handle_webhook",
                        lambda payload: calls.append(payload))
    for headers in ({"Authorization": _jwt("some-other-secret")},
                    {"Authorization": "Bearer garbage"}):
        response = client().post("/api/py/eorder",
                                 json={"event": {"pulseId": 1}}, headers=headers)
        assert response.status_code == 200
        assert response.json()["ok"] is False
    assert calls == []
    assert [r["outcome"] for r in log.rows] == ["rejected", "rejected"]


def test_signing_required_turns_unsigned_back_into_a_rejection(monkeypatch):
    """The opt-in for an account that really is on OAuth — still a 200."""
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_REQUIRED", True)
    log = _catch_rejections(monkeypatch)
    calls = []
    monkeypatch.setattr(_module, "handle_webhook",
                        lambda payload: calls.append(payload))
    response = client().post("/api/py/eorder", json={"event": {"pulseId": 1}})
    assert response.status_code == 200
    assert calls == []
    assert log.rows[0]["outcome"] == "rejected"


def test_the_challenge_handshake_is_never_gated_on_a_signature(monkeypatch):
    """monday replays the handshake to re-verify a live webhook, and a
    personal-token webhook has nothing to sign it. Refusing the handshake is
    how registration breaks and the automation gets switched off."""
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_REQUIRED", True)
    _catch_rejections(monkeypatch)
    for headers in ({}, {"Authorization": _jwt("sign-me")},
                    {"Authorization": "Bearer garbage"}):
        response = client().post("/api/py/eorder", json={"challenge": "abc"},
                                 headers=headers)
        assert response.status_code == 200
        assert response.json() == {"challenge": "abc"}


def test_a_bad_hook_token_is_dropped_with_200_and_logged(monkeypatch):
    monkeypatch.setattr(_module.config, "WEBHOOK_SECRET", "url-token")
    log = _catch_rejections(monkeypatch)
    calls = []
    monkeypatch.setattr(_module, "handle_webhook",
                        lambda payload: calls.append(payload))
    response = client().post("/api/py/eorder?hook=wrong",
                             json={"event": {"pulseId": 1}})
    assert response.status_code == 200
    assert calls == []
    assert log.rows[0]["outcome"] == "rejected"

    ok = client().post("/api/py/eorder?hook=url-token",
                       json={"event": {"pulseId": 1}})
    assert ok.status_code == 200
    assert len(calls) == 1


def test_every_webhook_endpoint_refuses_to_answer_with_a_4xx(monkeypatch):
    """Whatever is wrong, monday must never see an auth error from any of
    them — one 401 anywhere here is one deactivated automation."""
    monkeypatch.setattr(_module.config, "WEBHOOK_SECRET", "url-token")
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_SECRET", "sign-me")
    monkeypatch.setattr(_module.config, "MONDAY_SIGNING_REQUIRED", True)
    _catch_rejections(monkeypatch)
    for path in ("/api/py/eorder", "/api/py/installer-change",
                 "/api/py/installer-account-change", "/api/py/portal/refresh"):
        response = client().post(f"{path}?hook=wrong", json={"event": {"pulseId": 1}})
        assert response.status_code == 200, path


def test_a_body_that_is_not_a_json_object_does_not_500(monkeypatch):
    """A 500 is a non-2xx too, and monday counts it the same way."""
    _catch_rejections(monkeypatch)
    calls = []
    monkeypatch.setattr(_module, "handle_webhook",
                        lambda payload: calls.append(payload))
    for body in (b"{not json", b"[1, 2, 3]", b'"a string"'):
        response = client().post("/api/py/eorder", content=body,
                                 headers={"Content-Type": "application/json"})
        assert response.status_code == 200, body
        assert response.json()["ok"] is False
    assert calls == []


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
