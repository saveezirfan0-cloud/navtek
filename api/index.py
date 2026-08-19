"""HTTP surface for the eOrder service.

Four things live here:

  POST /eorder        monday webhook — the automation
  POST /parse         xlsx in, JSON out. No monday, no database. This is how you
                      test the parser against a file without touching the board,
                      and what Make calls if the flow is ever driven from there.
  GET  /portal/jobs   the installer portal's job list
  POST /portal/action contacted / booked / progress / completed / blocked
  GET  /health        config check — which secrets and column IDs are missing

The portal routes exist now because brief §3.1 says to create the Contacted /
Booked / Scheduled columns up front, and §9 says the parser service is expected
to become the portal's backend. The monday token never leaves this service.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Body, Cookie, FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402

from _lib import bootstrap, columns as columns_mod, config, notify, portal, sla, users  # noqa: E402
from _lib.ingest import handle_webhook  # noqa: E402
from _lib.monday import Monday, MondayError  # noqa: E402
from _lib.store import Store  # noqa: E402

app = FastAPI(title="Navtek eOrder service", docs_url=None, redoc_url=None)


# A bare "HTTP 500" on the setup page tells whoever is running it nothing at
# all. These put the actual cause in the response body, which is the only place
# they can see it without opening Vercel's logs — but only for the app's own
# server-side calls, which carry the shared secret or setup key. An anonymous
# caller poking the public /api/py/* prefix gets a generic line: raw exception
# strings can carry database messages, API responses and file paths, which is
# reconnaissance handed out for free.
def _caller_is_trusted(request):
    import hmac as _hmac

    secret = request.headers.get("x-portal-secret", "")
    if config.PORTAL_SHARED_SECRET and _hmac.compare_digest(
        secret, config.PORTAL_SHARED_SECRET
    ):
        return True
    key = request.headers.get("x-setup-key", "")
    return bool(SETUP_KEY) and _hmac.compare_digest(key, SETUP_KEY)


@app.exception_handler(MondayError)
async def _monday_error(request, exc):
    if _caller_is_trusted(request):
        return JSONResponse({"detail": f"monday API: {exc}"}, status_code=502)
    return JSONResponse({"detail": "monday API error"}, status_code=502)


@app.exception_handler(Exception)
async def _any_error(request, exc):
    import traceback

    traceback.print_exception(exc)  # the full story, in the Vercel logs
    if _caller_is_trusted(request):
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500
        )
    return JSONResponse(
        {"detail": f"Something went wrong ({type(exc).__name__}). "
                   "The detail is in the server logs."},
        status_code=500,
    )


@app.get("/api/py/health")
def health(fresh: bool = Query(default=False)):
    """What's configured, and where each column ID came from.

    Column IDs are resolved off the board, so this reflects what the automation
    would actually use — not just what the environment supplies. Served from
    the 5-minute column cache: the dashboard and file tester call this on every
    load, and each force-read was a full monday GraphQL round trip on the app's
    most-visited page. ?fresh=1 bypasses the cache when it matters; the setup
    page's own refresh step always does.
    """
    try:
        cols = columns_mod.resolved(Monday(), force=fresh)
        source = "board" if not config.COLUMNS.get("eorder_file") else "COLUMN_IDS"
    except Exception as exc:  # noqa: BLE001
        cols = config.COLUMNS
        source = f"environment only — could not read the board: {exc}"

    return {
        "build": {
            "version": config.APP_VERSION,
            "commit": (os.environ.get("VERCEL_GIT_COMMIT_SHA") or "")[:7] or None,
        },
        "ok": not config.missing_secrets() and not config.CONFIG_WARNINGS,
        "missing_secrets": config.missing_secrets(),
        "config_warnings": config.CONFIG_WARNINGS,
        "database": Store().ping(),
        "unmapped_columns": columns_mod.unmapped(cols),
        "unmapped_optional": columns_mod.unmapped_optional(cols),
        "column_ids": cols,
        "column_ids_from": source,
        "orders_board": config.ORDERS_BOARD_ID,
        "installers_board": config.INSTALLERS_BOARD_ID,
        "write_order_type": config.WRITE_ORDER_TYPE,
        "allow_duplicate_files": config.ALLOW_DUPLICATE_FILES,
        "sla": {
            "go_live_date": (config.sla_go_live() or None)
            and config.sla_go_live().isoformat(),
            "go_live_raw": config.SLA_GO_LIVE_DATE or None,
            "business_days": config.SLA_BUSINESS_DAYS,
            "notifications_enabled": config.SLA_NOTIFICATIONS_ENABLED,
            "mode": (
                "off — SLA_GO_LIVE_DATE not set" if not config.sla_go_live()
                else ("live" if config.SLA_NOTIFICATIONS_ENABLED
                      else "shadow — logging only")
            ),
        },
    }


# --------------------------------------------------------------------------
# The automation
# --------------------------------------------------------------------------

@app.post("/api/py/eorder")
async def eorder(request: Request):
    # When WEBHOOK_SECRET is set, the registered URL carries it as ?hook=… and
    # anything without it is turned away — this endpoint is reachable from the
    # open internet and drives writes with the account-wide monday token.
    if config.WEBHOOK_SECRET:
        import hmac as _hmac

        if not _hmac.compare_digest(
            request.query_params.get("hook", ""), config.WEBHOOK_SECRET
        ):
            raise HTTPException(401, "bad webhook token")

    payload = await request.json()

    # monday's webhook handshake: echo the challenge on registration.
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    result = handle_webhook(payload)
    # Always 200, even when the ingest failed.
    #
    # monday retries any delivery that does not get a 2xx, and each retry of a
    # failing file re-ran the failure path and posted another ❌ Update — one
    # bad drop produced a notification storm. The failure is already reported
    # on the row itself, which is where the person who dropped the file is
    # looking; a retry cannot fix a bad file, only repeat the report. The body
    # still carries ok: false for anything reading the response directly.
    return JSONResponse(result, status_code=200)


@app.post("/api/py/parse")
async def parse_endpoint(request: Request):
    """Raw xlsx body in, parsed dict out. Deliberately dependency-free."""
    import io

    from _lib.eorder_parser import parse

    blob = await request.body()
    if not blob:
        raise HTTPException(400, "empty body — POST the .xlsx bytes")
    try:
        return parse(io.BytesIO(blob))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------
# Installer-flow webhooks and crons
# --------------------------------------------------------------------------

def _webhook_guard(request):
    """Same ?hook= check as /eorder — these endpoints are public and drive
    monday writes, so with WEBHOOK_SECRET set nothing without it gets in."""
    if config.WEBHOOK_SECRET:
        import hmac as _hmac

        if not _hmac.compare_digest(
            request.query_params.get("hook", ""), config.WEBHOOK_SECRET
        ):
            raise HTTPException(401, "bad webhook token")


@app.post("/api/py/installer-change")
async def installer_change(request: Request):
    """monday webhook on the Installer column — reallocation (prompt 4)."""
    _webhook_guard(request)
    payload = await request.json()
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}
    try:
        result = notify.handle_installer_change(Monday(), Store(), payload)
    except Exception as exc:  # noqa: BLE001 - 200 always, monday must not retry-storm
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return JSONResponse(result, status_code=200)


@app.post("/api/py/portal/refresh")
async def portal_refresh(request: Request):
    """monday webhook on the dispatch date / status columns (prompt 5).

    A direct edit in monday refreshes the cached job, and — because a dispatch
    date arriving is one half of the SMS rule — re-evaluates the allocation
    trigger. Both halves are idempotent, so duplicate deliveries are free.
    """
    _webhook_guard(request)
    payload = await request.json()
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}
    item_id = (payload.get("event") or {}).get("pulseId")
    if not item_id:
        return JSONResponse({"ok": False, "reason": "no pulseId"}, status_code=200)
    monday, store = Monday(), Store()
    try:
        result = portal.refresh_item(monday, store, item_id)
        result["notify"] = notify.evaluate(monday, store, item_id)
    except Exception as exc:  # noqa: BLE001 - 200 always
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return JSONResponse(result, status_code=200)


def _cron_authorise(x_portal_secret, authorization):
    """The sweep and resync accept the portal secret (header) or Vercel's
    cron identity (Authorization: Bearer CRON_SECRET) — a cron cannot send
    custom headers. Fails CLOSED like _authorise: no secrets configured means
    these routes are disabled, not open."""
    import hmac as _hmac

    if config.PORTAL_SHARED_SECRET and _hmac.compare_digest(
        x_portal_secret or "", config.PORTAL_SHARED_SECRET
    ):
        return
    if config.CRON_SECRET and _hmac.compare_digest(
        authorization or "", f"Bearer {config.CRON_SECRET}"
    ):
        return
    if not config.PORTAL_SHARED_SECRET and not config.CRON_SECRET:
        raise HTTPException(
            503,
            "Neither PORTAL_SHARED_SECRET nor CRON_SECRET is set, so this "
            "route is disabled. Add one in the Vercel project settings and "
            "redeploy.",
        )
    raise HTTPException(401, "bad secret")


@app.post("/api/py/sla/sweep")
@app.get("/api/py/sla/sweep")
def sla_sweep(
    x_portal_secret: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """The daily SLA pass. Refuses to run without SLA_GO_LIVE_DATE; sends
    nothing while SLA_NOTIFICATIONS_ENABLED is false (shadow mode)."""
    _cron_authorise(x_portal_secret, authorization)
    return sla.sweep(Monday(), Store())


@app.post("/api/py/portal/resync")
@app.get("/api/py/portal/resync")
def portal_resync(
    x_portal_secret: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """Hourly cache rebuild — belt and braces behind the live-read-first
    portal (prompt 5)."""
    _cron_authorise(x_portal_secret, authorization)
    return portal.resync(Monday(), Store())


# --------------------------------------------------------------------------
# Portal backend
# --------------------------------------------------------------------------

def _authorise(secret):
    """Only the portal may call these. The browser holds the magic-link token;
    the portal server holds this shared secret and adds it server-side.

    Fails CLOSED: with no PORTAL_SHARED_SECRET configured these routes used to
    wave everyone through — a deployment that skipped one env var silently ran
    its auth, portal and user-management endpoints open at the network edge,
    while /health said ok. Missing secret now means nobody gets in, and
    missing_secrets() names it. Constant-time compare, like the password path.
    """
    import hmac as _hmac

    if not config.PORTAL_SHARED_SECRET:
        raise HTTPException(
            503,
            "PORTAL_SHARED_SECRET is not set, so this route is disabled. "
            "Add it in the Vercel project settings and redeploy.",
        )
    if not _hmac.compare_digest(secret or "", config.PORTAL_SHARED_SECRET):
        raise HTTPException(401, "bad portal secret")


@app.get("/api/py/portal/jobs")
def portal_jobs(
    token: str = Query(...),
    x_portal_secret: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    account = store.account_by_token(token)
    if not account:
        raise HTTPException(404, "unknown or inactive link")
    return portal.jobs_for_account(Monday(), store, account)


@app.post("/api/py/portal/action")
def portal_action(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    account = store.account_by_token(body.get("token", ""))
    if not account:
        raise HTTPException(404, "unknown or inactive link")
    try:
        return portal.apply_action(
            Monday(), store, account,
            item_id=body["item_id"],
            action=body["action"],
            value=body.get("value"),
            note=body.get("note"),
        )
    except KeyError as exc:
        raise HTTPException(400, f"missing field: {exc}") from exc


@app.get("/api/py/portal/vehicle-list")
def vehicle_list(
    token: str = Query(...),
    item_id: str = Query(...),
    x_portal_secret: str = Header(default=""),
):
    """A fresh asset URL, every time.

    monday's public_url expires after an hour, so this is never cached and never
    embedded in a rendered page — the installer taps, we mint, they download
    (§6.3).
    """
    _authorise(x_portal_secret)
    store = Store()
    if not store.account_by_token(token):
        raise HTTPException(404, "unknown or inactive link")
    column_id = config.COLUMNS.get("vehicle_list")
    if not column_id:
        raise HTTPException(503, "Vehicle List column is not configured yet")
    assets = Monday().asset_urls(item_id, column_id)
    if not assets:
        raise HTTPException(404, "no vehicle list attached to this job")
    return {"name": assets[-1]["name"], "url": assets[-1]["public_url"], "expires_in": 3600}


# --------------------------------------------------------------------------
# Logins
#
# The web app's authentication. Only the Next.js server may call these — it
# holds the portal shared secret. The browser holds an opaque session token in
# an httpOnly cookie; what that token means is decided here, against the
# database, never by anything the browser claims about itself.
# --------------------------------------------------------------------------

def _db_or_503(store):
    if not store.enabled:
        raise HTTPException(
            503,
            "The database isn't connected. Logins need SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY set in Vercel.",
        )


def _session_user(store, token):
    """The user behind a session token, or 401. Vague on purpose — an invalid
    session and an expired one look identical from outside."""
    user = store.session_user(users.token_sha(token))
    if not user:
        raise HTTPException(401, "signed out")
    return user


def _require_admin(user):
    if not user.get("is_admin"):
        raise HTTPException(403, "Only an admin can do that.")


@app.get("/api/py/auth/state")
def auth_state(x_portal_secret: str = Header(default="")):
    """Does the app have any users yet? Drives the first-run screen."""
    _authorise(x_portal_secret)
    store = Store()
    return {
        "database": store.ping(),
        "users_exist": store.users_exist(),
    }


@app.post("/api/py/auth/bootstrap")
def auth_bootstrap(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_setup_key: str = Header(default=""),
):
    """Create the first admin. Locked to the SETUP_KEY, and only while the
    users table is empty — after that this endpoint does nothing, ever."""
    _authorise(x_portal_secret)
    _setup_guard(x_setup_key)
    store = Store()
    _db_or_503(store)
    if store.users_exist() is not False:
        raise HTTPException(
            409,
            "An admin already exists (or the users table is unreadable — run "
            "supabase/migrations/0002_users.sql). Sign in instead.",
        )
    email = users.normalise_email(body.get("email", ""))
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""
    if not email or "@" not in email or not name:
        raise HTTPException(400, "A name and a valid email are needed.")
    problem = users.password_problem(password)
    if problem:
        raise HTTPException(400, problem)
    row = store.create_user({
        "email": email,
        "name": name,
        "password_hash": users.hash_password(password),
        "is_admin": True,
        "can_orders": True,
        "can_installer": False,
        "active": True,
    })
    if not row:
        raise HTTPException(
            503,
            f"Could not create the user — {store.degraded or 'database write failed'}. "
            "Has supabase/migrations/0002_users.sql been run?",
        )
    return _issue_session(store, row, body.get("user_agent"))


def _issue_session(store, user_row, user_agent):
    token = users.new_session_token()
    session = store.create_session(
        user_row["id"], users.token_sha(token), users.session_expiry(), user_agent
    )
    if not session:
        raise HTTPException(
            503, f"Could not start a session — {store.degraded or 'database write failed'}."
        )
    from datetime import datetime, timezone
    store.update_user(
        user_row["id"], {"last_login_at": datetime.now(timezone.utc).isoformat()}
    )
    return {"token": token, "user": users.public_user(user_row)}


@app.post("/api/py/auth/login")
def auth_login(body: dict = Body(...), x_portal_secret: str = Header(default="")):
    _authorise(x_portal_secret)
    store = Store()
    _db_or_503(store)
    email = users.normalise_email(body.get("email", ""))
    password = body.get("password") or ""
    # Brute force is cheap against a function that scales on demand. Eight
    # failures in fifteen minutes parks the email — recorded in portal_events,
    # so it holds across serverless instances, and fails open if the database
    # is down (throttling must never become the outage).
    if email and store.recent_failed_logins(email, minutes=15) >= 8:
        raise HTTPException(
            429,
            "Too many failed sign-ins for this email. Wait 15 minutes and try "
            "again.",
        )
    row = store.user_by_email(email) if email else None
    # A lookup that failed because the database misbehaved must not be
    # reported as a wrong password — that sends someone resetting credentials
    # that were never the problem.
    if row is None and store.degraded:
        raise HTTPException(
            503, f"Could not check the login — {store.degraded}. Try again shortly."
        )
    # Verify against a real hash even when the user is unknown, so the two
    # failures take the same time and the response can stay identical.
    stored = row["password_hash"] if row else users.hash_password("timing-decoy")
    ok = users.verify_password(password, stored)
    if not row or not ok or not row.get("active"):
        if email:
            store.record_failed_login(email)
        raise HTTPException(401, "That email or password isn't right.")
    return _issue_session(store, row, body.get("user_agent"))


@app.post("/api/py/auth/logout")
def auth_logout(body: dict = Body(default={}), x_portal_secret: str = Header(default="")):
    _authorise(x_portal_secret)
    Store().delete_session(users.token_sha((body or {}).get("token", "")))
    return {"ok": True}


@app.get("/api/py/auth/me")
def auth_me(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    return {"user": users.public_user(_session_user(Store(), x_session))}


# -- user management (admin only) ------------------------------------------

@app.get("/api/py/users")
def users_list(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    accounts = [
        {"id": a["id"], "name": a["account_name"], "active": a.get("active")}
        for a in store.installer_accounts(active_only=False)
    ]
    return {
        "users": [users.public_user(u) for u in store.list_users()],
        "installer_accounts": accounts,
    }


@app.post("/api/py/users")
def users_create(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))

    email = users.normalise_email(body.get("email", ""))
    name = (body.get("name") or "").strip()
    if not email or "@" not in email or not name:
        raise HTTPException(400, "A name and a valid email are needed.")
    if store.user_by_email(email):
        raise HTTPException(409, "A user with that email already exists.")
    problem = users.password_problem(body.get("password") or "")
    if problem:
        raise HTTPException(400, problem)

    row = store.create_user({
        "email": email,
        "name": name,
        "password_hash": users.hash_password(body["password"]),
        "is_admin": bool(body.get("is_admin")),
        "can_orders": bool(body.get("can_orders")),
        "can_installer": bool(body.get("can_installer")),
        "installer_account_id": body.get("installer_account_id") or None,
        "active": True,
    })
    if not row:
        raise HTTPException(
            503, f"Could not create the user — {store.degraded or 'database write failed'}."
        )
    return {"user": users.public_user(row)}


@app.post("/api/py/users/update")
def users_update(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)
    _require_admin(me)

    user_id = body.get("id")
    target = store.user_by_id(user_id) if user_id else None
    if not target:
        raise HTTPException(404, "No such user.")

    fields = {}
    for flag in ("is_admin", "can_orders", "can_installer", "active"):
        if flag in body:
            fields[flag] = bool(body[flag])
    if "installer_account_id" in body:
        fields["installer_account_id"] = body["installer_account_id"] or None
    if "name" in body and (body["name"] or "").strip():
        fields["name"] = body["name"].strip()
    if body.get("password"):
        problem = users.password_problem(body["password"])
        if problem:
            raise HTTPException(400, problem)
        fields["password_hash"] = users.hash_password(body["password"])

    # The one non-obvious rule: you cannot lock yourself out. Removing your own
    # admin or deactivating yourself leaves an app nobody can administer.
    if target["id"] == me["id"] and (
        fields.get("is_admin") is False or fields.get("active") is False
    ):
        raise HTTPException(400, "You can't remove your own admin access or deactivate yourself.")

    if not fields:
        raise HTTPException(400, "Nothing to change.")
    row = store.update_user(user_id, fields)
    if not row:
        raise HTTPException(
            503, f"Could not save — {store.degraded or 'database write failed'}."
        )
    # Deactivating someone signs them out everywhere, immediately. A password
    # change does the same — the person changing it is about to sign back in.
    if fields.get("active") is False or "password_hash" in fields:
        store.delete_user_sessions(user_id)
    return {"user": users.public_user(row)}


# -- previewing a user (admin) ------------------------------------------------

@app.get("/api/py/users/preview")
def user_preview(
    user_id: str = Query(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """What a given login would see — admin only.

    Returns the same shape as /auth/me so the web half can render the app
    through that user's eyes. Deliberately NOT a session for the target: no
    token is minted, nothing is impersonated — the admin's own session
    authorises every request, and writes stay the admin's writes.
    """
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    target = store.user_by_id(user_id)
    if not target:
        raise HTTPException(404, "No such user.")
    return {"user": users.public_user(target)}


@app.get("/api/py/portal/preview-jobs")
def portal_preview_jobs(
    user_id: str = Query(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """The job list a given installer login would see — admin only, read only.

    The 'viewed' audit event answers "did the installer actually look", so a
    preview must not forge one (record_view=False).
    """
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    target = store.user_by_id(user_id)
    if not target:
        raise HTTPException(404, "No such user.")
    account = store.account_by_id(target.get("installer_account_id"))
    if not account:
        raise HTTPException(
            409, "That login isn't linked to an installer account yet."
        )
    return portal.jobs_for_account(Monday(), store, account, record_view=False)


# -- the portal, for logged-in installer users ------------------------------

def _installer_account(store, user):
    if not (user.get("is_admin") or user.get("can_installer")):
        raise HTTPException(403, "This login doesn't have installer access.")
    account = store.account_by_id(user.get("installer_account_id"))
    if not account:
        raise HTTPException(
            409,
            "This login isn't linked to an installer account yet. Ask Navtek "
            "to link one on the Users page.",
        )
    return account


@app.get("/api/py/portal/my-jobs")
def portal_my_jobs(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    user = _session_user(store, x_session)
    account = _installer_account(store, user)
    return portal.jobs_for_account(Monday(), store, account)


@app.post("/api/py/portal/my-action")
def portal_my_action(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    user = _session_user(store, x_session)
    account = _installer_account(store, user)
    try:
        return portal.apply_action(
            Monday(), store, account,
            item_id=body["item_id"],
            action=body["action"],
            value=body.get("value"),
            note=body.get("note"),
        )
    except KeyError as exc:
        raise HTTPException(400, f"missing field: {exc}") from exc


# --------------------------------------------------------------------------
# Setup and dashboard
#
# These back the /setup and / pages. Guarded by SETUP_KEY, sent as a header by
# the page — they create columns on a live board and reveal column IDs.
# --------------------------------------------------------------------------

SETUP_KEY = os.environ.get("SETUP_KEY", "")


def _setup_guard(key):
    if not SETUP_KEY:
        raise HTTPException(
            503,
            "SETUP_KEY is not set. Add it in the Vercel project settings, "
            "redeploy, then reload this page.",
        )
    import hmac as _hmac

    if not _hmac.compare_digest(key or "", SETUP_KEY):
        raise HTTPException(401, "That setup key doesn't match.")


@app.get("/api/py/setup/plan")
def setup_plan(x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    return {"board": config.ORDERS_BOARD_ID, "columns": bootstrap.plan_columns(Monday())}


@app.post("/api/py/setup/columns")
def setup_columns(x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    return bootstrap.create_columns(Monday())


@app.post("/api/py/setup/installers")
def setup_installers(x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    monday = Monday()
    result = bootstrap.ensure_installer_board(monday)
    link = bootstrap.create_installer_link(monday, result["board_id"])
    result.setdefault("log", []).append(
        f"{'created' if link['created'] else 'exists'}  Installer connect column "
        f"({link['column_id']})"
    )
    result["installer_column_id"] = link["column_id"]
    return result


@app.post("/api/py/setup/refresh")
def setup_refresh(x_setup_key: str = Header(default="")):
    """Drop the cached column map and read the board again."""
    _setup_guard(x_setup_key)
    columns_mod.clear_cache()
    cols = columns_mod.resolved(Monday(), force=True)
    return {"columns": cols, "unmapped": columns_mod.unmapped(cols)}


@app.get("/api/py/setup/env")
def setup_env(x_setup_key: str = Header(default="")):
    """The environment variables to paste into Vercel, with current values."""
    _setup_guard(x_setup_key)
    monday = Monday()
    resolved = {k: v for k, v in config.COLUMNS.items() if v}
    for entry in bootstrap.plan_columns(monday):
        if entry["column_id"]:
            resolved[entry["key"]] = entry["column_id"]

    installers_board = config.INSTALLERS_BOARD_ID or bootstrap.find_installer_board(monday)
    for column in monday.board_columns(config.ORDERS_BOARD_ID):
        if column["type"] == "board_relation" and column["title"].strip().lower() == "installer":
            resolved["installer"] = column["id"]

    lines = [f"COLUMN_IDS={json.dumps(resolved, separators=(',', ':'))}"]
    if installers_board:
        lines.append(f"INSTALLERS_BOARD_ID={installers_board}")

    return {
        "env": lines,
        "env_raw": "\n".join(lines),
        "column_ids": resolved,
        "still_missing": [k for k, v in config.COLUMNS.items() if not resolved.get(k)],
    }


@app.post("/api/py/setup/sync")
def setup_sync(x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    try:
        return bootstrap.sync_installers(Monday(), Store())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/py/setup/webhook")
def setup_webhook(body: dict = Body(default={}), x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    url = (body or {}).get("url", "").strip().rstrip("/")
    if not url.startswith("https://"):
        raise HTTPException(400, "Enter this app's address, starting https://")
    monday = Monday()
    try:
        result = bootstrap.register_webhook(monday, f"{url}/api/py/eorder")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # The installer-flow webhooks (Installer column, dispatch date, status)
    # ride the same step, idempotently. Missing columns are skipped, not fatal
    # — the eOrder webhook is the one this step must not leave unregistered.
    try:
        result["flow_webhooks"] = bootstrap.register_flow_webhooks(monday, url)
    except Exception as exc:  # noqa: BLE001
        result["flow_webhooks"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


@app.get("/api/py/selftest")
def selftest(x_setup_key: str = Header(default="")):
    """Check every part of the order flow and say which are working.

    Deliberately read-only: it touches nothing on the board and writes nothing
    to the database. This is the "is it actually working" answer, in one place,
    rather than five endpoints and a guess.

    Key-guarded: the readout names the token's owner, the webhook IDs and the
    database diagnosis — a map of the deployment, not something to hand to
    whoever finds the URL. The setup page holds the key and keeps working.
    """
    _setup_guard(x_setup_key)
    checks = []

    def check(name, fn, needed=True):
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append({"check": name, "ok": ok, "required": needed, "detail": detail})
        return ok

    monday = Monday()

    def monday_auth():
        who = monday.me()
        return bool(who.get("name")), f"connected as {who.get('name')}" if who else "no response"

    def board_ok():
        name = monday.board_name(config.ORDERS_BOARD_ID)
        return bool(name), f"{name} ({config.ORDERS_BOARD_ID})" if name else "board not found"

    def columns_ok():
        cols = columns_mod.resolved(monday, force=True)
        missing = columns_mod.unmapped(cols)
        optional = columns_mod.unmapped_optional(cols)
        if missing:
            return False, f"missing: {', '.join(missing)} — run step 2"
        note = f", {len(optional)} production-only column(s) absent" if optional else ""
        return True, f"all {len(cols) - len(optional)} mapped{note}"

    def webhook_ok():
        column_id = bootstrap.eorder_column_id(monday)
        if not column_id:
            return False, "no file column called 'eOrder' — run step 2"
        for hook in monday.webhooks(config.ORDERS_BOARD_ID):
            if column_id in str(hook.get("config") or ""):
                return True, f"webhook {hook['id']} on the eOrder column"
        return False, "not registered — run step 4"

    def parser_ok():
        from _lib import eorder_parser
        return (
            bool(getattr(eorder_parser, "ACV_ORDER_REASONS", None)),
            "loaded" if callable(getattr(eorder_parser, "parse", None))
            else "placeholder — upload the real eorder_parser.py",
        )

    def database_ok():
        probe = Store().ping()
        return probe["ok"], probe.get("detail") or probe.get("state")

    check("monday token", monday_auth)
    check("orders board", board_ok)
    check("board columns", columns_ok)
    check("parser", parser_ok)
    check("webhook", webhook_ok)
    check("database", database_ok, needed=False)

    blocking = [c for c in checks if c["required"] and not c["ok"]]
    optional_failed = [c for c in checks if not c["required"] and not c["ok"]]

    if blocking:
        verdict = f"Not working yet — {blocking[0]['check']}: {blocking[0]['detail']}"
    elif optional_failed:
        verdict = ("Orders will be read and written to monday. "
                   f"{optional_failed[0]['check']} is not working, which costs the "
                   "duplicate check and the history, but not the order.")
    else:
        verdict = "Everything is working."

    return {"ok": not blocking, "verdict": verdict, "checks": checks}


@app.get("/api/py/recent")
def recent(limit: int = Query(default=20), x_portal_secret: str = Header(default="")):
    """Recent eOrder reads, for the dashboard. No secrets — but customer names,
    order IDs and file names ARE business data, so only the app's own server
    (which holds the shared secret and sits behind the login) may ask."""
    _authorise(x_portal_secret)
    store = Store()
    if not store.enabled:
        return {"enabled": False, "ingests": [], "database": store.ping()}
    try:
        # Straight to the query — the old ping-first pattern doubled the
        # database round trips on every dashboard load. ping() now runs only
        # to DIAGNOSE a failure (and _send has already tried the fallback
        # credential pair by then).
        rows = store.recent_ingests(min(limit, 50))
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "ingests": [],
                "database": {"ok": False, "state": "error",
                             "detail": f"{type(exc).__name__}: {exc}"}}
    if store.degraded:
        return {"enabled": False, "ingests": [], "database": store.ping()}

    # The webhook log includes what the ingest ledger never sees — duplicate
    # skips and no-file deliveries, which monday's own log shows as Success.
    # An absent table (0004 not run yet) degrades to an empty list plus a flag
    # the dashboard turns into a "run the migration" hint.
    hooks = store.recent_webhooks(min(limit, 50))
    webhook_log_ready = not (store.degraded and "webhook_log" in str(store.degraded))

    return {
        "enabled": True,
        "ingests": [
            {
                "monday_item_id": r.get("monday_item_id"),
                "opportunity_id": r.get("opportunity_id"),
                "file_name": r.get("file_name"),
                "status": r.get("status"),
                "warnings": r.get("warnings") or [],
                "changed_fields": r.get("changed_fields") or [],
                "error": r.get("error"),
                "duration_ms": r.get("duration_ms"),
                "created_at": r.get("created_at"),
                "item_name": (r.get("parsed") or {}).get("derived_item_name"),
            }
            for r in rows
        ],
        "webhook_log_ready": webhook_log_ready,
        "webhooks": [
            {
                "monday_item_id": h.get("monday_item_id"),
                "opportunity_id": h.get("opportunity_id"),
                "file_name": h.get("file_name"),
                "outcome": h.get("outcome"),
                "reason": h.get("reason"),
                "status": h.get("status"),
                "duration_ms": h.get("duration_ms"),
                "created_at": h.get("created_at"),
            }
            for h in hooks
        ],
    }


@app.get("/api/py/eorder/file")
def eorder_file(
    item_id: int = Query(...),
    navtek_session: str = Cookie(default=""),
):
    """Download the eOrder file sitting on a monday row.

    Browser-navigated (a plain link on the dashboard), so it authenticates
    with the session COOKIE directly rather than the X-Session header the
    server-to-server routes use — the httpOnly cookie rides along on any
    same-origin navigation. Orders access required: the raw eOrder carries
    dealer commission and contract value, so this is a STAFF door — never
    link it from the installer portal, whose users must not see commercials.

    monday asset URLs expire after ~1h, so the fresh URL is fetched per click
    and answered as a redirect — nothing is stored (brief §3.2/§6.3).
    """
    store = Store()
    user = _session_user(store, navtek_session)
    if not (user.get("can_orders") or user.get("is_admin")):
        raise HTTPException(403, "This login doesn't have Orders access.")

    monday = Monday()
    cols = columns_mod.resolved(monday)
    file_column = cols.get("eorder_file")
    if not file_column:
        raise HTTPException(404, "No eOrder file column is mapped on the board.")
    assets = monday.asset_urls(item_id, file_column)
    if not assets:
        raise HTTPException(404, "No file on this row's eOrder column.")
    return RedirectResponse(assets[-1]["public_url"])


@app.get("/api/py/installers")
def installer_accounts(x_setup_key: str = Header(default="")):
    """Accounts and their portal links, for the dashboard. Key-guarded — the
    tokens in here are the entirety of the portal's authentication."""
    _setup_guard(x_setup_key)
    store = Store()
    if not store.enabled:
        return {"accounts": []}
    return {
        "accounts": [
            {
                "name": a["account_name"],
                "coordinator": a.get("coordinator_name"),
                "mobile": a.get("coordinator_mobile"),
                "token": a["portal_token"],
                "active": a.get("active"),
            }
            for a in store.installer_accounts(active_only=False)
        ]
    }
