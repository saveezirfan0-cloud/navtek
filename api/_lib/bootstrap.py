"""Board and account setup.

Extracted from the CLI script so the same code backs the browser setup page.
Nothing here is destructive: columns are created only when a column of that
title does not already exist, so every function is safe to run twice.
"""

import secrets

from . import config, installers

# (config key, monday title, column type, defaults)
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

INSTALLER_COLUMNS = [
    ("account_type", "Type", "status",
     {"labels": {"1": "Company", "2": "Sole operator"}}),
    ("coordinator_name", "Coordinator name", "text", None),
    ("coordinator_mobile", "Coordinator mobile", "phone", None),
    ("coordinator_email", "Coordinator email", "email", None),
    ("portal_token", "Portal token", "text", None),
    ("region", "Region", "dropdown", None),
    ("active", "Active", "checkbox", None),
]

# The "Installer" connect-boards column is created separately — it needs the
# Installer Accounts board to exist first.
INSTALLER_LINK_COLUMN = ("installer", "Installer", "board_relation")

SEED_ACCOUNTS = [
    ("Dan Wells", "Sole operator"),
    ("Paul Redmond / FFT Technology", "Company"),
    ("Rob Salerno", "Sole operator"),
    ("David Unger", "Sole operator"),
    ("Ahmed", "Sole operator"),
    ("GPS Tech", "Company"),
    ("Quality Installs", "Company"),
    ("TN", "Company"),
]


def plan_columns(monday, board_id=None):
    """What create_columns() would do. Read this before running it."""
    board_id = board_id or config.ORDERS_BOARD_ID
    existing = {c["title"].strip().lower(): c for c in monday.board_columns(board_id)}
    plan = []
    for key, title, ctype, _ in ORDER_COLUMNS:
        found = existing.get(title.lower())
        plan.append({
            "key": key, "title": title, "type": ctype,
            "action": "exists" if found else "create",
            "column_id": found["id"] if found else None,
        })
    return plan


def create_columns(monday, board_id=None):
    """Create the §3.1 columns. Returns the full COLUMN_IDS map."""
    board_id = board_id or config.ORDERS_BOARD_ID
    existing = {c["title"].strip().lower(): c for c in monday.board_columns(board_id)}
    resolved = {k: v for k, v in config.COLUMNS.items() if v}
    log = []

    for key, title, ctype, defaults in ORDER_COLUMNS:
        found = existing.get(title.lower())
        if found:
            resolved[key] = found["id"]
            log.append(f"exists   {title} ({found['id']})")
            continue
        created = monday.create_column(board_id, title, ctype, defaults)
        resolved[key] = created["id"]
        log.append(f"created  {title} ({created['id']})")

    return {"column_ids": resolved, "log": log}


def create_installer_link(monday, installers_board_id, orders_board_id=None):
    """The Installer connect-boards column on TN Orders.

    Replaces the free-text `installer` column, which holds things like
    "Now Dan Wells = SYD (was GPS TECH)" and cannot be filtered or used to route
    an SMS (§6). The old column is left alone as historical reference.
    """
    orders_board_id = orders_board_id or config.ORDERS_BOARD_ID
    key, title, ctype = INSTALLER_LINK_COLUMN

    for column in monday.board_columns(orders_board_id):
        if column["title"].strip().lower() == title.lower() and column["type"] == ctype:
            return {"column_id": column["id"], "created": False}

    created = monday.create_column(
        orders_board_id, title, ctype,
        {"boardIds": [int(installers_board_id)]},
    )
    return {"column_id": created["id"], "created": True}


def find_installer_board(monday, name="Installer Accounts"):
    data = monday.gql(
        "query ($n: String!) { boards (limit: 200) { id name } }", {"n": name}
    )
    for board in data.get("boards") or []:
        if board["name"].strip().lower() == name.lower():
            return board["id"]
    return None


def create_installer_board(monday):
    """Create and seed Installer Accounts. Idempotent on the board name."""
    existing = find_installer_board(monday)
    if existing:
        return {"board_id": existing, "created": False, "log": ["board already exists"]}

    data = monday.gql(
        "mutation ($n: String!) { create_board (board_name: $n, board_kind: private) { id } }",
        {"n": "Installer Accounts"},
    )
    board_id = data["create_board"]["id"]
    log = [f"created board {board_id}"]

    columns = {}
    for key, title, ctype, defaults in INSTALLER_COLUMNS:
        created = monday.create_column(board_id, title, ctype, defaults)
        columns[key] = created["id"]
        log.append(f"created  {title} ({created['id']})")

    groups = monday.board_groups(board_id)
    group_id = groups[0]["id"] if groups else "topics"

    for name, account_type in SEED_ACCOUNTS:
        monday.create_item(board_id, group_id, name, {
            columns["account_type"]: {"label": account_type},
            # This token is the entirety of the portal's authentication, so it
            # comes from urandom and is never derived from a name or an id.
            columns["portal_token"]: secrets.token_urlsafe(32),
            columns["active"]: {"checked": "true"},
        })
        log.append(f"seeded   {name}")

    return {"board_id": board_id, "created": True, "log": log, "columns": columns}


def sync_installers(monday, store, installers_board_id=None):
    """Copy Installer Accounts from monday into Supabase.

    The portal authenticates a magic link by looking the token up in Supabase,
    so an account added in monday is invisible to the portal until this runs.
    Re-run it whenever an account is added, deactivated or reissued.
    """
    board_id = installers_board_id or config.INSTALLERS_BOARD_ID
    if not board_id:
        raise ValueError("INSTALLERS_BOARD_ID is not set")
    if not store.enabled:
        raise ValueError("Supabase is not configured")

    data = monday.gql(
        """
        query ($b: [ID!]) {
          boards (ids: $b) {
            columns { id title type }
            items_page (limit: 200) {
              items { id name column_values { id text } }
            }
          }
        }
        """,
        {"b": [str(board_id)]},
    )
    boards = data.get("boards") or []
    if not boards:
        raise ValueError(f"board {board_id} not found")

    by_title = {c["title"].strip().lower(): c["id"] for c in boards[0]["columns"]}

    def column(values, title):
        column_id = by_title.get(title.lower())
        return values.get(column_id) if column_id else None

    rows, skipped = [], []
    for item in boards[0]["items_page"]["items"]:
        values = {c["id"]: c.get("text") for c in item["column_values"]}
        token = column(values, "Portal token")
        if not token:
            skipped.append(item["name"])
            continue
        active_raw = (column(values, "Active") or "").strip().lower()
        rows.append({
            "monday_item_id": int(item["id"]),
            "account_name": item["name"],
            "account_type": column(values, "Type"),
            "coordinator_name": column(values, "Coordinator name"),
            "coordinator_mobile": column(values, "Coordinator mobile"),
            "coordinator_email": column(values, "Coordinator email"),
            "portal_token": token,
            "region": column(values, "Region"),
            "active": active_raw in ("v", "true", "checked", "yes", "1"),
            "match_key": installers.match_key(item["name"]),
        })

    if rows:
        store.upsert_accounts(rows)

    return {"synced": len(rows), "skipped_no_token": skipped}


def register_webhook(monday, url, board_id=None, file_column_id=None):
    board_id = board_id or config.ORDERS_BOARD_ID
    column_id = file_column_id or config.COLUMNS.get("eorder_file")
    if not column_id:
        raise ValueError("the eOrder file column id is not configured yet")
    hook = monday.create_webhook(
        board_id, url, "change_specific_column_value", {"columnId": column_id}
    )
    return {"webhook_id": hook["id"], "url": url, "column_id": column_id}
