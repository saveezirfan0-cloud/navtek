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


def client():
    return TestClient(_module.app, raise_server_exceptions=False)


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
