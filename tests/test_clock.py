"""Dates and times in the timezone the business actually runs on.

The server runs UTC. Navtek work Australian eastern time, and for ten to
fourteen hours of every day UTC is on the previous date — so an SLA clock
started a day early, and with the engine live that is a real reminder to a real
installer about a job that is not late yet.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import clock  # noqa: E402


def test_august_is_aest_ten_hours_ahead():
    moment = datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc)
    assert clock.to_local(moment).utcoffset() == timedelta(hours=10)
    assert clock.to_local(moment).hour == 12


def test_january_is_aedt_eleven_hours_ahead():
    """Daylight saving. A fixed +10 would be an hour out for half the year."""
    moment = datetime(2026, 1, 24, 2, 0, tzinfo=timezone.utc)
    assert clock.to_local(moment).utcoffset() == timedelta(hours=11)


def test_late_utc_evening_is_already_tomorrow_in_sydney():
    """The off-by-one that mattered: 23 Aug 23:58 UTC is 24 Aug in Sydney, so
    anything counting days off the server's date was a day behind."""
    moment = datetime(2026, 8, 23, 23, 58, tzinfo=timezone.utc)
    assert moment.date() == date(2026, 8, 23)
    assert clock.to_local(moment).date() == date(2026, 8, 24)


def test_a_naive_timestamp_is_read_as_utc():
    """Every timestamp this app stores is UTC — Supabase, monday, the log."""
    naive = datetime(2026, 8, 23, 23, 58)
    assert clock.to_local(naive).date() == date(2026, 8, 24)


def test_the_fallback_offsets_agree_with_the_zone_database():
    """The manual rule only runs where there is no tzdata, so it is never
    exercised in CI unless asserted directly."""
    for moment, expected in (
        (datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc), timedelta(hours=10)),
        (datetime(2026, 1, 24, 2, 0, tzinfo=timezone.utc), timedelta(hours=11)),
        (datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc), timedelta(hours=11)),
        (datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc), timedelta(hours=10)),
    ):
        assert clock._manual_zone(moment).utcoffset(None) == expected, moment


def test_today_and_now_agree_with_each_other():
    assert clock.today() == clock.now().date()
    assert clock.now().tzinfo is not None
