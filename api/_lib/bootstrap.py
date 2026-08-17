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
    """Locate the Installer Accounts board by name.

    INSTALLERS_BOARD_ID wins over this — an existing board that happens to be
    called something else is still the right board, and guessing by name would
    create a duplicate alongside it.
    """
    if config.INSTALLERS_BOARD_ID:
        return config.INSTALLERS_BOARD_ID
    data = monday.gql("query { boards (limit: 500) { id name } }")
    for board in data.get("boards") or []:
        if board["name"].strip().lower() == name.lower():
            return board["id"]
    return None


def ensure_installer_board(monday):
    """Adopt an existing Installer Accounts board, or create one.

    Most accounts already track installers somewhere. Rather than making a
    second board alongside it, this takes whatever board INSTALLERS_BOARD_ID
    points at (or finds one by name), adds only the columns that are missing,
    and issues a portal token to any account that doesn't have one.

    Seeding only happens on a genuinely empty board. On a board that already
    has rows, the existing names are the truth and SEED_ACCOUNTS would just be
    eight duplicates to clean up.
    """
    board_id = find_installer_board(monday)
    log = []
    created_board = False

    if board_id:
        log.append(f"using existing board {board_id}")
    else:
        data = monday.gql(
            "mutation ($n: String!) { create_board (board_name: $n, board_kind: private) { id } }",
            {"n": "Installer Accounts"},
        )
        board_id = data["create_board"]["id"]
        created_board = True
        log.append(f"created board {board_id}")

    # --- columns: add only what's missing ---
    existing = {c["title"].strip().lower(): c for c in monday.board_columns(board_id)}
    columns = {}
    for key, title, ctype, defaults in INSTALLER_COLUMNS:
        found = existing.get(title.lower())
        if found:
            columns[key] = found["id"]
            log.append(f"exists   {title} ({found['id']})")
            continue
        created = monday.create_column(board_id, title, ctype, defaults)
        columns[key] = created["id"]
        log.append(f"created  {title} ({created['id']})")

    # --- accounts ---
    data = monday.gql(
        """
        query ($b: [ID!]) {
          boards (ids: $b) {
            groups { id }
            items_page (limit: 500) { items { id name column_values { id text } } }
          }
        }
        """,
        {"b": [str(board_id)]},
    )
    board = (data.get("boards") or [{}])[0]
    items = (board.get("items_page") or {}).get("items") or []
    groups = board.get("groups") or []
    group_id = groups[0]["id"] if groups else "topics"

    token_column = columns["portal_token"]

    if not items:
        for name, account_type in SEED_ACCOUNTS:
            monday.create_item(board_id, group_id, name, {
                columns["account_type"]: {"label": account_type},
                token_column: secrets.token_urlsafe(32),
                columns["active"]: {"checked": "true"},
            })
            log.append(f"seeded   {name}")
    else:
        issued = 0
        for item in items:
            values = {c["id"]: c.get("text") for c in item["column_values"]}
            if (values.get(token_column) or "").strip():
                continue
            monday.set_columns(
                board_id, item["id"], {token_column: secrets.token_urlsafe(32)}
            )
            issued += 1
            log.append(f"token    {item['name']}")
        log.append(
            f"{len(items)} existing account(s), {issued} issued a portal token"
        )

    return {
        "board_id": board_id,
        "created": created_board,
        "log": log,
        "columns": columns,
        "accounts": len(items) or len(SEED_ACCOUNTS),
    }


# Kept for the CLI script and anyone following the old name.
create_installer_board = ensure_installer_board


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


def eorder_column_id(monday, board_id=None):
    """The eOrder file column, from config or looked up live.

    Looked up rather than required, so the webhook can be registered before
    COLUMN_IDS has been pasted into the environment — otherwise step 6 depends
    on a redeploy that hasn't happened yet.
    """
    if config.COLUMNS.get("eorder_file"):
        return config.COLUMNS["eorder_file"]
    for column in monday.board_columns(board_id or config.ORDERS_BOARD_ID):
        if column["type"] == "file" and column["title"].strip().lower() == "eorder":
            return column["id"]
    return None


def register_webhook(monday, url, board_id=None, file_column_id=None):
    board_id = board_id or config.ORDERS_BOARD_ID
    column_id = file_column_id or eorder_column_id(monday, board_id)
    if not column_id:
        raise ValueError(
            "No file column called 'eOrder' on the board. Run step 2 first."
        )

    # Registering twice would process every dropped file twice.
    for hook in monday.webhooks(board_id):
        if hook.get("config") and column_id in str(hook["config"]):
            return {
                "webhook_id": hook["id"],
                "url": url,
                "column_id": column_id,
                "already_registered": True,
            }

    hook = monday.create_webhook(
        board_id, url, "change_specific_column_value", {"columnId": column_id}
    )
    return {"webhook_id": hook["id"], "url": url, "column_id": column_id}
