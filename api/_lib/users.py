"""Logins for the web app.

Who signs in, what they can see, and how a browser proves who it is. The
Next.js half never sees a password hash or the monday token — it holds an
opaque session token in an httpOnly cookie and asks this service what that
token means.

Design points, each load-bearing:

* Passwords are PBKDF2-SHA256, stdlib only. This runs in a serverless function
  where every dependency is cold-start weight; bcrypt/argon2 would be nicer but
  pull in native wheels for marginal gain at this user count.
* Sessions store only the SHA-256 of the token. A database read alone cannot be
  replayed as a login.
* Access is two independent switches an admin flips per user — `can_orders`
  (the order dashboard side) and `can_installer` (the portal side, which also
  needs the user linked to an installer account). `is_admin` implies both and
  adds user management and setup.
* Login errors are deliberately vague ("email or password is wrong") but
  database problems are not — "the database isn't connected" sends someone to
  fix the right thing.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 310_000
SESSION_DAYS = 30


# -- passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = (stored or "").split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, AttributeError):
        return False


# -- sessions --------------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_sha(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def session_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()


# -- shaping ---------------------------------------------------------------

def public_user(row: dict) -> dict:
    """The user record as the browser is allowed to see it. Never the hash."""
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "name": row.get("name"),
        "is_admin": bool(row.get("is_admin")),
        "can_orders": bool(row.get("is_admin")) or bool(row.get("can_orders")),
        "can_installer": bool(row.get("can_installer")),
        "installer_account_id": row.get("installer_account_id"),
        "active": bool(row.get("active")),
        "created_at": row.get("created_at"),
        "last_login_at": row.get("last_login_at"),
    }


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def password_problem(password: str):
    """A reason the password is not acceptable, or None."""
    if not password or len(password) < 10:
        return "Passwords need at least 10 characters."
    return None
