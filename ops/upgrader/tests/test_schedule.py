from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from upgrader.schedule import next_run

BRUSSELS = ZoneInfo("Europe/Brussels")


def local(*args):
    return datetime(*args, tzinfo=BRUSSELS)


def test_ordinary_day():
    assert next_run(local(2026, 9, 15, 1, 0), "03:00", "Europe/Brussels") == local(2026, 9, 15, 3, 0)


def test_no_catch_up_after_the_days_time():
    assert next_run(local(2026, 9, 15, 3, 10), "03:00", "Europe/Brussels") == local(2026, 9, 16, 3, 0)


def test_exactly_at_the_time_is_the_next_day():
    assert next_run(local(2026, 9, 15, 3, 0), "03:00", "Europe/Brussels") == local(2026, 9, 16, 3, 0)


def test_clocks_go_forward_runs_at_the_first_valid_instant():
    got = next_run(local(2026, 3, 29, 0, 30), "02:30", "Europe/Brussels")
    assert got.astimezone(UTC) == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
    assert got.astimezone(BRUSSELS).strftime("%H:%M") == "03:00"


def test_clocks_go_back_runs_once():
    first = next_run(local(2026, 10, 25, 0, 0), "02:30", "Europe/Brussels")
    assert first.astimezone(UTC) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    after_first = next_run(first, "02:30", "Europe/Brussels")
    assert after_first.astimezone(BRUSSELS).date().isoformat() == "2026-10-26"
    during_repeat = datetime(2026, 10, 25, 1, 15, tzinfo=UTC)
    assert next_run(during_repeat, "02:30", "Europe/Brussels").astimezone(BRUSSELS).day == 26


def test_brussels_three_oclock_is_never_skipped_or_repeated():
    for after in (local(2026, 3, 28, 12, 0), local(2026, 10, 24, 12, 0)):
        got = next_run(after, "03:00", "Europe/Brussels").astimezone(BRUSSELS)
        assert got.strftime("%H:%M") == "03:00"


def test_off():
    assert next_run(local(2026, 9, 15, 1, 0), "off", "Europe/Brussels") is None
