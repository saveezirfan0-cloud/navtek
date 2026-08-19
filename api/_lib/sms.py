"""SMS delivery, provider-agnostic.

The Twilio/MessageMedia/etc decision hasn't been made, and nothing else should
care when it is: everything sends through `send_sms(to, body)` and the provider
is a config change inside this module, not a refactor outside it.

The default implementation is a logging stub. It "succeeds" — records the send
and prints it — so the whole trigger pipeline (dedupe, message content,
who-gets-what) can run and be read in the logs before a single real text goes
out. Wire a real provider by replacing `_deliver`.
"""

# Sends this process has made, newest last. The stub's audit surface: tests
# read it, and a warm function's logs can be cross-checked against it.
SENT = []


def send_sms(to, body):
    """Send one SMS. Returns {"ok": bool, "provider": str, ...}.

    `to` should be E.164. A missing number is a report, not an exception —
    the caller records the attempt either way and the coordinator's row on the
    Installer Accounts board is where the fix happens.
    """
    if not to or not str(to).strip():
        return {"ok": False, "provider": PROVIDER, "error": "no mobile number"}
    result = _deliver(str(to).strip(), str(body))
    SENT.append({"to": str(to).strip(), "body": str(body), **result})
    del SENT[:-200]   # a warm function must not hoard its whole history
    return result


PROVIDER = "log"


def _deliver(to, body):
    """The logging stub. Replace this to go live with a real provider."""
    print(f"[sms:{PROVIDER}] to {to}: {body}")
    return {"ok": True, "provider": PROVIDER}
