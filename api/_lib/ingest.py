"""The eOrder → monday flow.

    file dropped on the eOrder column
      → webhook fires (change_specific_column_value, scoped to that column)
      → fetch the asset public_url and download immediately (it expires in 1h)
      → parse
      → find the row by opportunity_id, or create one in this month's group
      → write blanks only, rename, split multi-site to subitems
      → post an Update and set eOrder Status

Target is under 30 seconds end to end (acceptance criterion 7).
"""

import time
import traceback
from datetime import datetime

from . import columns as columns_mod
from . import config, installers, mapping
from .monday import Monday, MondayError
from .store import Store, sha256

def _parser():
    """Import the parser on first use, not at module import.

    The parser is the only thing in this app that needs openpyxl. Importing it
    at module level means one missing dependency takes down every route —
    health, the setup console, the dashboard — each returning a bare 500 with
    no body, because the crash happens before any error handler exists to
    explain it. Deferring the import keeps the rest of the app alive and makes
    the failure attributable to the one endpoint that actually needs it.
    """
    from . import eorder_parser
    return eorder_parser


MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def current_group_id(monday, board_id, when=None):
    """The group for this month, e.g. "August 2026".

    Falls back to the board's first group rather than creating one — a stray
    auto-created group on a live board is harder to notice than a row in the
    wrong place.
    """
    when = when or datetime.now()
    month, year = MONTHS[when.month - 1], when.year
    groups = monday.board_groups(board_id)

    wanted = [f"{month} {year}".lower(), f"{month[:3]} {year}".lower(), month.lower()]
    for group in groups:
        if group["title"].strip().lower() in wanted:
            return group["id"]
    for group in groups:
        title = group["title"].strip().lower()
        if month.lower() in title and str(year) in title:
            return group["id"]
    return groups[0]["id"] if groups else None


def handle_webhook(payload, monday=None, store=None):
    """Entry point for a monday file-column webhook.

    Returns a dict describing what happened — used by the HTTP layer for the
    response body and by tests as the assertion surface.
    """
    started = time.time()
    monday = monday or Monday()
    store = store or Store()

    event = payload.get("event") or {}
    item_id = event.get("pulseId")
    board_id = int(event.get("boardId") or config.ORDERS_BOARD_ID)

    if not item_id:
        return {"ok": False, "reason": "no pulseId in payload"}

    # The board this automation may touch is configuration, not payload. The
    # webhook is registered on one board, so a delivery naming another one is
    # either misconfiguration or someone probing the public endpoint — both
    # end here, before any monday call is made.
    if board_id != config.ORDERS_BOARD_ID:
        return {"ok": False,
                "reason": f"event names board {board_id}, not the orders board"}

    result = {"item_id": item_id, "board_id": board_id}

    try:
        return _run(monday, store, payload, result, started)
    except Exception as exc:  # noqa: BLE001
        # Anything unforeseen still gets reported on the row. A webhook that
        # 500s silently looks identical to one that never fired, and monday
        # leaves the run showing "In progress" forever.
        detail = f"{type(exc).__name__}: {exc}"
        _fail(monday, board_id, item_id,
              f"Something went wrong reading this eOrder.<br>{detail}")
        return {**result, "ok": False, "reason": detail}


def _run(monday, store, payload, result, started):
    event = payload.get("event") or {}
    item_id = event.get("pulseId")
    board_id = int(event.get("boardId") or config.ORDERS_BOARD_ID)
    cols = columns_mod.resolved(monday, board_id)

    file_column = cols.get("eorder_file") or event.get("columnId")
    if not file_column:
        return {**result, "ok": False,
                "reason": "no file column called 'eOrder' on this board"}

    # Ignore removals.
    #
    # monday has no "file uploaded" trigger — a file column fires the same
    # change event whether a file was added or deleted. Rather than rely on the
    # automation being configured a particular way, the removal case is caught
    # here: the payload's new value carries the files that remain, and an empty
    # list means someone deleted one. Doing nothing is right, and it must be
    # reported as success so monday does not retry it as a failure.
    value = event.get("value")
    if isinstance(value, dict) and "files" in value and not value.get("files"):
        return {**result, "ok": True, "skipped": "file removed — nothing to do"}

    try:
        assets = monday.asset_urls(item_id, file_column)
        if not assets:
            # The column is empty. Reached when a file was removed, or when the
            # event arrives after the file is already gone. Not an error, and
            # nothing on the row should be touched.
            return {**result, "ok": True,
                    "skipped": "no file on the eOrder column — nothing to do"}

        asset = assets[-1]  # most recent drop wins
        blob = monday.download(asset["public_url"])
        result["file_name"] = asset.get("name")
        file_sha = sha256(blob)

    except Exception as exc:  # noqa: BLE001 - report every failure to the user
        _fail(monday, board_id, item_id, f"Could not fetch the file: {exc}", cols)
        return {**result, "ok": False, "reason": str(exc)}

    # --- parse ---------------------------------------------------------
    try:
        import io

        parsed = _parser().parse(io.BytesIO(blob))
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}: {exc}"
        _fail(
            monday, board_id, item_id,
            f"This does not look like a Teletrac Navman eOrder.<br>{detail}", cols,
        )
        store.record_ingest(
            monday_item_id=item_id, monday_board_id=board_id,
            file_name=result.get("file_name"), file_sha256=file_sha,
            status="failed", error=detail,
            duration_ms=int((time.time() - started) * 1000),
        )
        return {**result, "ok": False, "reason": detail}

    opportunity_id = parsed.get("opportunity_id")
    result["opportunity_id"] = opportunity_id

    if not opportunity_id:
        _fail(
            monday, board_id, item_id,
            "No OPPORTUNITY ID in this file, so it cannot be matched to an "
            "order. Nothing else on the row was changed.", cols,
        )
        return {**result, "ok": False, "reason": "no opportunity_id"}

    # --- idempotency (criterion 2) -------------------------------------
    if store.already_ingested(opportunity_id, file_sha):
        return {**result, "ok": True, "skipped": "identical file already read"}

    previous = store.previous_parse(opportunity_id)
    changes = mapping.diff_against(previous, parsed) if previous else []

    # --- silent-failure guard on ACV (§4.1) ----------------------------
    order_reason = parsed.get("order_reason")
    if order_reason and not _acv_reason_known(order_reason):
        store.record_unknown_order_reason(
            order_reason, opportunity_id, result.get("file_name")
        )

    # --- installer suggestion (§6.2) -----------------------------------
    #
    # Only attempted once there are accounts to match against. With an empty
    # Installer Accounts board every real ship-to would come back "unmatched"
    # and flag Check, so an order automation running on its own would report a
    # problem on every order that ships to an installer. No accounts means the
    # allocation half simply isn't in use yet, which is not a fault.
    accounts = store.installer_accounts() if store.enabled else []
    installer_match = None
    installer_ids = None
    if accounts:
        installer_match = installers.match(
            parsed.get("installer_company"), accounts,
            customer_name=parsed.get("company"),
        )
        if installer_match["account"]:
            installer_ids = [installer_match["account"]["monday_item_id"]]

    status, warnings = mapping.validate(parsed, installer_match)

    # --- find or create the row ----------------------------------------
    target_id, created = _resolve_item(monday, board_id, item_id, opportunity_id, cols)
    result["target_item_id"] = target_id
    result["created"] = created

    existing = monday.item(target_id) or {}
    existing_text = {c["id"]: c.get("text") for c in existing.get("column_values", [])}

    proposed = mapping.to_column_values(parsed, cols, installer_item_ids=installer_ids)
    # A revised eOrder is allowed to correct fields; a first read only fills gaps.
    values = proposed if changes else mapping.merge_preserving(proposed, existing_text)

    # Align every status label to the board's real label list. One label the
    # board doesn't have would fail the whole mutation — every field lost over
    # a stripped emoji. A label that can't be aligned is dropped and reported,
    # and the rest of the order still lands.
    try:
        board_labels = columns_mod.status_labels(monday, board_id)
    except Exception:  # noqa: BLE001 - alignment is a guard, never a blocker
        board_labels = {}
    values, dropped = mapping.align_status_values(values, board_labels)
    warnings.extend(_dropped_warnings(dropped, cols))

    # --- multi-site subitems (§8.4) ------------------------------------
    #
    # Contained: subitems live on their own board with their own column IDs,
    # so a value write monday refuses must cost the subitem's values, not the
    # order. Runs before the row write so a failure here still counts toward
    # the status stamped on the row.
    sites = parsed.get("multi_site") or []
    if sites:
        try:
            result["subitems"] = _sync_subitems(monday, target_id, sites, cols)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"could not create per-site subitems: {exc}")

    # A warning collected after validate() — a dropped label, a failed subitem
    # — must still turn Read into Check. validate's own contract is
    # "STATUS_CHECK if warnings else STATUS_READ", and the board filter on
    # ⚠️ Check is the at-a-glance signal this column exists for; a clean flag
    # over a silent field loss defeats it.
    if warnings and status == mapping.STATUS_READ:
        status = mapping.STATUS_CHECK

    if cols.get("eorder_status"):
        status_value, status_dropped = mapping.align_status_values(
            {cols["eorder_status"]: mapping.v_status(status)}, board_labels
        )
        values.update(status_value)
        warnings.extend(_dropped_warnings(status_dropped, cols))

    # The rename rides in the same mutation — change_multiple_column_values
    # accepts {"name": …} (rename() is implemented with it), and a separate
    # call was one more round trip on every first read.
    new_name = mapping.item_name(parsed)
    if new_name and existing.get("name") != new_name:
        values["name"] = new_name

    fields_written = len([k for k in values if k != "name"])
    if values:
        monday.set_columns(board_id, target_id, values)

    # --- feedback -------------------------------------------------------
    monday.post_update(
        target_id,
        mapping.update_body(parsed, status, warnings, fields_written, changes),
    )

    duration_ms = int((time.time() - started) * 1000)
    store.record_ingest(
        opportunity_id=opportunity_id, monday_item_id=target_id,
        monday_board_id=board_id, file_name=result.get("file_name"),
        file_sha256=file_sha, parsed=parsed,
        status={mapping.STATUS_READ: "read",
                mapping.STATUS_CHECK: "check"}.get(status, "failed"),
        warnings=warnings, changed_fields=changes, duration_ms=duration_ms,
    )

    return {
        **result, "ok": True, "status": status, "fields_written": fields_written,
        "database": store.degraded or "ok",
        "warnings": warnings, "changes": changes, "duration_ms": duration_ms,
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _dropped_warnings(dropped, cols):
    """One warning line per status label the board refused to accept."""
    key_by_id = {v: k for k, v in cols.items() if v}
    return [
        f"label '{label}' does not exist on the "
        f"{key_by_id.get(column_id, column_id)} column "
        f"(board has: {', '.join(available) or 'none'}) — not written"
        for column_id, label, available in dropped
    ]


def _acv_reason_known(order_reason):
    return str(order_reason).strip().lower() in {
        r.strip().lower() for r in _parser().ACV_ORDER_REASONS
    }


def _resolve_item(monday, board_id, dropped_on_item_id, opportunity_id, cols):
    """Normal case: they just made a row and dropped the file on it.

    If that row is blank we use it. If the opportunity already lives on a
    different row we write there instead, so a re-drop onto a fresh row updates
    the real order rather than forking it.
    """
    column_id = cols.get("opportunity_id")
    if column_id:
        matches = monday.find_by_column_value(board_id, column_id, opportunity_id)
        for existing in matches:
            if str(existing["id"]) != str(dropped_on_item_id):
                return existing["id"], False
    return dropped_on_item_id, False


def _sync_subitems(monday, parent_id, sites, cols):
    """One subitem per delivery site, each with its own SLA clock.

    Subitems live on a separate board with its own column IDs, so the parent
    board's IDs are only valid there if the subitem board happens to mirror
    them. When monday refuses the values, the subitem is created bare rather
    than not at all — the site split is the point; the per-site fields are a
    bonus.
    """
    existing = {s["name"]: s for s in monday.subitems(parent_id)}
    written = []
    for index, site in enumerate(sites, start=1):
        name = mapping.subitem_name(site, index)
        if name in existing:
            continue
        values = mapping.subitem_values(site, cols)
        try:
            created = monday.create_subitem(parent_id, name, values)
        except MondayError:
            created = monday.create_subitem(parent_id, name, {})
        written.append({"id": created["id"], "name": name})
    return written


def _fail(monday, board_id, item_id, message, cols=None):
    """Set ❌ Failed and say why. Never touch anything else on the row (§5)."""
    try:
        column_id = (cols or config.COLUMNS).get("eorder_status")
        if not column_id:
            # The catch-all failure path arrives here with no resolved columns
            # (config alone leaves eorder_status as None), which used to mean a
            # catastrophic failure never set the status at all — the Update was
            # the only trace. Resolve from the board so ❌ Failed shows.
            try:
                column_id = columns_mod.resolved(monday, board_id).get("eorder_status")
            except Exception:  # noqa: BLE001
                column_id = None
        if column_id:
            values = {column_id: mapping.v_status(mapping.STATUS_FAILED)}
            try:
                labels = columns_mod.status_labels(monday, board_id)
                values, _ = mapping.align_status_values(values, labels)
            except Exception:  # noqa: BLE001 - write unaligned rather than not at all
                pass
            try:
                if values:
                    monday.set_columns(board_id, item_id, values)
            except Exception:  # noqa: BLE001 - the Update below must still post
                traceback.print_exc()
        monday.post_update(item_id, f"❌ <b>Could not read eOrder</b><br>{message}")
    except Exception:  # noqa: BLE001 - reporting must not raise
        traceback.print_exc()
