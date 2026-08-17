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

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from _lib import bootstrap, config, portal  # noqa: E402
from _lib.ingest import handle_webhook  # noqa: E402
from _lib.monday import Monday, MondayError  # noqa: E402
from _lib.store import Store  # noqa: E402

app = FastAPI(title="Navtek eOrder service", docs_url=None, redoc_url=None)


# A bare "HTTP 500" on the setup page tells whoever is running it nothing at
# all. These put the actual cause in the response body, which is the only place
# they can see it without opening Vercel's logs.
@app.exception_handler(MondayError)
async def _monday_error(request, exc):
    return JSONResponse({"detail": f"monday API: {exc}"}, status_code=502)


@app.exception_handler(Exception)
async def _any_error(request, exc):
    return JSONResponse(
        {"detail": f"{type(exc).__name__}: {exc}"}, status_code=500
    )


@app.get("/api/py/health")
def health():
    unmapped = [k for k, v in config.COLUMNS.items() if not v]
    return {
        "ok": not config.missing_secrets(),
        "missing_secrets": config.missing_secrets(),
        "unmapped_columns": unmapped,
        "orders_board": config.ORDERS_BOARD_ID,
        "write_order_type": config.WRITE_ORDER_TYPE,
    }


# --------------------------------------------------------------------------
# The automation
# --------------------------------------------------------------------------

@app.post("/api/py/eorder")
async def eorder(request: Request):
    payload = await request.json()

    # monday's webhook handshake: echo the challenge on registration.
    if "challenge" in payload:
        return {"challenge": payload["challenge"]}

    result = handle_webhook(payload)
    return JSONResponse(result, status_code=200 if result.get("ok") else 422)


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
# Portal backend
# --------------------------------------------------------------------------

def _authorise(secret):
    """Only the portal may call these. The browser holds the magic-link token;
    the portal server holds this shared secret and adds it server-side."""
    if not config.PORTAL_SHARED_SECRET:
        return
    if secret != config.PORTAL_SHARED_SECRET:
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
    if key != SETUP_KEY:
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
    try:
        return bootstrap.register_webhook(Monday(), f"{url}/api/py/eorder")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/py/recent")
def recent(limit: int = Query(default=20)):
    """Recent eOrder reads, for the dashboard. No secrets in the response."""
    store = Store()
    if not store.enabled:
        return {"enabled": False, "ingests": []}
    rows = store.recent_ingests(min(limit, 50))
    return {
        "enabled": True,
        "ingests": [
            {
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
    }


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
