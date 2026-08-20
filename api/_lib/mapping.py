"""Turn a parsed eOrder into monday column values.

PARSER CONTRACT
---------------
Keys this module reads from `eorder_parser.parse()`. Confirmed against real
output for AGB Investment, Kane Civil, Southern Truck Centre, Cosmo Cranes and
Qualityvend unless marked otherwise.

    opportunity_id        str    e.g. "006VP00000agsnG"   (join key, required)
    company               str    customer legal name       (required)
    derived_item_name     str    "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551"
    order_reason          str    "New Business" | "Add-On" | ...
    order_date            str    "July 2, 2026" — NOT ISO
    platform              str
    migration_required    str
    site_contact_name     str
    site_contact_phone    str    raw, as typed
    site_contact_email    str
    site_phone_e164       str    "+61437353834"  — for SMS
    site_phone_display    str    original, for humans
    site_phone_note       str    set when normalisation did something notable
    address/suburb/state/postcode
    delivery_address      str
    installer_company     str    SHIP-TO, not necessarily the installer (§8.1)
    installer_contact     str
    installer_email       str
    ship_to_type          str    installer | third_party | customer |
                                 nothing_to_ship | multiple | unknown
    install_required      str    "Yes" | "No" | "Customer self-install"
    acv                   float|None
    acv_note              str
    dealer_commission     num
    install_value         num
    lines                 list   [{qty:int, product:str}]  — note: `lines`
    multi_site            list   [{company, contact, phone, phone_e164, email,
                                   address, notes, qty}]
    total_contract_value  float
    contract_term_months  int
    vehicles              list   always empty in practice (§8.2)
    _warnings             list[str]

Field access goes through `_get()` with fallbacks rather than direct subscript,
so a template revision that renames one key degrades to a Check flag instead of
a 500. Anything genuinely required is asserted up front in `validate()`.
"""

import re
from datetime import date, datetime

from . import config

# --------------------------------------------------------------------------
# Status values written to the eOrder Status column
# --------------------------------------------------------------------------
STATUS_READ = "✅ Read"
STATUS_CHECK = "⚠️ Check"
STATUS_FAILED = "❌ Failed"


def _get(parsed, *names, default=None):
    for name in names:
        value = parsed.get(name)
        if value not in (None, "", []):
            return value
    return default


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


# --------------------------------------------------------------------------
# monday value encoders — one per column type
# --------------------------------------------------------------------------

def v_text(value):
    return None if _is_blank(value) else str(value).strip()


def v_number(value):
    if value in (None, ""):
        return None
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return None


def v_status(label):
    return None if _is_blank(label) else {"label": str(label).strip()}


def v_email(address, label=None):
    if _is_blank(address):
        return None
    return {"email": address.strip(), "text": (label or address).strip()}


def v_phone(e164, country="AU"):
    """monday's phone column wants E.164 without the +, plus a country code.

    If normalisation failed we return None and let the caller stash the raw
    value in a text field instead — a half-valid phone number in a phone column
    is worse than none, because automations will try to send to it.
    """
    if _is_blank(e164):
        return None
    digits = re.sub(r"[^\d]", "", str(e164))
    if not digits:
        return None
    return {"phone": digits, "countryShortName": country}


def v_date(value):
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return {"date": value.date().isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    text = str(value).strip()
    # "%B %d, %Y" first: that is what the eOrder actually contains
    # ("July 2, 2026"). Everything after it is defensive — if TN changes the
    # template's date formatting, this keeps working rather than silently
    # leaving ORDER PLACED empty, which is how this was found.
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
                "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return {"date": datetime.strptime(text, fmt).date().isoformat()}
        except ValueError:
            continue
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return {"date": match.group(1)} if match else None


def v_relation(item_ids):
    if not item_ids:
        return None
    return {"item_ids": [int(i) for i in item_ids]}


# --------------------------------------------------------------------------
# Status labels must match the board's, exactly
# --------------------------------------------------------------------------
#
# monday validates every status label against the column's own label list and
# rejects the ENTIRE change_multiple_column_values mutation over one it doesn't
# know — one bad label loses every other field in the same write and the order
# lands as "❌ Failed" even though the parse was fine. That is exactly what
# happened in production: this app's status column was created with "✅ Read /
# ⚠️ Check / ❌ Failed", monday stripped the emoji during creation, and every
# write of "✅ Read" was then refused with "This status label doesn't exist,
# possible statuses are: {1: Read, 2: Check, 3: Failed}".
#
# So before writing, every proposed label is aligned to the board: an exact
# match passes through, a match up to emoji/punctuation/case is rewritten to
# the board's own spelling, and a label the column simply doesn't have is
# dropped and reported as a warning instead of failing the whole order.

def normalise_label(text):
    """Lowercase letters, digits and single spaces — nothing else.

    "✅ Read", "Read " and "read" all normalise to "read", so a label survives
    the emoji being stripped, stray whitespace, and case drift.
    """
    cleaned = re.sub(r"[^0-9a-z]+", " ", str(text).lower())
    return " ".join(cleaned.split())


def align_status_values(values, labels_by_column):
    """Fit proposed {"label": …} writes to the labels the board really has.

    Returns (aligned_values, dropped) where dropped is a list of
    (column_id, proposed_label, available_labels) for anything that could not
    be matched. Columns with no label information (board unreadable, not a
    status column) pass through untouched.
    """
    aligned, dropped = {}, []
    for column_id, value in values.items():
        available = labels_by_column.get(column_id)
        if (
            available is None
            or not isinstance(value, dict)
            or set(value) != {"label"}
        ):
            aligned[column_id] = value
            continue
        proposed = value["label"]
        if proposed in available:
            aligned[column_id] = value
            continue
        # setdefault: when two board labels normalise identically ("Read" and
        # "✅ Read" on one column), the FIRST wins — index order is the column's
        # own label order, and last-wins made the rewrite depend on dict
        # iteration order.
        by_normalised = {}
        for label in available:
            by_normalised.setdefault(normalise_label(label), label)
        wanted = normalise_label(proposed)
        # A label that normalises to nothing (pure emoji/punctuation) has no
        # text to match on — treat it as unmatched rather than pairing two
        # unrelated symbols.
        match = by_normalised.get(wanted) if wanted else None
        if match:
            aligned[column_id] = {"label": match}
        else:
            dropped.append((column_id, proposed, list(available)))
    return aligned, dropped


# --------------------------------------------------------------------------
# Derived values
# --------------------------------------------------------------------------

def units_total(parsed):
    """Sum of line-item quantities (brief §6.4).

    Excludes the non-hardware lines the ACV term calculation also excludes —
    a commissions line is not a unit anybody installs.
    """
    lines = _get(parsed, "lines", "line_items", default=[]) or []
    total = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        name = str(line.get("product") or line.get("name") or "")
        if re.search(r"internal use only|commissions? & fees|^parts$", name, re.I):
            continue
        qty = line.get("qty", line.get("quantity"))
        try:
            total += int(float(qty))
        except (TypeError, ValueError):
            continue
    return total or None


def site_address(parsed):
    """Prefer the explicit delivery address; fall back to the customer address."""
    delivery = _get(parsed, "delivery_address")
    if delivery and "multiple" not in str(delivery).lower():
        return delivery
    parts = [
        _get(parsed, "address"),
        _get(parsed, "suburb"),
        _get(parsed, "state"),
        str(_get(parsed, "postcode", default="")) or None,
    ]
    joined = " ".join(str(p).strip() for p in parts if p)
    return joined or None


def item_name(parsed):
    return _get(parsed, "derived_item_name") or _get(parsed, "company")


# --------------------------------------------------------------------------
# Validation → status + warnings
# --------------------------------------------------------------------------

CRITICAL_FIELDS = ("opportunity_id", "company")
EXPECTED_FIELDS = ("site_contact_name", "site_contact_phone")


def validate(parsed, installer_match=None):
    """Return (status, warnings) per brief §5.

    A missing installer is explicitly NOT a warning — only 1 of 5 sample orders
    named one, so it is the normal case (§8.1).

    Several checks here are also made by the parser's own `_validate()`, whose
    output arrives in `_warnings`. That overlap is deliberate — this layer must
    still warn if a parser revision drops a check — but the same fact must not
    reach the row twice, so each duplicate-prone append is guarded by a
    substring the parser's wording shares, and the final list is deduplicated.
    """
    warnings = list(parsed.get("_warnings") or [])

    def already_flagged(*needles):
        return any(
            all(needle in warning for needle in needles) for warning in warnings
        )

    missing_critical = [f for f in CRITICAL_FIELDS if _is_blank(parsed.get(f))]
    if missing_critical:
        return STATUS_FAILED, [f"missing required field: {f}" for f in missing_critical]

    ship_to = str(_get(parsed, "ship_to_type", default="")).lower()

    if ship_to == "multiple" and not already_flagged("subitem"):
        sites = _get(parsed, "multi_site", default=[]) or []
        warnings.append(
            f"ship-to is Multiple Addresses — {len(sites)} site(s) split to subitems"
        )
        # Sites-sum-vs-total check that knows when to shut up (FINALIZE
        # prompt 8): per-site quantities come from free-text notes and parse
        # to None when unreadable. The check runs ONLY when every site parsed
        # to a number — one unknown, or no sites at all, means silence, and a
        # mismatch is a ⚠️ Check with the numbers, never a failure.
        qtys = [site.get("qty") for site in sites]
        total = units_total(parsed)
        if sites and total and all(isinstance(q, (int, float)) for q in qtys):
            site_sum = int(sum(qtys))
            if site_sum != total:
                warnings.append(
                    f"site quantities add up to {site_sum} but the order has "
                    f"{total} units — check the split"
                )

    # classify_ship_to() returns one of: installer, third_party, customer,
    # nothing_to_ship, multiple, unknown. "unknown" means the ship-to cell was
    # empty, which is the case the brief wants flagged — with nothing there we
    # cannot tell whether an install is needed.
    if (
        ship_to == "unknown" or _is_blank(_get(parsed, "installer_company"))
    ) and not already_flagged("ship-to", "blank"):
        warnings.append("ship-to is blank — cannot tell whether an install is needed")

    missing_expected = [f for f in EXPECTED_FIELDS if _is_blank(parsed.get(f))]
    if missing_expected:
        warnings.append("blank in eOrder: " + ", ".join(missing_expected))

    if _get(parsed, "site_phone_note"):
        warnings.append(f"phone: {parsed['site_phone_note']}")

    if _is_blank(_get(parsed, "site_phone_e164")) and not _is_blank(
        _get(parsed, "site_contact_phone")
    ):
        warnings.append(
            f"phone would not normalise, stored raw: {parsed['site_contact_phone']}"
        )

    if installer_match is not None and installer_match.get("unmatched"):
        warnings.append(
            f"ship-to '{installer_match['unmatched']}' is not on the Installer "
            f"Accounts board — allocation left blank"
        )

    warnings = list(dict.fromkeys(warnings))
    return (STATUS_CHECK if warnings else STATUS_READ), warnings


# --------------------------------------------------------------------------
# The mapping itself
# --------------------------------------------------------------------------

def to_column_values(parsed, columns=None, installer_item_ids=None):
    """Build {column_id: value}. Columns with no configured ID are skipped."""
    cols = columns or config.COLUMNS
    out = {}

    def put(key, value):
        column_id = cols.get(key)
        if column_id and value is not None:
            out[column_id] = value

    # --- existing columns (§4) ---
    put("opportunity_id", v_text(_get(parsed, "opportunity_id")))
    put("platform", v_status(_get(parsed, "platform")))
    put("migration_required", v_status(_get(parsed, "migration_required")))
    put("order_date", v_date(_get(parsed, "order_date")))
    put("dealer_commission", v_number(_get(parsed, "dealer_commission")))
    put("install_value", v_number(_get(parsed, "install_value")))

    # ACV is only written for new-revenue order reasons. The parser returns None
    # otherwise, and None must stay empty rather than becoming a zero — a zero
    # is a real measurement that drags a new-business target average down (§4.1).
    acv = _get(parsed, "acv")
    if acv is not None:
        put("acv", v_number(acv))

    # Order Type stays untouched until the Rental/Outright rule is confirmed.
    if config.WRITE_ORDER_TYPE:
        put("order_type", v_status(_get(parsed, "order_reason")))

    # --- new columns (§3.1) ---
    put("site_contact", v_text(_get(parsed, "site_contact_name")))
    put("site_phone", v_phone(_get(parsed, "site_phone_e164")))
    put("site_email", v_email(_get(parsed, "site_contact_email")))
    put("site_address", v_text(site_address(parsed)))
    put("install_required", v_status(_get(parsed, "install_required")))
    put("units_total", v_number(units_total(parsed)))
    put("installer_email", v_email(_get(parsed, "installer_email")))
    put("installer", v_relation(installer_item_ids))

    return out


def install_sites(parsed):
    """The uniform install-site list for an order (Prompt 1 of the finalisation
    pack): one entry per site that needs an install, whatever the order shape.

    - Multiple Addresses order → its multi_site rows, unchanged (their install
      items inherit the order's dispatch date from the parent row in the
      portal's _shape fallback).
    - Single-site order with Install Required = Yes → exactly one entry, built
      from the main delivery block, carrying the same fields a multi-site row
      does (contact, phone, email, address, units, dispatch date).
    - Install Required = No or Customer self-install → none.

    Every install item the ingest creates comes from this list, so the portal,
    the SLA clock and the SMS trigger see one shape — no single-site special
    case downstream.
    """
    if str(_get(parsed, "install_required") or "").strip().lower() != "yes":
        return []
    sites = _get(parsed, "multi_site", default=[]) or []
    if sites:
        return list(sites)
    return [{
        # Ship-to company, matching what a multi-site row carries per site.
        "company": _get(parsed, "installer_company") or _get(parsed, "company"),
        "contact": _get(parsed, "site_contact_name"),
        "phone": _get(parsed, "site_phone_display") or _get(parsed, "site_contact_phone"),
        "phone_e164": _get(parsed, "site_phone_e164"),
        "email": _get(parsed, "site_contact_email"),
        "address": site_address(parsed),
        "qty": units_total(parsed),
        "dispatch": _get(parsed, "order_date"),
        "notes": None,
    }]


def subitem_values(site, columns=None):
    """Column values for one install item — a site of a Multiple Addresses
    order (§8.4), or the single site of an ordinary install order (Prompt 1)."""
    cols = columns or config.COLUMNS
    out = {}

    def put(key, value):
        column_id = cols.get(key)
        if column_id and value is not None:
            out[column_id] = value

    put("site_contact", v_text(site.get("contact") or site.get("contact_name")))
    put("site_phone", v_phone(site.get("phone_e164") or site.get("phone")))
    put("site_email", v_email(site.get("email")))
    put("site_address", v_text(site.get("address")))
    put("units_total", v_number(site.get("qty")))
    put("order_date", v_date(site.get("dispatch")))
    return out


def subitem_name(site, index):
    label = (site.get("company") or site.get("address")
             or site.get("contact") or f"Site {index}")
    qty = site.get("qty")
    return f"{label} — {qty} units" if qty else str(label)


# --------------------------------------------------------------------------
# Never clobber human edits
# --------------------------------------------------------------------------

def merge_preserving(proposed, existing_text):
    """Drop any proposed value where monday already holds something.

    Brief §5: never overwrite a non-empty monday field with a blank from the
    eOrder. This goes further — it will not overwrite a non-empty field at all
    on the normal path, because a person may have corrected it by hand. Revised
    eOrders take the other path (`force`) and are reported in the Update.
    """
    return {
        column_id: value
        for column_id, value in proposed.items()
        if _is_blank(existing_text.get(column_id))
    }


def diff_against(previous, parsed, keys=None):
    """Human-readable list of what changed between two parses of one order."""
    if not previous:
        return []
    keys = keys or (
        "derived_item_name", "order_reason", "install_required", "acv",
        "install_value", "dealer_commission", "site_contact_name",
        "site_contact_phone", "installer_company", "platform",
    )
    changes = []
    for key in keys:
        before, after = previous.get(key), parsed.get(key)
        if before != after:
            changes.append(f"{key}: {before or '—'} → {after or '—'}")
    before_units = units_total(previous)
    after_units = units_total(parsed)
    if before_units != after_units:
        changes.append(f"units: {before_units or 0} → {after_units or 0}")
    return changes


# --------------------------------------------------------------------------
# The monday Update — the user's only feedback (§3.4)
# --------------------------------------------------------------------------

def update_body(parsed, status, warnings, field_count, changes=None):
    lines = []

    if status == STATUS_READ:
        lines.append(f"✅ <b>Read from eOrder</b> — {field_count} fields populated")
    elif status == STATUS_CHECK:
        lines.append(
            f"⚠️ <b>Read from eOrder</b> — {field_count} fields populated, "
            f"{len(warnings)} to check"
        )
    else:
        lines.append("❌ <b>Could not read eOrder</b>")

    installer = _get(parsed, "installer_company")
    contact = _get(parsed, "site_contact_name")
    phone = _get(parsed, "site_phone_display") or _get(parsed, "site_contact_phone")

    detail = []
    if installer:
        contact_name = _get(parsed, "installer_contact")
        detail.append(
            f"Installer: {contact_name} ({installer})" if contact_name
            else f"Ship to: {installer}"
        )
    if contact:
        detail.append(f"Site: {contact}" + (f" {phone}" if phone else ""))
    if detail:
        lines.append(" · ".join(detail))

    lines_summary = _summarise_lines(parsed)
    install_value = _get(parsed, "install_value")
    tail = []
    if lines_summary:
        tail.append(lines_summary)
    if install_value:
        tail.append(f"Install value ${float(install_value):,.0f}")
    acv = _get(parsed, "acv")
    if acv:
        tail.append(f"ACV ${float(acv):,.0f}")
    if tail:
        lines.append(" · ".join(tail))

    if changes:
        lines.append("")
        lines.append("<b>Changed since the previous eOrder</b>")
        lines.extend(f"• {c}" for c in changes)

    if warnings:
        lines.append("")
        lines.append("<b>Check</b>")
        lines.extend(f"• {w}" for w in warnings)

    return "<br>".join(lines)


def _summarise_lines(parsed):
    """"18 × RE400, 22 × VT202, 4 × AT551" for the monday Update.

    Taken from derived_item_name, which the parser has already built using its
    own product-code extraction. Re-deriving it here from the raw line text
    would produce "18 × RE 400 with TN360" and drift from the item name on the
    very same row.
    """
    name = _get(parsed, "derived_item_name")
    if name and "=" in name:
        return name.split("=", 1)[1].strip().replace(" x ", " × ")

    lines = _get(parsed, "lines", "line_items", default=[]) or []
    parts = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        qty = line.get("qty", line.get("quantity"))
        product = line.get("product") or line.get("name")
        if qty and product:
            parts.append(f"{int(float(qty))} × {product}")
    return " · ".join(parts[:6])
