"""Match an eOrder ship-to value to an Installer Account.

Brief §6.2: monday owns allocation. This only ever produces a *suggestion*, and
only when the ship-to is confidently a known installer. Anything short of
confident is left blank and flagged Check — a wrong installer routes an SMS to
the wrong company and books a job nobody is going to.

Ship-to takes four shapes (§8.1), and only the first names an installer:

    "FFT TECHNOLOGY"      → a real installer account
    "Kane Civil Pty Ltd"  → the customer's own name
    "Nothing to Ship"     → no hardware
    "Multiple Addresses"  → contacts live on the multi-site sheet
"""

import re
from difflib import SequenceMatcher

from . import config

SHIP_SENTINELS = {"nothing to ship", "multiple addresses", "n/a", "tbc", "tba"}

ENTITY_SUFFIX = re.compile(
    r"\b(pty|ltd|limited|p/l|inc|incorporated|group|holdings|australia|aust|"
    r"services|technology|technologies|solutions|the trustee for|t/a|trading as)\b",
    re.I,
)


def match_key(name):
    """Normalise a company name for comparison.

    Strips entity suffixes and punctuation so "FFT TECHNOLOGY PTY LTD",
    "FFT Technology" and "fft-technology" all collapse to "fft".
    """
    if not name:
        return ""
    key = str(name).lower()
    key = re.sub(r"[^a-z0-9\s]", " ", key)
    key = ENTITY_SUFFIX.sub(" ", key)
    return re.sub(r"\s+", " ", key).strip()


def is_sentinel(ship_to):
    return match_key(ship_to) in {match_key(s) for s in SHIP_SENTINELS}


def match(ship_to, accounts, customer_name=None, threshold=None):
    """Return {'account': row|None, 'score': float, 'unmatched': str|None}.

    `accounts` is a list of dicts with at least `account_name` and
    `monday_item_id`.
    """
    threshold = threshold if threshold is not None else config.INSTALLER_MATCH_THRESHOLD
    blank = {"account": None, "score": 0.0, "unmatched": None}

    if not ship_to or is_sentinel(ship_to):
        return blank

    key = match_key(ship_to)
    if not key:
        return blank

    # Ships to the customer, not an installer — expected, not a problem.
    if customer_name and _similar(key, match_key(customer_name)) >= 0.92:
        return blank

    best, best_score = None, 0.0
    for account in accounts:
        candidate = account.get("match_key") or match_key(account.get("account_name"))
        if not candidate:
            continue
        score = _similar(key, candidate)
        # A clean containment ("fft" inside "fft technology") is a real match
        # that character-ratio similarity under-scores on short names.
        if key in candidate or candidate in key:
            score = max(score, 0.95)
        if score > best_score:
            best, best_score = account, score

    if best and best_score >= threshold:
        return {"account": best, "score": round(best_score, 3), "unmatched": None}

    # Named something we don't recognise. Worth surfacing — it is either a new
    # installer to add to the board, or the customer under a trading name.
    return {"account": None, "score": round(best_score, 3), "unmatched": str(ship_to)}


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()
