"""Configuration.

Column IDs are configuration, not constants. The existing columns have real IDs
(taken from brief §4). The new columns in §3.1 do not exist yet — run
`scripts/bootstrap_board.py`, which creates them and prints a COLUMN_IDS block
to paste into the environment.

Anything not yet mapped is left as None and simply skipped by the writer, so the
service runs end to end against the existing columns before the board work is
done.
"""

import json
import os

# Bumped with every packaged build. Shown on /health and the dashboard so
# "which build is actually live" is a fact you can read, not a guess — an
# ambiguity that has cost real debugging time in this project.
APP_VERSION = "2026-08-19.6"


def _clean_secret(value):
    """Strip the two paste accidents that make a correct credential fail.

    Values arrive here by being copied out of a dashboard and pasted into a
    settings box, so a trailing space or newline rides along easily, and a
    value copied via a shell keeps its quotes. Both make the real service
    reject a key that is otherwise correct — SETUP.md calls stray spaces the
    single most common cause of "it says my token is wrong", and this makes
    that sentence true in code rather than only in documentation.

    Only applied to credentials sent to monday and Supabase. Symmetric secrets
    (SETUP_KEY, PORTAL_SHARED_SECRET) are compared against what the other side
    holds, so cleaning one side alone could un-match a pair that currently
    works.
    """
    value = (value or "").strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


# --------------------------------------------------------------------------
# Secrets — server side only, always. Never expose to a browser (brief §10).
# --------------------------------------------------------------------------
MONDAY_TOKEN = _clean_secret(os.environ.get("MONDAY_TOKEN", ""))
MONDAY_API_URL = os.environ.get("MONDAY_API_URL", "https://api.monday.com/v2")
MONDAY_API_VERSION = os.environ.get("MONDAY_API_VERSION", "2024-10")

# Supabase credentials, as an ordered list of candidate pairs.
#
# A URL and a key have to come from the SAME project, and it is easy to end up
# with one of each from two projects — the error is identical to a wrong key,
# so guessing between them wastes a lot of time. Setting a second pair lets the
# app try both and report which one actually works.
#
#   SUPABASE_URL   / SUPABASE_SERVICE_KEY     (primary)
#   SUPABASE_URL_2 / SUPABASE_SERVICE_KEY_2   (optional alternative)
#
# SUPABASE_SECRET_KEY is accepted as an alias, since that is what the Supabase
# dashboard now calls it.
def supabase_candidates():
    pairs = [
        ("SUPABASE_SERVICE_KEY",
         os.environ.get("SUPABASE_URL", ""),
         os.environ.get("SUPABASE_SERVICE_KEY", "")),
        ("SUPABASE_SECRET_KEY",
         os.environ.get("SUPABASE_URL", ""),
         os.environ.get("SUPABASE_SECRET_KEY", "")),
        ("SUPABASE_SERVICE_KEY_2",
         os.environ.get("SUPABASE_URL_2") or os.environ.get("SUPABASE_URL", ""),
         os.environ.get("SUPABASE_SERVICE_KEY_2", "")),
    ]
    seen, out = set(), []
    for name, url, key in pairs:
        url, key = _clean_secret(url), _clean_secret(key)
        if url and key and (url, key) not in seen:
            seen.add((url, key))
            out.append({"name": name, "url": url.rstrip("/"), "key": key})
    return out


SUPABASE_URL = _clean_secret(os.environ.get("SUPABASE_URL", ""))
_first = supabase_candidates()
SUPABASE_SERVICE_KEY = _first[0]["key"] if _first else ""

# Shared secret between the portal (Next.js) and this service. The portal is the
# only client allowed to call /portal/*; it holds this, the browser never does.
PORTAL_SHARED_SECRET = os.environ.get("PORTAL_SHARED_SECRET", "")

# Vercel sends this as "Authorization: Bearer <CRON_SECRET>" on cron requests.
# The sweep and resync endpoints accept it as an alternative to the portal
# secret, because a cron cannot send custom headers.
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# Optional webhook hardening. When set, the registered webhook URL carries it
# as ?hook=… and /eorder rejects deliveries without it — otherwise anyone who
# can reach the public URL can hand the automation a payload. Set it, then
# re-run setup step 4 so the registration picks it up.
WEBHOOK_SECRET = _clean_secret(os.environ.get("WEBHOOK_SECRET", ""))


# Where the app is reachable from an installer's phone — used to build the
# portal link in SMS bodies. Falls back to Vercel's own idea of the deployment.
def portal_base_url():
    for name in ("APP_URL", "PORTAL_BASE_URL"):
        value = (os.environ.get(name) or "").strip().rstrip("/")
        if value:
            return value
    host = (os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
            or os.environ.get("VERCEL_URL") or "").strip().rstrip("/")
    return f"https://{host}" if host else ""

# --------------------------------------------------------------------------
# Boards
# --------------------------------------------------------------------------
ORDERS_BOARD_ID = int(os.environ.get("ORDERS_BOARD_ID", "5834171978"))
INSTALLERS_BOARD_ID = int(os.environ.get("INSTALLERS_BOARD_ID", "0")) or None

# --------------------------------------------------------------------------
# Column IDs
#
# Existing columns: IDs confirmed in brief §4.
# New columns: filled in by bootstrap_board.py.
# --------------------------------------------------------------------------
_DEFAULT_COLUMNS = {
    # --- existing, confirmed ---
    "opportunity_id": "order__",
    # The orders board's own status column — the one Navtek staff work from.
    # Lookup-only (LEGACY_COLUMNS): the SLA escalation writes its existing
    # "6.1 Installer Esc." label here, and if the board has no such column the
    # escalation is skipped and reported rather than guessed at.
    "order_status": None,
    "order_type": "order_type9",
    "platform": "platform1",
    "migration_required": "migration_required",
    "order_date": "date3",
    "dealer_commission": "total_commission",
    "install_value": "numeric",
    "acv": "numeric_mm0asnac",
    # --- new, created by bootstrap ---
    "eorder_file": None,
    "eorder_status": None,
    "site_contact": None,
    "site_phone": None,
    "site_email": None,
    "site_address": None,
    "installer": None,
    "installer_email": None,
    "install_required": None,
    "vehicle_list": None,
    "units_total": None,
    "units_installed": None,
    "progress_updated": None,
    "contacted_date": None,
    "booked_date": None,
    "scheduled_install_date": None,
}


def _parse_column_ids(raw):
    """Read COLUMN_IDS as leniently as possible. Never raise.

    This value is copied out of a web page and pasted into a settings box, so
    the failure modes are paste failures, not programming errors: the whole
    `NAME=value` line pasted into the value box, two lines pasted at once,
    stray quotes from a shell, trailing whitespace.

    An earlier version raised RuntimeError here. Because every module imports
    this one, a mistyped environment variable took down the entire
    application — every route returning a bare HTTP 500 with no body, since
    the crash happened at import before any error handler existed. A bad
    setting should degrade one feature, never the whole app, so this now
    returns a warning and carries on. The IDs are resolved from the board
    anyway (see columns.py); COLUMN_IDS is only an override.
    """
    text = (raw or "").strip()
    if not text:
        return {}, None

    # Two variables pasted at once — keep the line that has our JSON on it.
    if "\n" in text:
        for line in text.splitlines():
            if "{" in line:
                text = line.strip()
                break

    # The whole `COLUMN_IDS={...}` line pasted into the value box.
    for prefix in ("COLUMN_IDS=", "column_ids=", "COLUMN_IDS ="):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    # Shell-style quoting picked up on the way through.
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()

    if not text:
        return {}, None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, (
            f"COLUMN_IDS could not be read ({exc}). It is being ignored and "
            f"column IDs are coming from the board instead. Expected a single "
            f"line starting with {{ — check nothing extra was pasted with it. "
            f"Value starts: {text[:40]!r}"
        )

    if not isinstance(parsed, dict):
        return {}, f"COLUMN_IDS should be a JSON object, got {type(parsed).__name__}. Ignoring it."

    unknown = [k for k in parsed if k not in _DEFAULT_COLUMNS]
    warning = f"COLUMN_IDS contains unrecognised keys, ignored: {', '.join(unknown)}" if unknown else None
    return {k: v for k, v in parsed.items() if v and k in _DEFAULT_COLUMNS}, warning


# Problems worth telling someone about, surfaced by /health and the dashboard
# rather than thrown.
CONFIG_WARNINGS = []


def _load_columns():
    cols = dict(_DEFAULT_COLUMNS)
    overrides, warning = _parse_column_ids(os.environ.get("COLUMN_IDS", ""))
    if warning:
        CONFIG_WARNINGS.append(warning)
    cols.update(overrides)
    return cols


COLUMNS = _load_columns()

# --------------------------------------------------------------------------
# Behaviour switches
# --------------------------------------------------------------------------

# Order Type is unresolved (brief §4): monday's values are compound
# ("New Business | Rental") and the eOrder only supplies the first half. The
# Kane Civil file is headed "OUTRIGHT ORDER FORM" while its monday row reads
# "New Business | Rental", so the form title is not a usable source.
#
# Default off. Do not turn this on until Damon's team has confirmed where
# Rental vs Outright comes from — a wrong value here is worse than a blank one,
# because a blank prompts someone to fill it in and a wrong one does not.
WRITE_ORDER_TYPE = os.environ.get("WRITE_ORDER_TYPE", "false").lower() == "true"

# Testing escape hatch: re-read a file the ledger has already seen instead of
# skipping it. The duplicate skip (acceptance criterion 2) is right for
# production — the same file re-dropped must not fork or re-notify — but while
# testing, dropping the same sample repeatedly is the whole workflow, and every
# drop after the first looks like the automation died. Default off; existing
# monday values are still never clobbered when it is on (merge_preserving).
ALLOW_DUPLICATE_FILES = (
    os.environ.get("ALLOW_DUPLICATE_FILES", "false").lower() == "true"
)

# Fuzzy-match threshold for ship-to → Installer Account. Below this we write
# nothing and flag Check rather than guessing (brief §6.2).
INSTALLER_MATCH_THRESHOLD = float(os.environ.get("INSTALLER_MATCH_THRESHOLD", "0.86"))

# monday asset public_urls expire after one hour. Fetch immediately, never
# store, never cache the URL itself (brief §3.2, §6.3).
ASSET_FETCH_TIMEOUT = int(os.environ.get("ASSET_FETCH_TIMEOUT", "30"))

# --------------------------------------------------------------------------
# SLA engine
# --------------------------------------------------------------------------

# The hard go-live cutoff. Only jobs whose dispatch date is ON OR AFTER this
# date ever enter the SLA engine — everything older is historical backlog that
# Navtek reconciles with installers by hand. The board carries jobs up to 212
# business days overdue; a sweep without this cutoff texts every installer
# about months-old jobs in its first hour and kills trust in the whole system.
# Unset means the SLA engine (sweep, SMS, escalation) is OFF, not "no cutoff".
SLA_GO_LIVE_DATE = os.environ.get("SLA_GO_LIVE_DATE", "").strip()

# Contact SLA in business days (public holidays per the installer's state).
SLA_BUSINESS_DAYS = int(os.environ.get("SLA_BUSINESS_DAYS", "2"))

# Master switch for actually sending anything (SMS, escalation status writes).
# Default false: the sweep runs in shadow mode first, logging what it WOULD
# send, until a week of real orders has been read from that log.
SLA_NOTIFICATIONS_ENABLED = (
    os.environ.get("SLA_NOTIFICATIONS_ENABLED", "false").lower() == "true"
)


def sla_go_live():
    """The cutoff as a date, or None when unset/unparseable.

    Parsed at call time, not import time, so /health can report a typo and a
    fixed value takes effect without hunting down module state.
    """
    from datetime import date as _date
    raw = (os.environ.get("SLA_GO_LIVE_DATE") or SLA_GO_LIVE_DATE or "").strip()
    if not raw:
        return None
    try:
        return _date.fromisoformat(raw[:10])
    except ValueError:
        return None


def missing_secrets():
    """Return the names of required secrets that are not set."""
    missing = []
    if not MONDAY_TOKEN:
        missing.append("MONDAY_TOKEN")
    if not supabase_candidates():
        missing.append("SUPABASE_URL + SUPABASE_SERVICE_KEY")
    # Without it, logins, the portal and user management refuse to serve
    # (they fail closed rather than running open) — so its absence is a
    # missing secret, not a quiet default.
    if not PORTAL_SHARED_SECRET:
        missing.append("PORTAL_SHARED_SECRET")
    return missing
