"""When the nightly run is due (D11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _instant(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The first instant whose local wall time is `day` at `at`, or the first valid instant
    after it when the clocks skip it. A repeated wall time resolves to its first occurrence."""
    wall = datetime.combine(day, at)
    first = wall.replace(tzinfo=zone, fold=0)
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall:
        return first
    lo = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    hi = first.astimezone(UTC)
    lo, hi = min(lo, hi), max(lo, hi)
    while hi - lo > timedelta(minutes=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(zone).replace(tzinfo=None) >= wall:
            hi = mid
        else:
            lo = mid
    return hi.replace(second=0, microsecond=0).astimezone(zone)


def next_run(after: datetime, schedule_time: str, timezone: str) -> datetime | None:
    """The first scheduled instant strictly after `after`, or None when the schedule is off."""
    if schedule_time == "off":
        return None
    zone = ZoneInfo(timezone)
    hour, minute = (int(part) for part in schedule_time.split(":"))
    local_day = after.astimezone(zone).date()
    for offset in range(3):
        candidate = _instant(local_day + timedelta(days=offset), time(hour, minute), zone)
        if candidate > after:
            return candidate
    raise AssertionError("unreachable: a scheduled time occurs every day")
