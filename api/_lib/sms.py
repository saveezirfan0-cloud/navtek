"""Provider-agnostic SMS (FINALIZE prompt 3, transport half).

Everything that texts a human goes through send_sms(to, body), so the
Twilio/MessageMedia/whatever decision stays a config change, not a refactor.
The default implementation only logs — which is exactly what the SLA engine's
shadow mode wants, and what keeps a misconfigured deploy from texting anyone.
"""


def send_sms(to, body):
    """Log-only stub. Returns what a real provider adapter should return."""
    print(f"[sms:stub] to={to!r} body={body!r}")
    return {"sent": False, "logged": True, "to": to}
