"""SMS delivery, provider-agnostic.

Everything sends through `send_sms(to, body)`; the provider is a config
change inside this module, not a refactor outside it. With TWILIO_ACCOUNT_SID
set, sends go through Twilio's Messages API (raw httpx, no SDK — same
cold-start reasoning as store.py); otherwise the logging stub runs.

The stub "succeeds" — records the send and prints it — so the whole trigger
pipeline (dedupe, message content, who-gets-what) can run and be read in the
logs before a single real text goes out. That is also why the SLA engine's
shadow mode and this stub are separate switches: shadow mode decides whether
to send at all, this module decides how.
"""

import os

# Sends this process has made, newest last. The audit surface for both
# providers: tests read it, and a warm function's logs can be cross-checked
# against it.
SENT = []


def provider():
    """Which provider a send would use right now. Read per call, not at
    import, so tests (and a mid-flight env change on redeploy) see the truth."""
    return "twilio" if os.environ.get("TWILIO_ACCOUNT_SID") else "log"


def send_sms(to, body):
    """Send one SMS. Returns {"ok": bool, "provider": str, ...}.

    `to` should be E.164. A missing number is a report, not an exception —
    the caller records the attempt either way and the coordinator's row on the
    Installer Accounts board is where the fix happens. The result carries the
    provider's message id and status when there is one, so the notification
    ledger's payload says what actually happened, not just what was tried.
    """
    if not to or not str(to).strip():
        return {"ok": False, "provider": provider(), "error": "no mobile number"}
    result = _deliver(str(to).strip(), str(body))
    SENT.append({"to": str(to).strip(), "body": str(body), **result})
    del SENT[:-200]   # a warm function must not hoard its whole history
    return result


def _deliver(to, body):
    if provider() == "twilio":
        return _deliver_twilio(to, body)
    print(f"[sms:log] to {to}: {body}")
    return {"ok": True, "provider": "log"}


def _deliver_twilio(to, body):
    """Twilio Messages API. Failure is a result, never an exception — a
    provider outage must not take down the sweep that noticed the breach."""
    import httpx

    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    sender = (os.environ.get("TWILIO_FROM", "")
              or os.environ.get("TWILIO_MESSAGING_SERVICE_SID", "")).strip()
    if not token or not sender:
        return {"ok": False, "provider": "twilio",
                "error": "TWILIO_AUTH_TOKEN and TWILIO_FROM (or "
                         "TWILIO_MESSAGING_SERVICE_SID) must both be set"}

    fields = {"To": to, "Body": body}
    if sender.startswith("MG"):
        fields["MessagingServiceSid"] = sender
    else:
        fields["From"] = sender

    try:
        response = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=fields, auth=(sid, token), timeout=15,
        )
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return {"ok": False, "provider": "twilio",
                    "status_code": response.status_code,
                    "error": data.get("message") or f"HTTP {response.status_code}"}
        return {"ok": True, "provider": "twilio",
                "sid": data.get("sid"), "status": data.get("status")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "provider": "twilio",
                "error": f"{type(exc).__name__}: {exc}"}
