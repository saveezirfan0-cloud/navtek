"""What time it is, in the timezone the business runs on.

Everything here used to be `date.today()` and `datetime.now()`, which on Vercel
means UTC. Navtek work Australian eastern time, and for ten to fourteen hours of
every day UTC is on the previous date — so a dispatch at 9am Sydney was
recorded as yesterday, the SLA clock started a day early, and an order placed
on the 1st filed into the previous month's group. With the SLA engine live
(SLA_NOTIFICATIONS_ENABLED) an off-by-one day is a real reminder sent to a real
installer about a job that is not late yet.

ZoneInfo is the source of truth; `tzdata` is pinned in requirements.txt so the
zone resolves even on a runtime image that ships no system zoneinfo. The manual
fallback exists because a missing timezone database must not take the app down
— UTC+10/+11 by the NSW rule is wrong for at most an hour a year at the
changeover, where UTC is wrong for half of every day.
"""

from datetime import date, datetime, timedelta, timezone

TZ_NAME = "Australia/Sydney"

# AEST is UTC+10; AEDT (daylight saving) is UTC+11.
_AEST = timezone(timedelta(hours=10))
_AEDT = timezone(timedelta(hours=11))

try:  # pragma: no cover - exercised by whichever branch the runtime provides
    from zoneinfo import ZoneInfo

    _ZONE = ZoneInfo(TZ_NAME)
except Exception:  # noqa: BLE001 - no tzdata on this runtime
    _ZONE = None


def _first_sunday(year, month):
    """The first Sunday of a month — when NSW changes its clocks."""
    day = date(year, month, 1)
    return day + timedelta(days=(6 - day.weekday()) % 7)


def _manual_zone(moment_utc):
    """AEDT from the first Sunday in October to the first Sunday in April.

    Both switches happen at 2am local, which this rounds to the whole day. The
    error is confined to a few hours twice a year, on a boundary where nothing
    here is precise to the hour anyway.
    """
    year = moment_utc.year
    starts = datetime.combine(_first_sunday(year, 10), datetime.min.time(),
                              tzinfo=timezone.utc)
    ends = datetime.combine(_first_sunday(year, 4), datetime.min.time(),
                            tzinfo=timezone.utc)
    return _AEDT if (moment_utc >= starts or moment_utc < ends) else _AEST


def zone(moment_utc=None):
    """The tzinfo to use — real zone where available, offset rule otherwise."""
    if _ZONE is not None:
        return _ZONE
    return _manual_zone(moment_utc or datetime.now(timezone.utc))


def now():
    """Timezone-aware 'now' in Australian eastern time."""
    moment = datetime.now(timezone.utc)
    return moment.astimezone(zone(moment))


def today():
    """The date it is in Australian eastern time — not the server's date."""
    return now().date()


def to_local(moment):
    """Render any datetime in Australian eastern time.

    A naive datetime is read as UTC, which is what every timestamp this app
    stores actually is (Supabase timestamptz, monday's API, datetime.utcnow).
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone(moment.astimezone(timezone.utc)))
