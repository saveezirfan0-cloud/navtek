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

    try:
        live = monday.board_columns(board_id)
    except Exception:
        # monday unreachable: fall back to whatever the environment gave us
        # rather than failing the whole request.
        return {**config.COLUMNS, **columns}

    by_title = {}
    for column in live:
        by_title.setdefault(column["title"].strip().lower(), column)

    for key, title, ctype, _ in ORDER_COLUMNS + [INSTALLER_LINK_COLUMN + (None,)]:
        if columns.get(key):
            continue
        found = by_title.get(title.lower())
        if found and _compatible(found["type"], ctype):
            columns[key] = found["id"]

    full = {**config.COLUMNS, **columns}
    _cache.update({"at": now, "board": board_id, "columns": full})
    return full


def unmapped(columns):
    return [key for key, value in columns.items() if not value]


def clear_cache():
    _cache.update({"at": 0.0, "board": None, "columns": None})
