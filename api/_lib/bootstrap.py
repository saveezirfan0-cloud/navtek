"""Board and account setup.

Extracted from the CLI script so the same code backs the browser setup page.
Nothing here is destructive: columns are created only when a column of that
title does not already exist, so every function is safe to run twice.
"""

import secrets

from . import config, installers
from .columns import INSTALLER_LINK_COLUMN, ORDER_COLUMNS, resolved

INSTALLER_COLUMNS = [
    ("account_type", "Type", "status",
     {"labels": {"1": "Company", "2": "Sole operator"}}),
    ("coordinator_name", "Coordinator name", "text", None),
    ("coordinator_mobile", "Coordinator mobile", "phone", None),
    ("coordinator_email", "Coordinator email", "email", None),
    ("portal_token", "Portal token", "text", None),
    ("region", "Region", "dropdown", None),
    # Which state's public holidays this account's SLA clock skips (§6 /
    # prompt 6). Defaults to NSW downstream when blank.
    ("state", "State", "status",
     {"labels": {"1": "NSW", "2": "VIC", "3": "QLD", "4": "SA",
                 "5": "WA", "6": "TAS", "7": "ACT", "8": "NT"}}),
    ("active", "Active", "checkbox", None),
]

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
    """Create the §3.1 columns. Returns the full COLUMN_IDS map.

    One column monday refuses must not abort the rest — "This column type is
    not supported yet in the API" on a single type used to leave every column
    after it uncreated, and the step showing nothing but the error. Refusals
    are logged with the exact title so the column can be added by hand, and
    everything else still lands.
    """
    from .monday import MondayError

    board_id = board_id or config.ORDERS_BOARD_ID
    existing = {c["title"].strip().lower(): c for c in monday.board_columns(board_id)}
    resolved = {k: v for k, v in config.COLUMNS.items() if v}
    log, failed = [], []

    for key, title, ctype, defaults in ORDER_COLUMNS:
        found = existing.get(title.lower())
        if found:
            resolved[key] = found["id"]
            log.append(f"exists   {title} ({found['id']})")
            continue
        try:
            created = monday.create_column(board_id, title, ctype, defaults)
        except MondayError as exc:
            failed.append(title)
            log.append(f"failed   {title} — {exc}. Create a '{ctype}' column "
                       f"titled '{title}' on the board by hand, then re-run "
                       "this step to bind it.")
            continue
        resolved[key] = created["id"]
        log.append(f"created  {title} ({created['id']})")

    return {"column_ids": resolved, "log": log, "failed": failed}


def prepare_subitem_columns(monday, board_id=None):
    """Give the subitem board the install-item field set, if it exists yet.

    Subitems live on their own board with their own column IDs, and that board
    only comes into existence with the board's first-ever subitem. Multi-site
    orders prepare the columns themselves on first use; running this from
    Setup makes them visible up front on any board that already has subitems,
    so the field set can be checked before a live multi-site order arrives.
    """
    from . import ingest

    board_id = board_id or config.ORDERS_BOARD_ID
    sub_board = ingest._subitem_board_id(monday, board_id)
    if not sub_board:
        return {"prepared": False, "log": [
            "skipped  install-item columns — this board has no subitems yet; "
            "the columns are created automatically with the first multi-site "
            "order"
        ]}
    ingest._SUB_COLS_CACHE.pop(str(sub_board), None)
    cols = ingest._ensure_subitem_columns(monday, sub_board)
    return {"prepared": True, "subitem_board_id": sub_board, "log": [
        f"ready    install-item columns on the subitem board ({len(cols)} fields)"
    ]}


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

    from .monday import MondayError

    try:
        created = monday.create_column(
            orders_board_id, title, ctype,
            {"boardIds": [int(installers_board_id)]},
        )
    except MondayError as exc:
        # Some accounts' API refuses to create connect-boards columns. The
        # rest of the installer setup still stands; the column can be added by
        # hand (Connect boards → the Installer Accounts board) and this step
        # re-run to bind it.
        return {"column_id": None, "created": False, "error": str(exc)}
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
        from .monday import MondayError

        for name, account_type in SEED_ACCOUNTS:
            try:
                monday.create_item(board_id, group_id, name, {
                    columns["account_type"]: {"label": account_type},
                    token_column: secrets.token_urlsafe(32),
                    columns["active"]: {"checked": "true"},
                })
                log.append(f"seeded   {name}")
            except MondayError as exc:
                # An adopted board's Type column may carry different labels;
                # one refused label must cost that seed row, not the whole
                # setup step (the same containment the ingest applies).
                log.append(f"skipped  {name}: {exc}")
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
            "state": (column(values, "State") or "NSW").strip().upper() or "NSW",
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
    return resolved(monday, board_id, force=True).get("eorder_file")


def register_webhook(monday, url, board_id=None, file_column_id=None):
    board_id = board_id or config.ORDERS_BOARD_ID
    # With WEBHOOK_SECRET set, the registration carries it and /eorder rejects
    # deliveries without it. Registered here so setup step 4 is the only thing
    # to re-run after setting the variable.
    if config.WEBHOOK_SECRET and "hook=" not in url:
        url = f"{url}?hook={config.WEBHOOK_SECRET}"
    column_id = file_column_id or eorder_column_id(monday, board_id)
    if not column_id:
        raise ValueError(
            "No file column called 'eOrder' on the board. Run step 2 first."
        )
    return _register_column_webhook(monday, board_id, column_id, url)


def _register_column_webhook(monday, board_id, column_id, url):
    """change_specific_column_value on one column, exactly once.

    Registering twice would process every change twice — for the eOrder column
    that means every dropped file ingested twice, for the Installer column
    every reallocation handled twice.
    """
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


def register_flow_webhooks(monday, base_url, board_id=None):
    """Every webhook the installer flow needs, idempotently, in one call.

    Alongside the eOrder file webhook: the Installer column (reallocation —
    prompt 4), the dispatch date column, and the board's status column (portal
    cache freshness — prompt 5). Columns that don't exist yet are reported and
    skipped, not fatal — this is safe to re-run after board setup finishes.
    """
    board_id = board_id or config.ORDERS_BOARD_ID
    base = base_url.rstrip("/")
    cols = resolved(monday, board_id, force=True)

    # Same ?hook= hardening as register_webhook — every one of these endpoints
    # is reachable from the open internet and drives monday writes.
    suffix = f"?hook={config.WEBHOOK_SECRET}" if config.WEBHOOK_SECRET else ""
    wanted = [
        ("eorder_file", f"{base}/api/py/eorder{suffix}"),
        ("installer", f"{base}/api/py/installer-change{suffix}"),
        ("order_date", f"{base}/api/py/portal/refresh{suffix}"),
        ("order_status", f"{base}/api/py/portal/refresh{suffix}"),
    ]

    registered, skipped = [], []
    for key, url in wanted:
        column_id = cols.get(key)
        if not column_id:
            skipped.append(key)
            continue
        result = _register_column_webhook(monday, board_id, column_id, url)
        registered.append({"column": key, **result})
    return {"registered": registered, "skipped_missing_columns": skipped}
