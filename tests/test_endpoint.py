"""The webhook endpoint's contract with monday.

monday retries any non-2xx delivery. A retry of a bad file cannot succeed —
it re-runs the failure path and posts a duplicate ❌ Update, which is the
notification storm these tests exist to prevent coming back.
"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from fastapi.testclient import TestClient  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vercel_index",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "api", "index.py"),
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def client():
    return TestClient(_module.app, raise_server_exceptions=False)


def test_a_failed_ingest_still_returns_200_so_monday_does_not_retry(monkeypatch):
    monkeypatch.setattr(
        _module, "handle_webhook",
        lambda payload: {"ok": False, "reason": "simulated bad file"},
    )
    response = client().post("/api/py/eorder", json={"event": {"pulseId": 1}})
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_a_successful_ingest_returns_200(monkeypatch):
    monkeypatch.setattr(
        _module, "handle_webhook", lambda payload: {"ok": True, "status": "✅ Read"},
    )
    response = client().post("/api/py/eorder", json={"event": {"pulseId": 1}})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_the_registration_challenge_is_echoed():
    response = client().post("/api/py/eorder", json={"challenge": "abc123"})
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_health_names_the_build_that_is_running():
    """The stamp exists so "is the new code deployed" is readable, not guessed."""
    response = client().get("/api/py/health")
    assert response.status_code == 200
    build = response.json().get("build") or {}
    assert build.get("version"), "health must carry the build version"
