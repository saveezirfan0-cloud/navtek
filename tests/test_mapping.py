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
    # Customer block (General Information) vs delivery block: the trucks live
    # in Botany; the hardware ships to Paul Redmond's workshop in Nowra.
    "address": "9-13 Underwood Avenue",
    "suburb": "Botany",
    "state": "New South Wales",
    "postcode": "2019",
    "delivery_address": "39 Jindalee Cres, Nowra NSW 2541",
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

def test_phone_keeps_the_plus_for_tap_to_dial():
    # 61437353834 breaks tap-to-dial and SMS routing; +61437353834 works.
    assert mapping.v_phone("+61437353834") == {
        "phone": "+61437353834", "countryShortName": "AU"
    }
    assert mapping.v_phone("0437 353 834") == {
        "phone": "+0437353834", "countryShortName": "AU"
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
    assert mapping.v_number(0) == "0"
    assert mapping.v_number("") is None


def test_whole_numbers_write_whole():
    # "44.0" units on a board reads as a data error to the people using it.
    assert mapping.v_number(44) == "44"
    assert mapping.v_number("44.0") == "44"
    assert mapping.v_number(7740.5) == "7740.5"   # real decimals survive


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
    assert values["numeric_mm0asnac"] == "18144"
    assert values["numbers_units"] == "44"
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


# -- the site address is the CUSTOMER's, never the ship-to ------------------

def test_site_address_is_the_customer_not_the_delivery_address():
    """The first live drop sent installers to 39 Jindalee Cres Nowra — Paul
    Redmond's workshop, where the hardware ships. The trucks are in Botany."""
    assert mapping.site_address(KANE) == "9-13 Underwood Avenue, Botany NSW 2019"


def test_nothing_to_ship_never_becomes_an_address():
    agb = {**KANE, "address": "15 Lockwood Street", "suburb": "Merrylands",
           "state": "New South Wales", "postcode": "2160",
           "delivery_address": "Nothing to Ship"}
    assert mapping.site_address(agb) == "15 Lockwood Street, Merrylands NSW 2160"


def test_a_missing_customer_block_yields_no_address_not_the_ship_to():
    bare = {**KANE, "address": None, "suburb": None, "state": None,
            "postcode": None}
    assert mapping.site_address(bare) is None


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


def test_a_warning_the_parser_already_made_is_not_repeated():
    # The parser's own _validate() puts "phone: <note>" into _warnings, and
    # validate() derives the same warning from site_phone_note. The Cosmo
    # Cranes row showed it twice — in the monday Update AND the dashboard.
    cosmo = {
        **KANE,
        "site_phone_note": "vanity number converted: 1300 1 COSMO",
        "_warnings": ["phone: vanity number converted: 1300 1 COSMO"],
    }
    status, warnings = mapping.validate(cosmo)
    assert status == mapping.STATUS_CHECK
    assert warnings.count("phone: vanity number converted: 1300 1 COSMO") == 1


def test_ship_to_blank_is_flagged_once_despite_different_wordings():
    # Parser and mapping word this check differently, so exact dedupe alone
    # can't catch it — the guard has to recognise the parser's version.
    blank = {
        **KANE, "installer_company": None, "ship_to_type": "unknown",
        "_warnings": ["ship-to company blank — cannot tell whether an install is needed"],
    }
    status, warnings = mapping.validate(blank)
    assert status == mapping.STATUS_CHECK
    assert sum("ship-to" in w and "blank" in w for w in warnings) == 1


def test_install_sites_is_per_delivery_site_never_per_unit():
    # Single-site install order → NO subitems; the order row is the job.
    assert mapping.install_sites(KANE) == []

    # Multi-site order → its site rows, untouched.
    multi = {**KANE, "ship_to_type": "multiple",
             "multi_site": [{"company": "A", "qty": 4}, {"company": "B", "qty": 8}]}
    assert mapping.install_sites(multi) == multi["multi_site"]

    # No install → no install items, whatever the wording.
    assert mapping.install_sites({**KANE, "install_required": "No"}) == []
    assert mapping.install_sites({**KANE, "install_required": "Customer self-install"}) == []
    assert mapping.install_sites({**KANE, "install_required": None}) == []


def test_portal_yields_one_job_per_install_item_uniformly():
    class StubMonday:
        def __init__(self, subs):
            self._subs = subs

        def subitems(self, item_id):
            return self._subs

    order = {"id": "9", "name": "KANE CIVIL = 18 x RE400", "column_values": []}

    # No subitems (pre-Prompt-1 order): the row stands in as the install item.
    jobs = portal.install_items(StubMonday([]), order, {})
    assert len(jobs) == 1
    assert jobs[0]["install_id"] == "9" and jobs[0]["subitem_id"] is None

    # With subitems: one job per site, none synthesized on top — and a bare
    # subitem's unit count is recovered from the name the ingest gave it.
    subs = [{"id": "91", "name": "FFT Technology — 8 units", "column_values": []},
            {"id": "92", "name": "GPS Tech — 7 units", "column_values": []}]
    jobs = portal.install_items(StubMonday(subs), order, {})
    assert [j["install_id"] for j in jobs] == ["91", "92"]
    assert [j["units_total"] for j in jobs] == [8, 7]
    assert all(j["item_id"] == "9" for j in jobs)   # write-backs target the order


def test_multi_site_split_is_flagged_once_when_the_parser_already_said_so():
    multi = {
        **KANE, "ship_to_type": "multiple",
        "multi_site": [{"qty": 4}, {"qty": 8}],
        "_warnings": ["multi-site order: 2 delivery sites — "
                      "create one subitem per site, each with its own SLA clock"],
    }
    status, warnings = mapping.validate(multi)
    assert status == mapping.STATUS_CHECK
    assert sum("subitem" in w for w in warnings) == 1


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


# -- status labels aligned to the board (incident of 19 Aug 2026) -----------

def test_align_translates_emoji_labels_onto_a_plain_board():
    values = {
        "status_eorder": {"label": "✅ Read"},
        "status_install": {"label": "Yes"},
        "text_site": "Gerard Cahalan",
    }
    labels = {"status_eorder": ["Read", "Check", "Failed"],
              "status_install": ["Yes", "No", "Customer self-install"]}
    aligned, dropped = mapping.align_status_values(values, labels)
    assert aligned["status_eorder"] == {"label": "Read"}
    assert aligned["status_install"] == {"label": "Yes"}   # exact match kept
    assert aligned["text_site"] == "Gerard Cahalan"        # non-status untouched
    assert dropped == []


def test_align_keeps_an_exact_emoji_match_when_the_board_has_it():
    aligned, dropped = mapping.align_status_values(
        {"s": {"label": "✅ Read"}}, {"s": ["✅ Read", "⚠️ Check", "❌ Failed"]})
    assert aligned == {"s": {"label": "✅ Read"}}
    assert dropped == []


def test_align_drops_a_label_the_board_does_not_have():
    aligned, dropped = mapping.align_status_values(
        {"s": {"label": "TN360"}}, {"s": ["Navman", "Teletrac"]})
    assert aligned == {}
    assert dropped == [("s", "TN360", ["Navman", "Teletrac"])]


def test_align_passes_through_columns_it_has_no_labels_for():
    # Board unreadable → no label info → write what we have (old behaviour).
    aligned, dropped = mapping.align_status_values({"s": {"label": "X"}}, {})
    assert aligned == {"s": {"label": "X"}}
    assert dropped == []


# -- Supabase auth headers (regression: sb_secret keys are not JWTs) --------

def test_new_secret_keys_are_not_sent_as_bearer_tokens():
    """An sb_secret_ key sent as Authorization: Bearer gets the whole request
    rejected as a malformed JWT, even with a valid apikey header alongside.
    This is the bug that made correct navtek credentials look wrong."""
    from _lib.store import Store
    headers = Store("https://x.supabase.co", "sb_secret_abc")._headers()
    assert headers["apikey"] == "sb_secret_abc"
    assert "Authorization" not in headers


def test_legacy_jwt_keys_keep_the_bearer_header():
    from _lib.store import Store
    headers = Store("https://x.supabase.co", "eyJhbGciOi.payload.sig")._headers()
    assert headers["Authorization"] == "Bearer eyJhbGciOi.payload.sig"


# -- Supabase key diagnostics ------------------------------------------------

def _legacy_jwt(ref="abcdefgh", role="service_role", signature="s" * 43):
    """A structurally real legacy Supabase key: JWT with ref and role."""
    import base64
    import json as _json

    def b64(obj):
        return base64.urlsafe_b64encode(_json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'ref': ref, 'role': role})}.{signature}"


def test_a_service_role_key_with_a_cut_signature_is_named_truncated():
    """The payload of a truncated key still decodes cleanly — role and project
    both check out — so without looking at the signature the diagnosis reads
    'correct type, same project, rejected', which points everywhere except at
    the paste. The signature length is the tell."""
    from _lib.store import Store
    kind = Store("https://abcdefgh.supabase.co", _legacy_jwt(signature="s" * 20)).key_kind()
    assert "cut short" in kind or "truncated" in kind.lower()


def test_an_intact_service_role_key_is_the_correct_type():
    from _lib.store import Store
    kind = Store("https://abcdefgh.supabase.co", _legacy_jwt()).key_kind()
    assert kind == "legacy service_role key (correct type)"


def test_ping_surfaces_supabases_own_error_message():
    """Supabase's 401 body says exactly why a key was refused. Discarding it
    left only 'rejected', which cannot distinguish a truncated paste from
    disabled legacy keys from a rotated secret."""
    from _lib.store import Store

    class Refusal:
        status_code = 401
        text = '{"message":"Legacy API keys are disabled"}'
        content = text.encode()

        def json(self):
            return {"message": "Legacy API keys are disabled"}

    class Client:
        def get(self, *args, **kwargs):
            return Refusal()

    store = Store("https://abcdefgh.supabase.co", _legacy_jwt())
    store._client = Client()
    probe = store._ping_once()
    assert probe["state"] == "rejected"
    assert probe["supabase_said"] == "Legacy API keys are disabled"
    # And the detail turns that message into the actual fix.
    assert "sb_secret_" in probe["detail"]
    assert "legacy" in probe["detail"].lower()


def test_permission_denied_is_named_a_grants_problem_not_a_key_problem():
    """Production, 19 Aug 2026: a valid service_role key from the confirmed
    project got 'permission denied for table eorder_ingests' — Postgres
    refusing the role, after auth succeeded. The advice 'copy a fresh key'
    is wrong for this case and cost a round of key rotation that changed
    nothing. It must be told apart from a rejected key."""
    from _lib.store import Store

    class Refusal:
        status_code = 403
        text = ('{"code":"42501","details":null,"hint":null,'
                '"message":"permission denied for table eorder_ingests"}')
        content = text.encode()

        def json(self):
            return {"code": "42501", "details": None, "hint": None,
                    "message": "permission denied for table eorder_ingests"}

    class Client:
        def get(self, *args, **kwargs):
            return Refusal()

    store = Store("https://abcdefgh.supabase.co", _legacy_jwt())
    store._client = Client()
    probe = store._ping_once()
    assert probe["state"] == "no_grants"
    assert "0003_grants.sql" in probe["detail"]
    assert "key is fine" in probe["detail"].lower()


def test_every_read_fails_over_to_the_working_credential_pair(monkeypatch):
    """Only ping() used to try the other candidate pairs, so /health could
    elect the working pair while a cold function instance served logins with
    the dead first pair — intermittent 401s that look like flaky passwords
    while the dashboard says the database is ready."""
    from _lib.store import Store

    monkeypatch.setenv("SUPABASE_URL", "https://abcdefgh.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", _legacy_jwt())      # dead pair
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_good")    # live pair
    monkeypatch.setattr(Store, "_working", None)

    class Response:
        def __init__(self, code, body):
            self.status_code, self._body = code, body
            import json as _json
            self.text = _json.dumps(body)
            self.content = self.text.encode()

        def json(self):
            return self._body

    class Client:
        def get(self, url, params=None, headers=None):
            if headers["apikey"] == "sb_secret_good":
                return Response(200, [{"id": "1"}])
            return Response(401, {"message": "Invalid API key"})

    store = Store()
    store._client = Client()
    assert store.source == "SUPABASE_SERVICE_KEY"        # starts on the dead pair
    rows = store._get("eorder_ingests", {"select": "id"})
    assert rows == [{"id": "1"}]                          # failed over and retried
    assert store.source == "SUPABASE_SECRET_KEY"


def test_supabase_credentials_survive_pasted_whitespace_and_quotes(monkeypatch):
    from _lib import config as config_mod
    monkeypatch.setenv("SUPABASE_URL", " https://abcdefgh.supabase.co\n")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "'sb_secret_real_value' ")
    candidates = config_mod.supabase_candidates()
    assert candidates[0]["url"] == "https://abcdefgh.supabase.co"
    assert candidates[0]["key"] == "sb_secret_real_value"


# -- multi-site quantity check that knows when to shut up (prompt 8) ---------

def _multi(sites):
    return {**KANE, "ship_to_type": "multiple", "multi_site": sites}


def test_matching_site_quantities_stay_silent():
    # KANE's lines sum to 44 (commissions line excluded).
    status, warnings = mapping.validate(_multi([{"qty": 40}, {"qty": 4}]))
    assert not any("add up to" in w for w in warnings)


def test_mismatched_site_quantities_flag_check_with_the_numbers():
    status, warnings = mapping.validate(_multi([{"qty": 40}, {"qty": 3}]))
    assert status == mapping.STATUS_CHECK
    assert any("43" in w and "44" in w for w in warnings), warnings


def test_one_unparseable_site_silences_the_check():
    # site_qty() returns None — not 0 — when the free-text notes don't parse.
    status, warnings = mapping.validate(_multi([{"qty": 40}, {"qty": None}]))
    assert not any("add up to" in w for w in warnings)


def test_single_site_orders_never_run_the_check():
    status, warnings = mapping.validate(dict(KANE))
    assert not any("add up to" in w for w in warnings)


def test_customer_self_install_survives_alignment_exactly():
    aligned, dropped = mapping.align_status_values(
        {"s": {"label": "Customer self-install"}},
        {"s": ["Yes", "No", "Customer self-install"]})
    assert aligned == {"s": {"label": "Customer self-install"}}
    assert dropped == []


def test_a_two_part_jwt_is_named_signature_missing():
    from _lib.store import Store
    kind = Store("https://x.supabase.co", "eyJhbGciOi.payloadonly").key_kind()
    assert "signature missing" in kind


def test_diag_agrees_with_the_app_about_what_is_set():
    import importlib.util
    import os as _os
    spec = importlib.util.spec_from_file_location(
        "navtek_diag",
        _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      "api", "diag.py"))
    diag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diag)
    assert diag._actually_set("sb_secret_x") is True
    assert diag._actually_set('""') is False      # quoted-empty paste
    assert diag._actually_set("  ") is False      # whitespace-only paste
    assert diag._actually_set(None) is False
