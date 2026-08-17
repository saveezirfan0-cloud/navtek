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

# --------------------------------------------------------------------------
# Secrets — server side only, always. Never expose to a browser (brief §10).
# --------------------------------------------------------------------------
MONDAY_TOKEN = os.environ.get("MONDAY_TOKEN", "")
MONDAY_API_URL = os.environ.get("MONDAY_API_URL", "https://api.monday.com/v2")
MONDAY_API_VERSION = os.environ.get("MONDAY_API_VERSION", "2024-10")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")  # sb_secret_... or legacy service_role

# Shared secret between the portal (Next.js) and this service. The portal is the
# only client allowed to call /portal/*; it holds this, the browser never does.
PORTAL_SHARED_SECRET = os.environ.get("PORTAL_SHARED_SECRET", "")

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


def _load_columns():
    cols = dict(_DEFAULT_COLUMNS)
    raw = os.environ.get("COLUMN_IDS", "")
    if raw:
        try:
            cols.update({k: v for k, v in json.loads(raw).items() if v})
        except json.JSONDecodeError as exc:  # pragma: no cover - config error
            raise RuntimeError(f"COLUMN_IDS is not valid JSON: {exc}") from exc
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

# Fuzzy-match threshold for ship-to → Installer Account. Below this we write
# nothing and flag Check rather than guessing (brief §6.2).
INSTALLER_MATCH_THRESHOLD = float(os.environ.get("INSTALLER_MATCH_THRESHOLD", "0.86"))

# monday asset public_urls expire after one hour. Fetch immediately, never
# store, never cache the URL itself (brief §3.2, §6.3).
ASSET_FETCH_TIMEOUT = int(os.environ.get("ASSET_FETCH_TIMEOUT", "30"))


def missing_secrets():
    """Return the names of required secrets that are not set."""
    required = {
        "MONDAY_TOKEN": MONDAY_TOKEN,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    }
    return [name for name, value in required.items() if not value]
