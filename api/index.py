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

from _lib import bootstrap, columns as columns_mod, config, emailer, notify, onboarding, portal, sla, users  # noqa: E402
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
    _store = Store()
    _rejections = _store.recent_rejections()
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
        # Import-time warnings, plus posture the environment decides at run
        # time: with no webhook lock set, anyone who finds the URL can hand the
        # automation a payload — worth a banner, not a silent default.
        #
        # The recommendation is WEBHOOK_SECRET, not MONDAY_SIGNING_SECRET.
        # monday only signs webhooks created through an app's OAuth token, and
        # ours are created with a personal API token, so a signing secret
        # verifies nothing on its own — see config.MONDAY_SIGNING_SECRET.
        "config_warnings": config.CONFIG_WARNINGS + (
            [] if config.WEBHOOK_SECRET else
            ["The webhook endpoints accept unauthenticated calls. Set "
             "WEBHOOK_SECRET to a long random string and re-run setup step 4 "
             "so the registered URL carries it."]
        ) + (
            [f"{len(_rejections)} webhook delivery(ies) were turned away in the "
             f"last 48 hours: {_rejections[0].get('reason')}. Nothing lands on "
             f"the monday row for a rejected delivery. If WEBHOOK_SECRET was "
             f"changed, the registered URL still carries the old ?hook= token "
             f"— re-run setup step 4 with Re-register."]
            if _rejections else []
        ) + (
            ["MONDAY_SIGNING_SECRET is set, but monday only signs webhooks "
             "created through an app's OAuth token. If these were registered "
             "with a personal API token they arrive unsigned and this secret "
             "verifies nothing — WEBHOOK_SECRET is the lock doing the work."]
            if config.MONDAY_SIGNING_SECRET and not config.MONDAY_SIGNING_REQUIRED
            else []
        ),
        "database": _store.ping(),
        # Deliveries monday made that this app turned away. Nothing lands on
        # the row for these — the rejection happens before there is an item to
        # stamp — so without surfacing them here a stale ?hook= token looks
        # exactly like an automation nobody triggered.
        "rejected_deliveries": _rejections,
        "unmapped_columns": columns_mod.unmapped(cols),
        "unmapped_optional": columns_mod.unmapped_optional(cols),
        "column_ids": cols,
        "column_ids_from": source,
        "orders_board": config.ORDERS_BOARD_ID,
        "installers_board": config.INSTALLERS_BOARD_ID,
        "write_order_type": config.WRITE_ORDER_TYPE,
        "allow_duplicate_files": config.ALLOW_DUPLICATE_FILES,
        "monday_slug": config.MONDAY_ACCOUNT_SLUG or None,
        "log_retention_days": config.LOG_RETENTION_DAYS,
        "webhook_hardening": {
            "hook_token": bool(config.WEBHOOK_SECRET),
            "signature": bool(config.MONDAY_SIGNING_SECRET),
            "signature_required": bool(config.MONDAY_SIGNING_REQUIRED),
        },
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

def _monday_signature_ok(authorization):
    """Verify monday's webhook signature — an HS256 JWT in Authorization.

    Hand-rolled HMAC over header.payload rather than a JWT library: the only
    claim that matters is "monday's signing secret produced this", and a
    dependency-free check keeps the serverless bundle where store.py's
    reasoning already put it. Claims (exp and friends) are deliberately not
    read — monday's tokens are per-delivery and short-lived, and rejecting a
    clock-skewed but genuinely signed delivery would drop real orders.
    """
    import base64
    import hashlib
    import hmac as _hmac

    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    expected = _hmac.new(config.MONDAY_SIGNING_SECRET.encode(),
                         f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    try:
        got = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
    except Exception:  # noqa: BLE001 - malformed padding is just "no"
        return False
    return _hmac.compare_digest(expected, got)


def _webhook_rejection(request, payload):
    """Why this delivery must not be acted on, or None to carry on.

    Two independent locks, and neither may ever answer monday with a 4xx —
    see _accept_webhook for why.

    * WEBHOOK_SECRET — the registered URL carries it as ?hook=…. Our own
      registration always attaches it (bootstrap.register_flow_webhooks), so a
      mismatch means a hand-registered URL, a rotated secret nobody re-ran
      setup step 4 for, or someone who guessed the path.
    * MONDAY_SIGNING_SECRET — verifies the HS256 JWT monday puts in
      Authorization. monday only signs webhooks created through an app's OAuth
      token; one created with a personal API token (what bootstrap does)
      arrives with no Authorization header at all. So an *absent* signature is
      normal and is allowed through, and only a signature that is present and
      wrong is a rejection — unless MONDAY_SIGNING_REQUIRED says the webhooks
      really are OAuth-registered, in which case unsigned is a rejection too.

    With no WEBHOOK_SECRET the endpoints run open, which /health reports as a
    warning rather than silently accepting.
    """
    import hmac as _hmac

    if config.WEBHOOK_SECRET and not _hmac.compare_digest(
        request.query_params.get("hook", ""), config.WEBHOOK_SECRET
    ):
        return "?hook= token does not match WEBHOOK_SECRET"

    if not config.MONDAY_SIGNING_SECRET:
        return None

    # The registration handshake is never gated on a signature. monday replays
    # it to re-verify a live webhook, and a webhook registered with a personal
    # token has nothing to sign it — refusing the handshake is precisely how
    # the automation gets deactivated.
    if "challenge" in payload:
        return None

    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        if config.MONDAY_SIGNING_REQUIRED:
            return ("unsigned delivery while MONDAY_SIGNING_REQUIRED is set — "
                    "is this webhook registered through an app's OAuth token?")
        return None
    if not _monday_signature_ok(authorization):
        return "Authorization JWT does not verify against MONDAY_SIGNING_SECRET"
    return None


def _log_rejection(payload, reason):
    """A dropped delivery is invisible unless something records it.

    Answering 200 is what stops monday deactivating the automation, but it also
    means monday's own log can no longer be where a rejection shows up — so it
    shows up here, on /deliveries. Swallowed like every other ledger write: the
    log must never cost a request.
    """
    event = payload.get("event") or {}
    try:
        Store().record_webhook(
            monday_item_id=event.get("pulseId"),
            monday_board_id=event.get("boardId"),
            outcome="rejected",
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - the log must never cost the request
        pass


async def _accept_webhook(request):
    """Read one monday delivery and decide whether to act on it.

    Returns (payload, None) to go ahead, or (None, response) to send `response`
    and stop — the registration handshake's echo, or a drop.

    A rejected delivery is dropped with 200, never a 4xx. monday deactivates a
    webhook automation whose endpoint answers with an authentication error, and
    that deactivation is silent until an email turns up days later. A secret
    that doesn't match has to cost us one delivery, not the integration —
    the same reasoning that already makes a failed ingest return 200.
    """
    # A body we cannot read is still answered 200. An unparseable or non-object
    # payload would otherwise reach handle_webhook's payload.get and 500 — and
    # a 500 is a non-2xx like any other, which is the thing we are avoiding.
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - a body we cannot read is not a delivery
        return None, JSONResponse({"ok": False, "reason": "body is not JSON"},
                                  status_code=200)
    if not isinstance(payload, dict):
        return None, JSONResponse(
            {"ok": False, "reason": "webhook payload is not a JSON object"},
            status_code=200)

    reason = _webhook_rejection(request, payload)
    if reason:
        _log_rejection(payload, reason)
        return None, JSONResponse({"ok": False, "rejected": reason},
                                  status_code=200)

    # monday's webhook handshake: echo the challenge on registration.
    if "challenge" in payload:
        return None, JSONResponse({"challenge": payload["challenge"]},
                                  status_code=200)

    return payload, None


@app.post("/api/py/eorder")
async def eorder(request: Request):
    payload, early = await _accept_webhook(request)
    if early is not None:
        return early

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

@app.post("/api/py/installer-change")
async def installer_change(request: Request):
    """monday webhook on the Installer column — reallocation (prompt 4)."""
    payload, early = await _accept_webhook(request)
    if early is not None:
        return early
    try:
        result = notify.handle_installer_change(Monday(), Store(), payload)
    except Exception as exc:  # noqa: BLE001 - 200 always, monday must not retry-storm
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return JSONResponse(result, status_code=200)


@app.post("/api/py/installer-account-change")
async def installer_account_change(request: Request):
    """monday webhook on the Installer Accounts board — auto-onboarding.

    Adding or editing a row does what Setup steps A and B plus a copy-paste
    used to: the row gets a portal token and its Active tick, the board is
    re-synced into the database, and the coordinator is emailed their magic
    link. Every step is idempotent, so monday's retries — and the delivery
    our own token write triggers — are free.
    """
    payload, early = await _accept_webhook(request)
    if early is not None:
        return early
    try:
        result = onboarding.handle_account_event(Monday(), Store(), payload)
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
    payload, early = await _accept_webhook(request)
    if early is not None:
        return early
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
    nothing while SLA_NOTIFICATIONS_ENABLED is false (shadow mode). The
    retention purge rides the same daily schedule — and runs even when the
    sweep itself refuses, so an unconfigured SLA engine doesn't also mean
    logs that grow forever."""
    _cron_authorise(x_portal_secret, authorization)
    result = sla.sweep(Monday(), Store())
    result["retention"] = Store().purge_logs(config.LOG_RETENTION_DAYS)
    # The daily digest rides the same schedule. Independent of the SLA
    # engine's own guards — a workspace with the SLA off still wants to hear
    # how yesterday's orders went. Decides (and dedupes) for itself.
    result["digest"] = emailer.send_daily_digest(Store())
    return result


@app.get("/api/py/sla/preview")
def sla_preview(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """The SLA console's one call — read-only, admin only.

    What the engine sees right now: every job inside its window with its
    clock and countdown, plus the recent ledger. Writes nothing — no claims,
    no events — so the console can refresh freely without consuming the
    dedup keys the real sweep depends on.
    """
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    result = sla.preview(Monday(), Store())
    result["ledger"] = store.recent_notifications(30)
    return result


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
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


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
    account = store.account_by_token(token)
    if not account:
        raise HTTPException(404, "unknown or inactive link")
    monday = Monday()
    # Same ownership rule as the write-backs: item_id is client input, and a
    # minted asset URL is a data leak if the job belongs to another account.
    try:
        portal.require_ownership(monday, store, account, item_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    column_id = config.COLUMNS.get("vehicle_list")
    if not column_id:
        raise HTTPException(503, "Vehicle List column is not configured yet")
    assets = monday.asset_urls(item_id, column_id)
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


# -- your own account (any signed-in user) ----------------------------------
#
# Self-service that used to need an admin: your display name, your password,
# and the "I left myself signed in somewhere" button. Deliberately narrower
# than /users/update — access flags and active status stay admin-only.

@app.post("/api/py/auth/profile")
def auth_update_profile(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Enter a name.")
    row = store.update_user(me["id"], {"name": name[:120]})
    if not row:
        raise HTTPException(
            503, f"Could not save — {store.degraded or 'database write failed'}."
        )
    return {"user": users.public_user(row)}


@app.post("/api/py/auth/change-password")
def auth_change_password(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """A signed-in user changes their own password. The current password is
    required — a session alone (an unlocked laptop) must not be enough to
    take the account over. Wrong guesses count against the same throttle as
    the login form, so this route is no softer a brute-force target than
    /auth/login. On success every OTHER session is signed out; the browser
    that made the change stays in."""
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)

    email = users.normalise_email(me.get("email", ""))
    if store.recent_failed_logins(email, minutes=15) >= 8:
        raise HTTPException(
            429, "Too many wrong passwords. Wait 15 minutes and try again.",
        )
    if not users.verify_password(
        body.get("current_password") or "", me.get("password_hash") or ""
    ):
        store.record_failed_login(email)
        raise HTTPException(400, "Your current password isn't right.")

    new_password = body.get("new_password") or ""
    problem = users.password_problem(new_password)
    if problem:
        raise HTTPException(400, problem)
    if new_password == (body.get("current_password") or ""):
        raise HTTPException(400, "The new password is the same as the current one.")

    row = store.update_user(
        me["id"], {"password_hash": users.hash_password(new_password)}
    )
    if not row:
        raise HTTPException(
            503, f"Could not save — {store.degraded or 'database write failed'}."
        )
    store.delete_other_user_sessions(me["id"], users.token_sha(x_session))
    return {"ok": True}


@app.post("/api/py/auth/logout-all")
def auth_logout_all(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """Sign out everywhere — every session including this one. The web half
    clears its cookie and lands the person back on /login."""
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)
    store.delete_user_sessions(me["id"])
    return {"ok": True}


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


# -- workspace settings (admin) -----------------------------------------------
#
# Non-secret, admin-editable values behind /settings — today, who hears about
# ⚠️ Check and ❌ Failed reads by email. Secrets stay environment variables.

@app.get("/api/py/settings")
def settings_get(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    return {
        "notifications": emailer.notification_settings(store),
        "email": {
            "provider": emailer.provider(),
            "from": emailer.sender_address() or None,
        },
    }


@app.post("/api/py/settings")
def settings_save(
    body: dict = Body(...),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)
    _require_admin(me)
    _db_or_503(store)

    incoming = body.get("notifications")
    if not isinstance(incoming, dict):
        raise HTTPException(400, "Nothing to save.")
    value = {
        "emails": emailer.clean_emails(incoming.get("emails")),
        "notify_check": bool(incoming.get("notify_check", True)),
        "notify_failed": bool(incoming.get("notify_failed", True)),
        "daily_digest": bool(incoming.get("daily_digest", False)),
    }
    saved = store.save_setting(emailer.SETTINGS_KEY, value, updated_by=me.get("email"))
    if not saved:
        raise HTTPException(
            503,
            f"Could not save — {store.degraded or 'database write failed'}. "
            "If the app_settings table is missing, run "
            "supabase/migrations/0007_app_settings.sql.",
        )
    store.record_event(0, "settings_changed",
                       payload={"key": emailer.SETTINGS_KEY, "by": me.get("email")})
    return {"notifications": emailer.notification_settings(store)}


@app.post("/api/py/settings/test-email")
def settings_test_email(
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """Send a test to the saved recipients, so "will this reach us" is a
    button, not a production incident. Reports the provider's answer."""
    _authorise(x_portal_secret)
    store = Store()
    me = _session_user(store, x_session)
    _require_admin(me)
    settings = emailer.notification_settings(store)
    if not settings["emails"]:
        raise HTTPException(400, "Add at least one notification email first.")
    result = emailer.send_email(
        settings["emails"],
        "Test — Navtek eOrder notifications",
        "<p>This is a test from the Navtek eOrder dashboard. "
        "Alerts about ⚠️ Check and ❌ Failed reads will arrive like this.</p>"
        f"<p style='color:#5b6875;font-size:13px'>Requested by {me.get('email')}.</p>",
        "This is a test from the Navtek eOrder dashboard.",
    )
    return {"sent": bool(result.get("ok")), "to": settings["emails"], **result}


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
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


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
    monday = Monday()
    result = bootstrap.create_columns(monday)
    # The install-item (subitem) field set rides along: multi-site orders
    # would create it on first use anyway, but preparing it here lets the
    # columns be checked before a live multi-site order arrives.
    subitems = bootstrap.prepare_subitem_columns(monday)
    result["log"].extend(subitems["log"])
    result["subitem_columns_prepared"] = subitems["prepared"]
    return result


@app.post("/api/py/setup/installers")
def setup_installers(x_setup_key: str = Header(default="")):
    _setup_guard(x_setup_key)
    monday = Monday()
    result = bootstrap.ensure_installer_board(monday)
    link = bootstrap.create_installer_link(monday, result["board_id"])
    if link.get("error"):
        result.setdefault("log", []).append(
            f"failed   Installer connect column — {link['error']}. Add a "
            "Connect boards column titled 'Installer' (linked to the "
            "Installer Accounts board) by hand, then re-run this step."
        )
    else:
        result.setdefault("log", []).append(
            f"{'created' if link['created'] else 'exists'}  Installer connect "
            f"column ({link['column_id']})"
        )
    result["installer_column_id"] = link["column_id"]

    # Auto-onboarding: register the board's own webhooks here too, so step A
    # alone switches it on — the app knows its own address, and waiting for
    # step 4 to be re-run is exactly the kind of extra step this removes.
    base = config.portal_base_url()
    if base:
        try:
            result["onboarding_webhooks"] = bootstrap.register_installer_webhooks(
                monday, base, result["board_id"])
            result.setdefault("log", []).append(
                "ready    auto-onboarding — a row added or edited on this "
                "board now issues its token, syncs itself and emails the "
                "coordinator their link")
        except Exception as exc:  # noqa: BLE001
            result.setdefault("log", []).append(
                f"failed   auto-onboarding webhooks — {exc}. Run step 4 "
                "again to register them.")
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
    # force=true replaces existing registrations rather than reporting them as
    # already done. This is the repair for a rotated WEBHOOK_SECRET: the ?hook=
    # token is baked into the registered URL, monday cannot change a webhook's
    # URL or even report it back, and until this existed a re-run of this step
    # said "already registered" while every delivery was being turned away.
    force = bool((body or {}).get("force"))
    monday = Monday()
    try:
        result = bootstrap.register_webhook(monday, f"{url}/api/py/eorder",
                                            force=force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # The installer-flow webhooks (Installer column, dispatch date, status)
    # ride the same step, idempotently. Missing columns are skipped, not fatal
    # — the eOrder webhook is the one this step must not leave unregistered.
    try:
        result["flow_webhooks"] = bootstrap.register_flow_webhooks(
            monday, url, force=force)
    except Exception as exc:  # noqa: BLE001
        result["flow_webhooks"] = {"error": f"{type(exc).__name__}: {exc}"}
    result["forced"] = force
    return result


@app.get("/api/py/activity")
def activity(
    events_offset: int = Query(default=0),
    notifications_offset: int = Query(default=0),
    reasons_offset: int = Query(default=0),
    x_portal_secret: str = Header(default=""),
    x_session: str = Header(default=""),
):
    """The audit trail, for admins: one merged timeline — portal events
    (views, write-backs, failed logins, SLA breaches), webhook deliveries and
    file reads — plus the notification ledger and unrecognised order reasons.

    Each section pages independently. The timeline merges three tables that
    PostgREST cannot UNION, so a page is a window: the next 50 of EACH source
    at that offset, interleaved newest-first. Rows within a source are never
    skipped; totals drive the pager off the deepest source.
    """
    _authorise(x_portal_secret)
    store = Store()
    _require_admin(_session_user(store, x_session))
    page = 50
    offset = max(0, events_offset)

    def took(ms):
        return f"{ms / 1000:.1f}s" if ms else None

    events, events_total = store.events_page(page, offset)
    feed = [
        {
            "action": e.get("action"),
            "monday_item_id": e.get("monday_item_id"),
            "installer_account_id": e.get("installer_account_id"),
            "payload": e.get("payload") or {},
            "created_at": e.get("created_at"),
        }
        for e in events
    ]

    # Webhook deliveries — "a file was dropped / monday called us", including
    # the skips and no-file deliveries monday's own log shows as Success. An
    # absent webhook_log table (0004 not run) degrades to an empty list.
    hooks, hooks_total = store.webhook_page(page, offset)
    for h in hooks:
        feed.append({
            "action": f"webhook_{h.get('outcome') or 'processed'}",
            "monday_item_id": h.get("monday_item_id"),
            "installer_account_id": None,
            "payload": {
                "file": h.get("file_name"),
                "order": h.get("opportunity_id"),
                "detail": h.get("reason") or h.get("status"),
                "took": took(h.get("duration_ms")),
            },
            "created_at": h.get("created_at"),
        })

    # File reads — what the parser made of each upload.
    reads, reads_total = store.ingest_page(page, offset)
    for r in reads:
        notes = r.get("error") or " · ".join(
            [*(r.get("changed_fields") or []), *(r.get("warnings") or [])][:3]
        )
        feed.append({
            "action": f"file_{r.get('status') or 'read'}",
            "monday_item_id": r.get("monday_item_id"),
            "installer_account_id": None,
            "payload": {
                "file": r.get("file_name"),
                "order": r.get("opportunity_id"),
                "detail": notes or None,
                "took": took(r.get("duration_ms")),
            },
            "created_at": r.get("created_at"),
        })

    feed.sort(key=lambda e: e.get("created_at") or "", reverse=True)

    notifications, notifications_total = store.notifications_page(
        page, max(0, notifications_offset))
    reasons, reasons_total = store.reasons_page(
        page, max(0, reasons_offset))
    return {
        "page_size": page,
        "events": feed,
        "events_total": max(events_total, hooks_total, reads_total),
        "notifications": notifications,
        "notifications_total": notifications_total,
        "unknown_order_reasons": reasons,
        "reasons_total": reasons_total,
    }


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


def _ingest_row(r):
    return {
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


@app.get("/api/py/recent")
def recent(
    limit: int = Query(default=20),
    offset: int = Query(default=0),
    status: str = Query(default=""),
    q: str = Query(default=""),
    x_portal_secret: str = Header(default=""),
):
    """The read ledger, for the dashboard — paginated and searchable server
    side, so a search covers the whole history rather than the loaded page.
    No secrets — but customer names, order IDs and file names ARE business
    data, so only the app's own server (which holds the shared secret and
    sits behind the login) may ask."""
    _authorise(x_portal_secret)
    store = Store()
    if not store.enabled:
        return {"enabled": False, "ingests": [], "total": 0, "counts": {},
                "database": store.ping()}

    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    status = status if status in ("read", "check", "failed") else None
    rows, total = store.ingest_page(limit, offset, status=status, q=q)
    if store.degraded:
        return {"enabled": False, "ingests": [], "total": 0, "counts": {},
                "database": store.ping()}

    return {
        "enabled": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        # Whole-ledger counts, not counts of the visible page — "2 failed"
        # should mean two failures, full stop.
        "counts": store.ingest_counts(),
        "ingests": [_ingest_row(r) for r in rows],
    }


@app.get("/api/py/stats")
def stats(
    days: int = Query(default=30),
    x_portal_secret: str = Header(default=""),
):
    """The dashboard's activity chart and health tiles, in one call.

    Aggregated here, not in the browser: PostgREST doesn't group, and the
    dashboard should not download a month of rows to draw twelve pixels of
    bar. Same audience and guard as /recent.
    """
    _authorise(x_portal_secret)
    store = Store()
    if not store.enabled:
        return {"enabled": False, "database": store.ping()}

    from datetime import date, datetime, timedelta, timezone

    days = max(7, min(days, 90))
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days - 1)
    rows = store.ingests_since(f"{cutoff.isoformat()}T00:00:00Z")
    if store.degraded:
        return {"enabled": False, "database": store.ping()}

    by_day = {}
    durations = []
    totals = {"read": 0, "check": 0, "failed": 0}
    for row in rows:
        status = row.get("status")
        if status not in totals:
            continue
        day = str(row.get("created_at") or "")[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        bucket = by_day.setdefault(day, {"read": 0, "check": 0, "failed": 0})
        bucket[status] += 1
        totals[status] += 1
        if row.get("duration_ms"):
            durations.append(int(row["duration_ms"]))

    series = []
    for offset in range(days):
        day = (cutoff + timedelta(days=offset)).isoformat()
        series.append({"date": day, **by_day.get(day, {"read": 0, "check": 0,
                                                       "failed": 0})})

    total = sum(totals.values())
    durations.sort()

    def percentile(p):
        if not durations:
            return None
        return durations[min(len(durations) - 1, int(len(durations) * p))]

    return {
        "enabled": True,
        "window_days": days,
        "days": series,
        "totals": totals,
        "success_rate": (totals["read"] / total) if total else None,
        "median_ms": percentile(0.5),
        "p90_ms": percentile(0.9),
    }


@app.get("/api/py/order")
def order_detail(item_id: int = Query(...), x_portal_secret: str = Header(default="")):
    """Everything recorded about one order: every read (with the full parse,
    warnings and change history) and every webhook delivery. The order detail
    page's one call. Same audience and guard as /recent."""
    _authorise(x_portal_secret)
    store = Store()
    if not store.enabled:
        return {"enabled": False, "ingests": [], "webhooks": [],
                "database": store.ping()}
    ingests = store.order_ingests(item_id)
    return {
        "enabled": True,
        "ingests": [
            {**_ingest_row(r), "parsed": r.get("parsed") or {}}
            for r in ingests
        ],
        "webhooks": [_webhook_row(h) for h in store.order_webhooks(item_id)],
    }


def _webhook_row(h):
    return {
        "monday_item_id": h.get("monday_item_id"),
        "opportunity_id": h.get("opportunity_id"),
        "file_name": h.get("file_name"),
        "outcome": h.get("outcome"),
        "reason": h.get("reason"),
        "status": h.get("status"),
        "duration_ms": h.get("duration_ms"),
        "created_at": h.get("created_at"),
    }


@app.get("/api/py/webhooks")
def webhook_deliveries(
    limit: int = Query(default=25),
    offset: int = Query(default=0),
    outcome: str = Query(default=""),
    q: str = Query(default=""),
    x_portal_secret: str = Header(default=""),
):
    """The webhook delivery log, paginated — every call monday made, including
    the ones that changed nothing. This is what the ingest ledger never sees:
    duplicate skips and no-file deliveries, which monday's own automation log
    shows as Success. Same audience as /recent, so the same guard.

    An absent table (migration 0004 not run yet) degrades to an empty page
    plus webhook_log_ready=false, which the page turns into a "run the
    migration" hint rather than an empty-log lie.
    """
    _authorise(x_portal_secret)
    store = Store()
    if not store.enabled:
        return {"enabled": False, "webhooks": [], "total": 0,
                "database": store.ping()}

    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    outcome = outcome if outcome in ("processed", "skipped", "failed") else None
    hooks, total = store.webhook_page(limit, offset, outcome=outcome, q=q)

    # Only a 404 means "table not there yet". Anything else — bad key,
    # network — is the database misbehaving, and saying "run the migration"
    # would send someone to fix the wrong thing.
    degraded = str(store.degraded or "")
    if degraded and not degraded.startswith("HTTP 404"):
        return {"enabled": False, "webhooks": [], "total": 0,
                "database": store.ping()}
    webhook_log_ready = not degraded

    return {
        "enabled": True,
        "webhook_log_ready": webhook_log_ready,
        "total": total,
        "limit": limit,
        "offset": offset,
        "webhooks": [_webhook_row(h) for h in hooks],
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
