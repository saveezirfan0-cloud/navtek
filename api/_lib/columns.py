"""Where the monday column IDs come from.

Originally these lived only in the `COLUMN_IDS` environment variable, pasted in
after running the setup page. That works but it is brittle in a specific way:
the app cannot function until someone copies a blob of JSON into Vercel and
triggers a redeploy, and if either half of that doesn't happen the failure is
silent — columns simply never get written and nothing says why.

So the env var is now an *override*, not a requirement. Anything it doesn't
supply is looked up on the board by column title, the same way the parser looks
up values by label rather than by cell reference, and for the same reason: a
title survives a board being rebuilt or a column being reordered, and when it
does break it breaks visibly.

Precedence: COLUMN_IDS wins, then the board, then nothing (the writer skips any
column it has no ID for).
"""

import os
import time

from . import config

# (config key, monday title, column type, defaults) — the board schema from
# brief §3.1. bootstrap.py imports this rather than defining its own copy, so
# creation and lookup can never disagree about a title.
ORDER_COLUMNS = [
    ("eorder_file", "eOrder", "file", None),
    ("eorder_status", "eOrder Status", "status",
     {"labels": {"1": "✅ Read", "2": "⚠️ Check", "3": "❌ Failed"}}),
    ("site_contact", "Site Contact", "text", None),
    ("site_phone", "Site Phone", "phone", None),
    ("site_email", "Site Email", "email", None),
    ("site_address", "Site Address", "text", None),
    ("installer_email", "Installer Email", "email", None),
    ("install_required", "Install Required?", "status",
     {"labels": {"1": "Yes", "2": "No", "3": "Customer self-install"}}),
    ("vehicle_list", "Vehicle List", "file", None),
    ("units_total", "Units Total", "numbers", None),
    ("units_installed", "Units Installed", "numbers", None),
    ("progress_updated", "Progress Updated", "date", None),
    ("contacted_date", "Contacted Date", "date", None),
    ("booked_date", "Booked Date", "date", None),
    ("scheduled_install_date", "Scheduled Install Date", "date", None),
]

INSTALLER_LINK_COLUMN = ("installer", "Installer", "board_relation")

# Columns that already existed on the production board before this app.
#
# On production these resolve from their pinned IDs and this map is never
# consulted. It matters on any other board — a test copy, or production after a
# rebuild — where those IDs don't exist. Several candidate titles per column
# because the exact wording isn't certain; an exact title match on a compatible
# type binds, anything else leaves the column unmapped, which is the same
# outcome as not trying. This map is lookup-only: nothing here is ever created,
# so a wrong guess cannot add a duplicate column to a live board.
LEGACY_COLUMNS = [
    ("opportunity_id", ["OPPORTUNITY ID #", "Opportunity ID #", "Opportunity ID",
                        "Opportunity Field ID"], "text"),
    ("order_type", ["Order Type"], "status"),
    ("platform", ["Platform"], "status"),
    ("migration_required", ["Migration Required", "Migration Required?",
                            "Migration"], "status"),
    ("order_date", ["ORDER PLACED", "Order Placed", "Order Date",
                    "Date Ordered"], "date"),
    ("dealer_commission", ["Total Commission", "Dealer Commission",
                           "Commission"], "numbers"),
    ("install_value", ["Install Value", "Installation Value",
                       "Install $"], "numbers"),
    ("acv", ["ACV", "Annual Contract Value"], "numbers"),
]

# monday reports some types under a different name from the one you create them
# with, and has renamed a couple over the years. Matching on title alone would
# happily bind a text column called "eOrder" to the file column; matching on an
# exact type string would reject a perfectly good status column reported as
# "color". So: title must match, type must be equivalent.
TYPE_EQUIVALENTS = {
    "status": {"status", "color"},
    "numbers": {"numbers", "numeric"},
    "board_relation": {"board_relation", "connect_boards"},
    "text": {"text", "long-text", "long_text"},
    "file": {"file"},
    "date": {"date"},
    "phone": {"phone"},
    "email": {"email"},
}

def _warn(message):
    """Record once. These surface on /health and the Orders page."""
    if message not in config.CONFIG_WARNINGS:
        config.CONFIG_WARNINGS.append(message)


_CACHE_TTL = 300
_cache = {"at": 0.0, "board": None, "columns": None}


def _compatible(reported, wanted):
    return reported in TYPE_EQUIVALENTS.get(wanted, {wanted})


def resolved(monday, board_id=None, force=False):
    """The full {key: column_id} map, env var first, board second.

    Cached for five minutes per warm function instance. Someone adding a column
    mid-session waits at most that long, which is a fair trade against a monday
    API call on every single webhook.
    """
    board_id = board_id or config.ORDERS_BOARD_ID
    now = time.time()

    if (
        not force
        and _cache["columns"] is not None
        and _cache["board"] == board_id
        and now - _cache["at"] < _CACHE_TTL
    ):
        return _cache["columns"]

    columns = {k: v for k, v in config.COLUMNS.items() if v}
    # Which of those the operator supplied, as opposed to built-in defaults.
    # A stale value matters if someone typed it; a stale built-in default just
    # means this isn't the board those defaults describe.
    from_env, _ = config._parse_column_ids(os.environ.get("COLUMN_IDS", ""))

    try:
        live = monday.board_columns(board_id)
    except Exception:
        # monday unreachable: fall back to whatever the environment gave us
        # rather than failing the whole request.
        return {**config.COLUMNS, **columns}

    live_ids = {column["id"] for column in live}

    # Drop any COLUMN_IDS override that doesn't exist on this board.
    #
    # Column IDs belong to a board. Point ORDERS_BOARD_ID at a different board
    # — say, moving from a test copy to the real one — and every pinned ID
    # becomes wrong, but stays set. Without this the app would keep writing to
    # IDs monday has never heard of on the new board, and the errors would name
    # the column, not the cause. Falling back to lookup-by-title recovers
    # automatically and says so.
    stale = [key for key, value in columns.items() if value not in live_ids]
    for key in stale:
        columns.pop(key)

    stale_from_env = sorted(k for k in stale if k in from_env)
    if stale_from_env:
        _warn(
            f"COLUMN_IDS names {len(stale_from_env)} column(s) that are not on "
            f"board {board_id}: {', '.join(stale_from_env)}. They have been "
            f"ignored and looked up on the board instead. Column IDs belong to "
            f"a board, so this is expected after changing ORDERS_BOARD_ID — "
            f"clearing COLUMN_IDS is the fix."
        )

    by_title = {}
    for column in live:
        by_title.setdefault(column["title"].strip().lower(), column)

    for key, title, ctype, _ in ORDER_COLUMNS + [INSTALLER_LINK_COLUMN + (None,)]:
        if columns.get(key):
            continue
        found = by_title.get(title.lower())
        if found and _compatible(found["type"], ctype):
            columns[key] = found["id"]

    # Pre-existing production columns, by any of their candidate titles.
    for key, titles, ctype in LEGACY_COLUMNS:
        if columns.get(key):
            continue
        for title in titles:
            found = by_title.get(title.lower())
            if found and _compatible(found["type"], ctype):
                columns[key] = found["id"]
                break

    # Every known key, resolved or None. Deliberately NOT merged back over
    # config.COLUMNS — doing that reinstates the very IDs just dropped as
    # stale, which is exactly the bug this line replaces.
    full = {key: columns.get(key) for key in config.COLUMNS}
    _cache.update({"at": now, "board": board_id, "columns": full})
    return full


# Columns this app creates and depends on. Everything else in the map is a
# column that already existed on the production board — useful when present,
# absent on a fresh or test board, and not something setup can fix.
MANAGED = {key for key, _, _, _ in ORDER_COLUMNS} | {INSTALLER_LINK_COLUMN[0]}


def unmapped(columns):
    """Only the columns whose absence is actually a problem."""
    return [k for k, v in columns.items() if not v and k in MANAGED]


def unmapped_optional(columns):
    """Pre-existing production columns not present on this board."""
    return [k for k, v in columns.items() if not v and k not in MANAGED]


def clear_cache():
    _cache.update({"at": 0.0, "board": None, "columns": None})
