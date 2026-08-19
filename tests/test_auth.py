"""Logins: the hashing, the guards, and the failure that matters most —
a database that isn't there must say so, not fail like a wrong password."""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from fastapi.testclient import TestClient  # noqa: E402

from _lib import users  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vercel_index_auth",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "api", "index.py"),
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

# _authorise fails CLOSED: with no PORTAL_SHARED_SECRET configured, every
# guarded route answers 503 rather than running open. These tests exercise the
# guards BEHIND that door, so they configure a secret and knock properly.
TEST_SECRET = "test-portal-secret"
_module.config.PORTAL_SHARED_SECRET = TEST_SECRET


def client():
    return TestClient(_module.app, raise_server_exceptions=False,
                      headers={"X-Portal-Secret": TEST_SECRET})


def test_a_missing_portal_secret_fails_closed(monkeypatch):
    """No secret configured must mean nobody gets in — not everybody."""
    monkeypatch.setattr(_module.config, "PORTAL_SHARED_SECRET", "")
    bare = TestClient(_module.app, raise_server_exceptions=False)
    response = bare.get("/api/py/auth/me")
    assert response.status_code == 503
    assert "PORTAL_SHARED_SECRET" in response.json()["detail"]


def test_a_wrong_portal_secret_is_refused():
    bare = TestClient(_module.app, raise_server_exceptions=False,
                      headers={"X-Portal-Secret": "not-the-secret"})
    assert bare.get("/api/py/auth/me").status_code == 401


# -- passwords -------------------------------------------------------------

def test_a_password_verifies_against_its_own_hash():
    stored = users.hash_password("correct horse battery")
    assert users.verify_password("correct horse battery", stored)
    assert not users.verify_password("wrong horse", stored)


def test_two_hashes_of_the_same_password_differ():
    """Salted — a leaked table must not reveal who shares a password."""
    assert users.hash_password("same") != users.hash_password("same")


def test_garbage_hashes_never_verify_and_never_raise():
    for stored in ("", None, "plaintext", "a$b$c", "pbkdf2_sha256$x$y$z"):
        assert users.verify_password("anything", stored) is False


def test_short_passwords_are_refused():
    assert users.password_problem("short") is not None
    assert users.password_problem("long enough now") is None


# -- sessions --------------------------------------------------------------

def test_the_stored_session_hash_is_not_the_token():
    token = users.new_session_token()
    assert users.token_sha(token) != token
    assert len(users.token_sha(token)) == 64


def test_public_user_never_carries_the_hash():
    shaped = users.public_user({
        "id": "u1", "email": "a@b.c", "name": "A",
        "password_hash": "pbkdf2_sha256$1$aa$bb", "is_admin": True,
    })
    assert "password_hash" not in shaped
    assert shaped["can_orders"] is True  # admin implies orders


# -- endpoint guards -------------------------------------------------------
#
# No database is configured in tests, so Store().enabled is False. The routes
# must answer with a clear 503 ("database isn't connected"), never a 401 that
# sends someone off to reset a password that was fine.

def test_login_without_a_database_names_the_database():
    response = client().post("/api/py/auth/login",
                             json={"email": "a@b.c", "password": "irrelevant!"})
    assert response.status_code == 503
    assert "database" in response.json()["detail"].lower()


def test_me_without_a_session_is_signed_out():
    response = client().get("/api/py/auth/me")
    assert response.status_code == 401


def test_bootstrap_requires_the_setup_key(monkeypatch):
    monkeypatch.setattr(_module, "SETUP_KEY", "the-key")
    response = client().post(
        "/api/py/auth/bootstrap",
        json={"email": "a@b.c", "name": "A", "password": "long enough now"},
        headers={"X-Setup-Key": "wrong"},
    )
    assert response.status_code == 401


def test_user_management_requires_a_session():
    assert client().get("/api/py/users").status_code == 401
    assert client().post("/api/py/users/update", json={"id": "x"}).status_code == 401


def test_my_jobs_requires_a_session():
    assert client().get("/api/py/portal/my-jobs").status_code == 401


def test_previewing_a_user_requires_a_session():
    """Preview renders the app through another login's eyes — admin only,
    and the httpOnly cookie that drives it is inert without an admin session."""
    assert client().get("/api/py/users/preview?user_id=x").status_code == 401
    assert client().get("/api/py/portal/preview-jobs?user_id=x").status_code == 401


# -- the positive paths, against an injectable in-memory store ---------------
#
# Every route constructs Store() internally, so these monkeypatch the module's
# Store name. Before this, only the guard (negative) paths had tests: a flipped
# session-expiry comparison or a dropped active check would have shipped green.

class FakeUserStore:
    def __init__(self):
        self.enabled = True
        self.degraded = None
        self.users = {}
        self.sessions = {}
        self.failed_logins = []

    def ping(self):
        return {"ok": True, "state": "ready"}

    def users_exist(self):
        return bool(self.users)

    def user_by_email(self, email):
        for row in self.users.values():
            if row["email"] == email:
                return dict(row)
        return None

    def user_by_id(self, user_id):
        row = self.users.get(user_id)
        return dict(row) if row else None

    def list_users(self):
        return [dict(r) for r in self.users.values()]

    def create_user(self, fields):
        import uuid
        row = {"id": str(uuid.uuid4()), "active": True, "is_admin": False,
               "can_orders": False, "can_installer": False,
               "installer_account_id": None, **fields}
        self.users[row["id"]] = row
        return dict(row)

    def update_user(self, user_id, fields):
        if user_id not in self.users:
            return None
        self.users[user_id].update(fields)
        return dict(self.users[user_id])

    def create_session(self, user_id, token_sha256, expires_at, user_agent=None):
        self.sessions[token_sha256] = {"user_id": user_id, "expires_at": expires_at}
        return {"id": token_sha256}

    def session_user(self, token_sha256):
        from datetime import datetime, timezone
        session = self.sessions.get(token_sha256)
        if not session:
            return None
        expires = datetime.fromisoformat(
            str(session["expires_at"]).replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            del self.sessions[token_sha256]
            return None
        row = self.users.get(session["user_id"])
        return dict(row) if row and row.get("active") else None

    def delete_session(self, token_sha256):
        self.sessions.pop(token_sha256, None)
        return True

    def delete_user_sessions(self, user_id):
        self.sessions = {k: v for k, v in self.sessions.items()
                         if v["user_id"] != user_id}
        return True

    def recent_failed_logins(self, email, minutes=15):
        return self.failed_logins.count(email)

    def record_failed_login(self, email):
        self.failed_logins.append(email)
        return []

    def account_by_id(self, account_id):
        return None


def wired(monkeypatch):
    fake = FakeUserStore()
    monkeypatch.setattr(_module, "Store", lambda *a, **k: fake)
    monkeypatch.setattr(_module, "SETUP_KEY", "the-key")
    return fake


def bootstrap_admin(c):
    response = c.post(
        "/api/py/auth/bootstrap",
        json={"email": "admin@navtek.au", "name": "Admin",
              "password": "long enough now"},
        headers={"X-Setup-Key": "the-key"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_bootstrap_then_me_round_trips_a_session(monkeypatch):
    wired(monkeypatch)
    c = client()
    data = bootstrap_admin(c)
    assert data["user"]["is_admin"] is True
    me = c.get("/api/py/auth/me", headers={"X-Session": data["token"]})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@navtek.au"
    # And only while the users table is empty — after that, never again.
    assert c.post(
        "/api/py/auth/bootstrap",
        json={"email": "x@y.z", "name": "X", "password": "long enough now"},
        headers={"X-Setup-Key": "the-key"},
    ).status_code == 409


def test_login_succeeds_with_the_right_password_only(monkeypatch):
    wired(monkeypatch)
    c = client()
    bootstrap_admin(c)
    ok = c.post("/api/py/auth/login",
                json={"email": "admin@navtek.au", "password": "long enough now"})
    assert ok.status_code == 200 and ok.json()["token"]
    bad = c.post("/api/py/auth/login",
                 json={"email": "admin@navtek.au", "password": "wrong password!"})
    assert bad.status_code == 401


def test_eight_failed_logins_park_the_email(monkeypatch):
    wired(monkeypatch)
    c = client()
    bootstrap_admin(c)
    for _ in range(8):
        assert c.post("/api/py/auth/login",
                      json={"email": "admin@navtek.au", "password": "nope nope!"},
                      ).status_code == 401
    throttled = c.post("/api/py/auth/login",
                       json={"email": "admin@navtek.au",
                             "password": "long enough now"})
    assert throttled.status_code == 429  # even the RIGHT password waits now


def test_an_expired_session_is_signed_out(monkeypatch):
    fake = wired(monkeypatch)
    c = client()
    token = bootstrap_admin(c)["token"]
    for session in fake.sessions.values():
        session["expires_at"] = "2020-01-01T00:00:00+00:00"
    assert c.get("/api/py/auth/me",
                 headers={"X-Session": token}).status_code == 401


def test_deactivating_a_user_kills_their_sessions_immediately(monkeypatch):
    fake = wired(monkeypatch)
    c = client()
    admin_token = bootstrap_admin(c)["token"]
    created = c.post(
        "/api/py/users",
        json={"email": "staff@navtek.au", "name": "Staff",
              "password": "long enough now", "can_orders": True},
        headers={"X-Session": admin_token},
    )
    assert created.status_code == 200, created.text
    staff_token = c.post(
        "/api/py/auth/login",
        json={"email": "staff@navtek.au", "password": "long enough now"},
    ).json()["token"]
    assert c.get("/api/py/auth/me",
                 headers={"X-Session": staff_token}).status_code == 200
    off = c.post(
        "/api/py/users/update",
        json={"id": created.json()["user"]["id"], "active": False},
        headers={"X-Session": admin_token},
    )
    assert off.status_code == 200, off.text
    assert c.get("/api/py/auth/me",
                 headers={"X-Session": staff_token}).status_code == 401


def test_an_admin_cannot_lock_themselves_out(monkeypatch):
    wired(monkeypatch)
    c = client()
    data = bootstrap_admin(c)
    for change in ({"is_admin": False}, {"active": False}):
        response = c.post(
            "/api/py/users/update",
            json={"id": data["user"]["id"], **change},
            headers={"X-Session": data["token"]},
        )
        assert response.status_code == 400


# -- the SLA sweep endpoint ---------------------------------------------------

def test_the_sweep_needs_the_portal_secret_or_the_cron_secret(monkeypatch):
    bare = TestClient(_module.app, raise_server_exceptions=False)
    assert bare.post("/api/py/sla/sweep").status_code == 401

    monkeypatch.setattr(_module.config, "CRON_SECRET", "cron-secret")
    cron = TestClient(_module.app, raise_server_exceptions=False,
                      headers={"Authorization": "Bearer cron-secret"})
    response = cron.get("/api/py/sla/sweep")
    # No SLA_GO_LIVE_DATE in tests → the sweep answers, and says it's off.
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_the_activity_feed_is_admin_only():
    assert client().get("/api/py/activity").status_code == 401
