import threading
import time
from datetime import timedelta

from upgrader.config import Settings
from upgrader.db import now
from upgrader.scheduler import Scheduler

from .test_config import FULL


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def blocking():
    calls, release = [], threading.Event()

    def execute(trigger, scope):
        calls.append((trigger, scope))
        release.wait(5)

    return calls, release, execute


def test_a_request_while_a_run_holds_the_lock_is_refused():
    calls, release, execute = blocking()
    scheduler = Scheduler(execute)
    assert scheduler.request(None) is True
    assert wait_for(lambda: calls)
    assert scheduler.active()
    assert scheduler.request("immich") is False
    release.set()
    assert wait_for(lambda: not scheduler.active())
    assert calls == [("manual", None)]


def test_a_double_click_starts_one_run():
    calls, release, execute = blocking()
    scheduler = Scheduler(execute)
    assert [scheduler.request(None), scheduler.request(None)] == [True, False]
    release.set()
    assert wait_for(lambda: not scheduler.active())
    assert len(calls) == 1


def test_an_exception_in_a_run_releases_the_lock():
    def execute(trigger, scope):
        raise RuntimeError("boom")

    scheduler = Scheduler(execute)
    assert scheduler.request(None)
    assert wait_for(lambda: not scheduler.active())
    assert scheduler.request(None)


def test_a_scheduled_time_during_a_run_starts_after_it():
    calls, release, execute = blocking()
    clock = [now()]
    local = clock[0].astimezone(__import__("zoneinfo").ZoneInfo("Europe/Brussels"))
    due = (local + timedelta(minutes=5)).strftime("%H:%M")
    settings = Settings.from_env({**FULL, "SCHEDULE_TIME": due})
    scheduler = Scheduler(execute, settings=lambda: settings, clock=lambda: clock[0], tick=0.01)
    assert scheduler.request("immich")
    assert wait_for(lambda: calls)
    scheduler.start()
    clock[0] += timedelta(minutes=10)
    time.sleep(0.2)
    assert calls == [("manual", "immich")]
    release.set()
    assert wait_for(lambda: len(calls) == 2)
    assert calls[1] == ("scheduled", None)
    scheduler.stop.set()


def test_schedule_off_starts_nothing():
    calls = []
    settings = Settings.from_env({**FULL, "SCHEDULE_TIME": "off"})
    scheduler = Scheduler(lambda t, s: calls.append(t), settings=lambda: settings, tick=0.01)
    thread = scheduler.start()
    time.sleep(0.1)
    assert calls == []
    scheduler.stop.set()
    thread.join(1)
    assert not thread.is_alive()
