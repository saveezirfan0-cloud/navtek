"""Tests for everything between the parser and monday.

These deliberately do not need the parser or a network — they run against a
fixture dict shaped like parser output, so the mapping layer can be proven
before the parser is dropped in and without burning monday API calls.

The Kane Civil fixture below is RECONSTRUCTED from parser output captured in
Aug 2026 plus the validated tables in the brief. It is right about the fields it
asserts; it is not a complete parser dump. Once the real parser is in place,
regenerate it with:

    python -c "from _lib.eorder_parser import parse; import json; \
        print(json.dumps(parse('samples/KANE_CIVIL_PTY_LTD__2_07_2026__EOrder.xlsx')))"
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import installers, mapping, portal  # noqa: E402

KANE = {
    "opportunity_id": "006VP00000agsnG",
    "company": "KANE CIVIL PTY LTD",
    "derived_item_name": "KANE CIVIL = 18 x RE400, 22 x VT202, 4 x AT551",
    "order_reason": "New Business",
    "order_date": "July 2, 2026",   # the eOrder's actual format
    "site_contact_name": "Gerard Cahalan",
    "site_contact_phone": "0437353834",
    "site_phone_e164": "+61437353834",
    "site_phone_display": "0437 353 834",
    "site_contact_email": "gerard@kanecivil.com.au",
    "installer_company": "FFT TECHNOLOGY",
    "installer_contact": "Paul Redmond",
    "installer_email": "paul@ffttechnology.com.au",
    "ship_to_type": "installer",
    "install_required": "Yes",
    "acv": 18144.0,
    "install_value": 8000,
    # Real shape, taken from a parser run against the Kane Civil eOrder:
    # the key is `lines`, each entry is {qty, product}, and there is no `code`.
    "lines": [
        {"qty": 18, "product": "RE 400 with TN360"},
        {"qty": 22, "product": "VT202 VLU with TN360"},
        {"qty": 4, "product": "AT551 Asset Tracker Service"},
        {"qty": 1, "product": "Internal Use Only - Commissions & Fees"},
    ],
    "multi_site": [],
    "vehicles": [],
    "_warnings": [],
}

COLUMNS = {
    "opportunity_id": "order__",
    "install_value": "numeric",
    "acv": "numeric_mm0asnac",
    "order_date": "date3",
    "site_contact": "text_site",
    "site_phone": "phone_site",
    "site_email": "email_site",
    "site_address": "text_addr",
    "install_required": "status_install",
    "units_total": "numbers_units",
    "installer": "board_installer",
    "installer_email": "email_installer",
    "eorder_status": "status_eorder",
}


# -- encoders --------------------------------------------------------------

def test_phone_strips_to_digits_for_monday():
    assert mapping.v_phone("+61437353834") == {
        "phone": "61437353834", "countryShortName": "AU"
    }


def test_phone_refuses_junk_rather_than_emitting_broken_value():
    assert mapping.v_phone("") is None
    assert mapping.v_phone("n/a") is None


def test_date_reads_the_format_the_eorder_actually_uses():
    # Regression: the eOrder writes "July 2, 2026". An earlier version of this
    # only handled ISO and slash formats, so ORDER PLACED was silently never
    # written — no error, just a permanently empty column.
    assert mapping.v_date("July 2, 2026") == {"date": "2026-07-02"}
    assert mapping.v_date("July 27, 2026") == {"date": "2026-07-27"}
    assert mapping.v_date("Jul 2, 2026") == {"date": "2026-07-02"}


def test_date_still_accepts_other_orderings():
    assert mapping.v_date("02/07/2026") == {"date": "2026-07-02"}
    assert mapping.v_date("2026-07-02") == {"date": "2026-07-02"}


def test_number_zero_survives_but_blank_does_not():
    assert mapping.v_number(0) == "0.0"
    assert mapping.v_number("") is None


# -- derived values --------------------------------------------------------

def test_units_total_excludes_the_commissions_line():
    # 18 + 22 + 4 = 44. The Internal Use Only line is not a unit anyone fits.
    assert mapping.units_total(KANE) == 44


def test_units_total_is_none_not_zero_when_there_are_no_lines():
    assert mapping.units_total({"lines": []}) is None


# -- the mapping -----------------------------------------------------------

def test_maps_the_fields_the_brief_lists():
    values = mapping.to_column_values(KANE, COLUMNS, installer_item_ids=[123])
    assert values["order__"] == "006VP00000agsnG"
    assert values["numeric_mm0asnac"] == "18144.0"
    assert values["numbers_units"] == "44.0"
    assert values["status_install"] == {"label": "Yes"}
    assert values["board_installer"] == {"item_ids": [123]}
    assert values["text_site"] == "Gerard Cahalan"


def test_acv_stays_empty_on_a_renewal_rather_than_becoming_zero():
    renewal = {**KANE, "order_reason": "Service Only Renewal", "acv": None}
    values = mapping.to_column_values(renewal, COLUMNS)
    assert "numeric_mm0asnac" not in values


def test_order_type_is_not_written_while_the_rule_is_unresolved():
    values = mapping.to_column_values(KANE, {**COLUMNS, "order_type": "order_type9"})
    assert "order_type9" not in values


def test_existing_monday_values_are_never_clobbered():
    proposed = {"text_site": "Gerard Cahalan", "numeric": "8000"}
    existing = {"text_site": "Someone Else", "numeric": ""}
    kept = mapping.merge_preserving(proposed, existing)
    assert kept == {"numeric": "8000"}


# -- validation ------------------------------------------------------------

def test_a_clean_order_reads_clean():
    status, warnings = mapping.validate(KANE)
    assert status == mapping.STATUS_READ
    assert warnings == []


def test_a_missing_installer_is_not_an_error():
    # Only 1 of 5 sample orders named one — this is the normal case (§8.1).
    # "nothing_to_ship" is the parser's actual value; "nothing" was a guess.
    no_installer = {**KANE, "installer_company": "Nothing to Ship",
                    "ship_to_type": "nothing_to_ship"}
    status, warnings = mapping.validate(no_installer)
    assert status == mapping.STATUS_READ, warnings


def test_an_empty_ship_to_is_flagged():
    blank = {**KANE, "installer_company": None, "ship_to_type": "unknown"}
    status, warnings = mapping.validate(blank)
    assert status == mapping.STATUS_CHECK
    assert any("ship-to is blank" in w for w in warnings)


def test_update_line_summary_uses_the_parser_product_codes():
    body = mapping.update_body(KANE, mapping.STATUS_READ, [], 14)
    assert "18 × RE400" in body and "4 × AT551" in body
    assert "with TN360" not in body


def test_missing_opportunity_id_fails_hard():
    status, warnings = mapping.validate({**KANE, "opportunity_id": None})
    assert status == mapping.STATUS_FAILED
    assert "opportunity_id" in warnings[0]


def test_multiple_addresses_flags_check_and_counts_sites():
    multi = {**KANE, "ship_to_type": "multiple",
             "multi_site": [{"qty": 4}, {"qty": 8}, {"qty": 2}, {"qty": 1}]}
    status, warnings = mapping.validate(multi)
    assert status == mapping.STATUS_CHECK
    assert "4 site(s)" in warnings[0]


def test_vanity_phone_conversion_is_surfaced_not_swallowed():
    cosmo = {**KANE, "site_phone_note": "vanity number converted: 1300 1 COSMO"}
    status, warnings = mapping.validate(cosmo)
    assert status == mapping.STATUS_CHECK
    assert any("COSMO" in w for w in warnings)


# -- installer matching ----------------------------------------------------

ACCOUNTS = [
    {"account_name": "Paul Redmond / FFT Technology", "monday_item_id": 11},
    {"account_name": "Dan Wells", "monday_item_id": 22},
    {"account_name": "GPS Tech", "monday_item_id": 33},
]


def test_matches_an_installer_through_entity_suffixes():
    result = installers.match("FFT TECHNOLOGY PTY LTD", ACCOUNTS)
    assert result["account"]["monday_item_id"] == 11


def test_sentinels_are_not_installers():
    for sentinel in ("Nothing to Ship", "Multiple Addresses"):
        result = installers.match(sentinel, ACCOUNTS)
        assert result["account"] is None
        assert result["unmatched"] is None


def test_shipping_to_the_customer_is_not_an_unmatched_installer():
    result = installers.match("Kane Civil Pty Ltd", ACCOUNTS,
                              customer_name="KANE CIVIL PTY LTD")
    assert result["account"] is None
    assert result["unmatched"] is None


def test_an_unknown_company_is_reported_rather_than_guessed():
    result = installers.match("Bunbury Auto Electrics", ACCOUNTS)
    assert result["account"] is None
    assert result["unmatched"] == "Bunbury Auto Electrics"


# -- portal ----------------------------------------------------------------

def test_progress_counter_hidden_on_single_unit_jobs():
    # A counter on a one-unit job is noise (§6.4).
    assert portal._shape({"id": "1", "name": "X", "column_values": []})["show_counter"] is False


def test_business_days_skip_weekends():
    from datetime import date, timedelta
    monday_last_week = date.today() - timedelta(days=7)
    assert portal.business_days_since(monday_last_week.isoformat()) == 5


# -- the update body -------------------------------------------------------

def test_update_names_the_installer_and_the_site_contact():
    body = mapping.update_body(KANE, mapping.STATUS_READ, [], 14)
    assert "Paul Redmond (FFT TECHNOLOGY)" in body
    assert "Gerard Cahalan" in body
    assert "0437 353 834" in body
    assert "14 fields populated" in body


def test_update_lists_what_changed_on_a_revision():
    revised = {**KANE, "lines": [{"qty": 20, "product": "RE 400 with TN360"}]}
    changes = mapping.diff_against(KANE, revised)
    body = mapping.update_body(revised, mapping.STATUS_READ, [], 14, changes)
    assert "Changed since the previous eOrder" in body
    assert any("units" in c for c in changes)
