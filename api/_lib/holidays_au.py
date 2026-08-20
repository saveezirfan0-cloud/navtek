"""Australian public holidays, as data.

The SLA clock counts business days, and a business day in Australia depends on
which state the installer operates in — chase a Melbourne coordinator on
Melbourne Cup Day and the SLA engine has just proven it doesn't know the
country it runs in. Data as code, not a dependency: the set is small, changes
once a year, and a wrong holiday is a data fix, not a library upgrade.

Coverage: national holidays plus NSW and VIC state holidays (the states
installers operate in today), for LAST_COVERED_YEAR and the year before it.
A test asserts today's year is covered and fails once it isn't — extending
this file is the fix, and the test is how the job lands on someone's desk
rather than the clock silently counting holidays as working days.

Any state not listed here falls back to national holidays only, which
under-counts holidays and therefore over-counts SLA age — the failure mode
that flags a job early rather than the one that lets a breach hide.
"""

from datetime import date

LAST_COVERED_YEAR = 2027

# Holidays observed in every state we care about.
NATIONAL = {
    2026: {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 26): "Australia Day",
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 4): "Easter Saturday",
        date(2026, 4, 5): "Easter Sunday",
        date(2026, 4, 6): "Easter Monday",
        date(2026, 4, 25): "Anzac Day",
        date(2026, 6, 8): "King's Birthday",
        date(2026, 12, 25): "Christmas Day",
        date(2026, 12, 26): "Boxing Day",
        date(2026, 12, 28): "Boxing Day (substitute)",
    },
    2027: {
        date(2027, 1, 1): "New Year's Day",
        date(2027, 1, 26): "Australia Day",
        date(2027, 3, 26): "Good Friday",
        date(2027, 3, 27): "Easter Saturday",
        date(2027, 3, 28): "Easter Sunday",
        date(2027, 3, 29): "Easter Monday",
        date(2027, 4, 25): "Anzac Day",
        date(2027, 6, 14): "King's Birthday",
        date(2027, 12, 25): "Christmas Day",
        date(2027, 12, 26): "Boxing Day",
        date(2027, 12, 27): "Christmas Day (substitute)",
        date(2027, 12, 28): "Boxing Day (substitute)",
    },
}

# Per-state additions on top of NATIONAL.
STATE = {
    "NSW": {
        2026: {
            date(2026, 10, 5): "Labour Day",
        },
        2027: {
            date(2027, 10, 4): "Labour Day",
        },
    },
    "VIC": {
        2026: {
            date(2026, 3, 9): "Labour Day",
            # Proclaimed annually as the Friday before the AFL Grand Final;
            # confirm against the Victorian gazette when the fixture is set.
            date(2026, 9, 25): "Friday before the AFL Grand Final",
            date(2026, 11, 3): "Melbourne Cup Day",
        },
        2027: {
            date(2027, 3, 8): "Labour Day",
            date(2027, 9, 24): "Friday before the AFL Grand Final",
            date(2027, 11, 2): "Melbourne Cup Day",
        },
    },
}


def holidays_for(state, year):
    """{date: name} for one state and year. Unknown state → national only."""
    merged = dict(NATIONAL.get(year, {}))
    merged.update(STATE.get(normalise_state(state), {}).get(year, {}))
    return merged


def normalise_state(state):
    """"nsw", " NSW ", "New South Wales" → "NSW". Unknown values pass through
    uppercased, which falls back to national holidays only."""
    text = str(state or "").strip().upper()
    return {
        "NEW SOUTH WALES": "NSW",
        "VICTORIA": "VIC",
        "QUEENSLAND": "QLD",
        "SOUTH AUSTRALIA": "SA",
        "WESTERN AUSTRALIA": "WA",
        "TASMANIA": "TAS",
        "AUSTRALIAN CAPITAL TERRITORY": "ACT",
        "NORTHERN TERRITORY": "NT",
    }.get(text, text)


def is_business_day(when, state="NSW"):
    if when.weekday() >= 5:
        return False
    return when not in holidays_for(state, when.year)
