"""Australian public holidays, as data (FINALIZE prompt 6).

SLA age is measured in business days, and public holidays differ by state — a
VIC coordinator must not be chased on Melbourne Cup Day, and nobody should be
chased on Good Friday. Data as code, per state per year, because a lookup
table someone can read and extend beats a dependency for ~20 dates a year.

Covers LAST_COVERED_YEAR and everything before it that matters; a test fails
once the calendar outruns the data so someone extends it deliberately.

VIC's Friday before the AFL Grand Final is proclaimed each year and the date
below is the expected one — confirm it when the AFL fixture lands.
"""

from datetime import date

LAST_COVERED_YEAR = 2027

_NATIONAL = {
    # 2026
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 26): "Australia Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 4): "Easter Saturday",
    date(2026, 4, 6): "Easter Monday",
    date(2026, 4, 25): "Anzac Day",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 28): "Boxing Day (observed)",
    # 2027
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 26): "Australia Day",
    date(2027, 3, 26): "Good Friday",
    date(2027, 3, 27): "Easter Saturday",
    date(2027, 3, 29): "Easter Monday",
    date(2027, 4, 25): "Anzac Day",
    date(2027, 12, 27): "Christmas Day (observed)",
    date(2027, 12, 28): "Boxing Day (observed)",
}

_BY_STATE = {
    "NSW": {
        date(2026, 6, 8): "King's Birthday",
        date(2026, 10, 5): "Labour Day",
        date(2027, 6, 14): "King's Birthday",
        date(2027, 10, 4): "Labour Day",
    },
    "VIC": {
        date(2026, 3, 9): "Labour Day",
        date(2026, 6, 8): "King's Birthday",
        date(2026, 9, 25): "Friday before AFL Grand Final (expected)",
        date(2026, 11, 3): "Melbourne Cup Day",
        date(2027, 3, 8): "Labour Day",
        date(2027, 6, 14): "King's Birthday",
        date(2027, 9, 24): "Friday before AFL Grand Final (expected)",
        date(2027, 11, 2): "Melbourne Cup Day",
    },
}


def holidays_for(state):
    """All holidays for a state, national ones included. Unknown state → NSW,
    because a wrong-but-close business-day count beats a crash in an SLA sweep."""
    extra = _BY_STATE.get((state or "NSW").strip().upper(), _BY_STATE["NSW"])
    return {**_NATIONAL, **extra}


def is_business_day(when, state="NSW"):
    return when.weekday() < 5 and when not in holidays_for(state)
