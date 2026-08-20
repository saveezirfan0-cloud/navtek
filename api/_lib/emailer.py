"""Email delivery and the ingest alert emails, provider-agnostic.

Same shape as sms.py: everything sends through `send_email(...)`, and which
provider that means is a config change inside this module. With
RESEND_API_KEY set, sends go through Resend's HTTP API; with SMTP_HOST set,
through SMTP (STARTTLS); otherwise the logging stub runs — it "succeeds",
records the send and prints it, so recipients and message content can be read
in the logs before real mail goes out.

The alert rule this module exists for: when an eOrder read lands as
⚠️ Check or ❌ Failed, the people listed on /settings hear about it by email.
Who those people are — and whether each status warrants a send at all — is
admin-editable data in the app_settings table, not deploy-time configuration.
Exactly one email per (order, file, status): sends are claimed in the
`notifications` ledger before sending, the same dedup that keeps the SMS side
honest through webhook retry storms.
"""

import os

from . import config

# Sends this process has made, newest last — the audit surface tests read.
SENT = []

SETTINGS_KEY = "notifications"

DEFAULT_SETTINGS = {
    "emails": [],
    "notify_check": True,
    "notify_failed": True,
}


def provider():
    """Which provider a send would use right now. Read per call, not at
    import, so tests (and a mid-flight env change on redeploy) see the truth."""
    if os.environ.get("RESEND_API_KEY", "").strip():
        return "resend"
    if os.environ.get("SMTP_HOST", "").strip():
        return "smtp"
    return "log"


def sender_address():
    return (os.environ.get("EMAIL_FROM", "") or "").strip()


def notification_settings(store):
    """The saved settings merged over the defaults — a half-saved or older
    value must never crash the webhook that reads it."""
    saved = store.get_setting(SETTINGS_KEY) or {}
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(saved, dict):
        merged.update({k: saved[k] for k in DEFAULT_SETTINGS if k in saved})
    merged["emails"] = clean_emails(merged.get("emails"))
    return merged


def clean_emails(values):
    """A deduped list of plausible addresses out of whatever was saved."""
    if isinstance(values, str):
        values = values.replace(",", "\n").replace(";", "\n").splitlines()
    seen, out = set(), []
    for value in values or []:
        address = str(value).strip().lower()
        if address and "@" in address and "." in address.rsplit("@", 1)[-1]:
            if address not in seen:
                seen.add(address)
                out.append(address)
    return out[:20]


def send_email(to, subject, html, text=None):
    """Send one email to a list of addresses. Returns {"ok": bool, ...}.

    No recipients is a report, not an exception — the caller records the
    attempt either way and /settings is where the fix happens.
    """
    recipients = clean_emails(to)
    if not recipients:
        return {"ok": False, "provider": provider(), "error": "no recipients"}
    result = _deliver(recipients, str(subject), str(html), text)
    SENT.append({"to": recipients, "subject": str(subject), **result})
    del SENT[:-200]   # a warm function must not hoard its whole history
    return result


def _deliver(recipients, subject, html, text):
    which = provider()
    if which == "resend":
        return _deliver_resend(recipients, subject, html, text)
    if which == "smtp":
        return _deliver_smtp(recipients, subject, html, text)
    print(f"[email:log] to {', '.join(recipients)}: {subject}")
    return {"ok": True, "provider": "log"}


def _deliver_resend(recipients, subject, html, text):
    """Resend's HTTP API. Failure is a result, never an exception — a provider
    outage must not take down the webhook that noticed the problem."""
    import httpx

    key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = sender_address()
    if not sender:
        return {"ok": False, "provider": "resend",
                "error": "EMAIL_FROM must be set (a verified sender address)"}
    payload = {"from": sender, "to": recipients, "subject": subject, "html": html}
    if text:
        payload["text"] = text
    try:
        response = httpx.post(
            "https://api.resend.com/emails", json=payload,
            headers={"Authorization": f"Bearer {key}"}, timeout=15,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return {"ok": False, "provider": "resend",
                    "status_code": response.status_code,
                    "error": data.get("message") or f"HTTP {response.status_code}"}
        return {"ok": True, "provider": "resend", "id": data.get("id")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": "resend",
                "error": f"{type(exc).__name__}: {exc}"}


def _deliver_smtp(recipients, subject, html, text):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    sender = sender_address() or user
    if not sender:
        return {"ok": False, "provider": "smtp",
                "error": "EMAIL_FROM (or SMTP_USER) must be set"}
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    if text:
        message.attach(MIMEText(text, "plain"))
    message.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(sender, recipients, message.as_string())
        return {"ok": True, "provider": "smtp"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": "smtp",
                "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------
# The ingest alert — ⚠️ Check and ❌ Failed reads, emailed to the configured
# recipients. Called from handle_webhook on every delivery; decides for
# itself whether this outcome warrants a send.
# --------------------------------------------------------------------------

def notify_ingest_outcome(store, outcome):
    """Email the configured recipients when a read needs a person.

    Never raises, and never touches a delivery that went cleanly: a skipped
    duplicate, a no-file event and a ✅ Read all end here in one line.
    """
    try:
        return _notify_ingest_outcome(store, outcome)
    except Exception as exc:  # noqa: BLE001 - alerting must never cost the order
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}


def _notify_ingest_outcome(store, outcome):
    if outcome.get("skipped"):
        return {"sent": False, "reason": "nothing happened"}

    from . import mapping

    if not outcome.get("ok"):
        status = "failed"
    else:
        status = {mapping.STATUS_READ: "read",
                  mapping.STATUS_CHECK: "check"}.get(outcome.get("status"), "failed")
    if status == "read":
        return {"sent": False, "reason": "read cleanly"}

    settings = notification_settings(store)
    if not settings["emails"]:
        return {"sent": False, "reason": "no notification emails configured"}
    if status == "check" and not settings["notify_check"]:
        return {"sent": False, "reason": "check alerts are off"}
    if status == "failed" and not settings["notify_failed"]:
        return {"sent": False, "reason": "failure alerts are off"}

    # One email per (order, file, status) — a webhook retry storm or a
    # re-drop of the same broken file must not re-alert everyone. Claimed in
    # the notifications ledger BEFORE sending, same as every SMS.
    item_id = int(outcome.get("target_item_id") or outcome.get("item_id") or 0)
    finger = _fingerprint(outcome, status)
    key = f"email_{status}:{finger}"
    if not store.claim_notification(item_id, key, payload={
        "to": settings["emails"],
        "file": outcome.get("file_name"),
        "opportunity_id": outcome.get("opportunity_id"),
    }):
        return {"sent": False, "reason": "already emailed"}

    subject, html, text = _compose(status, outcome, item_id)
    result = send_email(settings["emails"], subject, html, text)
    store.record_event(item_id, "email_sent",
                       payload={"kind": key, "subject": subject,
                                "to": settings["emails"], **result})
    return {"sent": result.get("ok", False), "to": settings["emails"], **result}


def _fingerprint(outcome, status):
    """A stable identity for this alert across retries of the same delivery."""
    import hashlib

    basis = "|".join(str(outcome.get(k) or "") for k in
                     ("opportunity_id", "file_name", "reason")) + f"|{status}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _compose(status, outcome, item_id):
    import html as html_mod

    name = (outcome.get("file_name") or outcome.get("opportunity_id")
            or (f"item {item_id}" if item_id else "an eOrder"))
    if status == "check":
        subject = f"eOrder needs a check: {name}"
        headline = "An eOrder was read, but something needs a look."
        detail_lines = list(outcome.get("warnings") or [])
    else:
        subject = f"eOrder failed: {name}"
        headline = "An eOrder could not be read."
        detail_lines = [outcome.get("reason") or "no detail recorded"]

    base = config.portal_base_url()
    link = f"{base}/orders/{item_id}" if base and item_id else (base or None)

    facts = [
        ("File", outcome.get("file_name")),
        ("Opportunity ID", outcome.get("opportunity_id")),
        ("Status", "⚠️ Check" if status == "check" else "❌ Failed"),
    ]
    fact_rows = "".join(
        f"<tr><td style='padding:4px 14px 4px 0;color:#5b6875'>{label}</td>"
        f"<td style='padding:4px 0;font-weight:600'>{html_mod.escape(str(value))}</td></tr>"
        for label, value in facts if value
    )
    detail_html = "".join(
        f"<li style='margin:4px 0'>{html_mod.escape(str(line))}</li>"
        for line in detail_lines[:12]
    )

    html_body = (
        "<div style=\"font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,"
        "sans-serif;font-size:15px;color:#12181f;line-height:1.5\">"
        f"<h2 style='margin:0 0 10px;font-size:18px'>{html_mod.escape(headline)}</h2>"
        f"<table style='border-collapse:collapse;margin:0 0 12px'>{fact_rows}</table>"
        + (f"<ul style='margin:0 0 14px;padding-left:20px'>{detail_html}</ul>"
           if detail_html else "")
        + (f"<p style='margin:0 0 14px'><a href='{link}' "
           f"style='color:#1e5b8f'>Open this order in the dashboard</a></p>"
           if link else "")
        + "<p style='margin:0;color:#5b6875;font-size:13px'>Navtek eOrder · "
        "you're receiving this because your address is listed under "
        "Settings → Notifications.</p></div>"
    )
    text_body = "\n".join(
        [headline, ""]
        + [f"{label}: {value}" for label, value in facts if value]
        + [""] + [f"- {line}" for line in detail_lines[:12]]
        + ([f"\nOpen: {link}"] if link else [])
    )
    return subject, html_body, text_body
