"""Installer onboarding, driven by the board instead of the setup page.

The manual path works — Setup step A issues a token, step B copies the board
into Supabase, and the link is read off the Installers page — but it depends
on someone remembering three steps every time an account is added, and the
gap shows: an account with a token in monday is still invisible to the
portal until somebody presses Sync. This module is the webhook side of the
same flow. monday reports that the Installer Accounts board changed, and the
app finishes the job on its own:

  * a brand-new row is given a portal token and its Active tick;
  * the whole board is re-synced into Supabase (the same sync as step B);
  * the coordinator is emailed their magic link, exactly once per
    (token, address) pair — so a reissued token or a corrected address sends
    a fresh link, and a webhook retry sends nothing.

Loop safety: writing the token back to monday triggers this webhook again.
That second delivery finds the token present and writes nothing, the sync is
idempotent, and the email is claimed in the notifications ledger before
sending — the flow converges instead of ping-ponging.
"""

import hashlib
import secrets

from . import bootstrap, config, emailer

# monday delivers a created row as create_pulse (the registration event is
# called create_item — same thing, two vintages of naming).
_CREATE_EVENTS = ("create_pulse", "create_item")


def handle_account_event(monday, store, payload):
    """One delivery from the Installer Accounts board, whatever it was.

    Deliberately coarse: rather than dispatching on which column changed,
    every delivery converges the same three steps (token, sync, email), each
    of which is a no-op when already done. That makes retries, our own
    write-echoes and hand edits all safe, and the board stays the single
    source of truth.
    """
    event = payload.get("event") or {}
    item_id = event.get("pulseId")
    if not item_id:
        return {"ok": False, "reason": "no pulseId in payload"}
    board_id = event.get("boardId") or config.INSTALLERS_BOARD_ID
    if not board_id:
        return {"ok": False, "reason": "no installers board id"}

    item = monday.item(item_id)
    if not item:
        return {"ok": True, "reason": "item no longer exists"}

    columns = {c["title"].strip().lower(): c["id"]
               for c in monday.board_columns(board_id)}
    values = {c["id"]: c.get("text") for c in item["column_values"]}

    def text(title):
        column_id = columns.get(title)
        return (values.get(column_id) or "").strip() if column_id else ""

    result = {"ok": True, "item_id": int(item_id), "account": item["name"]}

    # --- 1. a row without a token gets one --------------------------------
    writes = {}
    token = text("portal token")
    if not token and columns.get("portal token"):
        token = secrets.token_urlsafe(32)
        writes[columns["portal token"]] = token
        result["token_issued"] = True

    # Active defaults to ticked ONLY on a brand-new row. Re-ticking it on a
    # change event would undo the one gesture that deactivates an account.
    active = bool(text("active"))
    if (not active and event.get("type") in _CREATE_EVENTS
            and columns.get("active")):
        writes[columns["active"]] = {"checked": "true"}
        active = True
        result["activated"] = True

    if writes:
        monday.set_columns(board_id, item_id, writes)

    # --- 2. mirror the board into the database ----------------------------
    if not store.enabled:
        return {**result, "synced": False,
                "reason": "Supabase is not configured — nothing to sync into"}

    sync = bootstrap.sync_installers(monday, store, board_id)
    result["synced"] = sync["synced"]
    if sync["skipped_no_token"]:
        result["skipped_no_token"] = sync["skipped_no_token"]

    if result.get("token_issued") or result.get("activated"):
        store.record_event(int(item_id), "installer_onboarded", payload={
            "account": item["name"],
            "token_issued": bool(result.get("token_issued")),
            "activated": bool(result.get("activated")),
        })

    # --- 3. email the coordinator their link ------------------------------
    result["email"] = email_portal_link(store, item_id, {
        "account_name": item["name"],
        "coordinator_name": text("coordinator name"),
        "coordinator_email": text("coordinator email"),
        "portal_token": token,
        "active": active,
    })
    return result


def email_portal_link(store, item_id, account):
    """Email the magic link to the coordinator — once per (token, address).

    The claim key hashes the token, so reissuing a token (the documented way
    to cut off and re-grant access) emails the NEW link on its own, while
    monday's retry storms and our own write-echoes email nothing. With no
    email provider configured the send is deferred rather than claimed —
    otherwise the one-shot claim would be burnt on a log line, and the real
    email could never follow once a provider was set up.
    """
    token = account.get("portal_token")
    if not token:
        return {"sent": False, "reason": "no portal token on the row yet"}
    if not account.get("active"):
        return {"sent": False, "reason": "account is not active"}
    to = (account.get("coordinator_email") or "").strip().lower()
    if not to or "@" not in to:
        return {"sent": False,
                "reason": "no coordinator email on the row — add one and the "
                          "link sends itself"}
    base = config.portal_base_url()
    if not base:
        return {"sent": False,
                "reason": "APP_URL is not set, so there is no link to send"}
    link = f"{base}/j/{token}"
    if emailer.provider() == "log":
        print(f"[email:log] would send {account['account_name']} their portal "
              f"link at {to}")
        return {"sent": False, "deferred": True,
                "reason": "no email provider configured (RESEND_API_KEY or "
                          "SMTP_HOST) — copy the link from the Installers "
                          "page instead"}

    finger = hashlib.sha256(token.encode()).hexdigest()[:16]
    key = f"portal_link:{finger}:{to}"
    if not store.claim_notification(int(item_id), key, payload={"to": to}):
        return {"sent": False, "reason": "this link was already emailed to "
                                         "this address"}

    subject, html, text = _compose(account, link)
    outcome = emailer.send_email([to], subject, html, text)
    store.record_event(int(item_id), "portal_link_emailed",
                       payload={"kind": key, "to": to, **outcome})
    return {"sent": bool(outcome.get("ok")), "to": to, **outcome}


def _compose(account, link):
    import html as html_mod

    who = account.get("coordinator_name") or account["account_name"]
    subject = f"Your Navtek installer portal link — {account['account_name']}"
    html_body = (
        "<div style=\"font-family:-apple-system,'Segoe UI',Roboto,Helvetica,"
        "Arial,sans-serif;font-size:15px;color:#12181f;line-height:1.5\">"
        f"<h2 style='margin:0 0 10px;font-size:18px'>Hi {html_mod.escape(who)} "
        "— your Navtek installer portal is ready</h2>"
        "<p style='margin:0 0 14px'>Your installs, site contacts and job "
        "updates for "
        f"<b>{html_mod.escape(account['account_name'])}</b> live here:</p>"
        f"<p style='margin:0 0 14px'><a href='{link}' "
        "style='color:#1e5b8f;font-weight:600'>Open the installer portal</a>"
        "</p>"
        "<p style='margin:0 0 14px'>Save that link to your phone's home "
        "screen — it works like a key, no password needed. Please don't "
        "forward it: anyone holding the link can see and update your jobs. "
        "If it needs replacing, Navtek can reissue it any time.</p>"
        "<p style='margin:0;color:#5b6875;font-size:13px'>Navtek eOrder · "
        "sent automatically when your account was set up.</p></div>"
    )
    text_body = (
        f"Hi {who} — your Navtek installer portal is ready.\n\n"
        f"Your installs and job updates for {account['account_name']} live "
        f"here:\n\n{link}\n\n"
        "Save the link to your phone. It works like a key — no password, so "
        "please don't forward it. If it needs replacing, Navtek can reissue "
        "it any time."
    )
    return subject, html_body, text_body
