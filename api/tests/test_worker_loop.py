from types import SimpleNamespace

from app import worker


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def test_failed_pass_is_logged_and_the_loop_sleeps(monkeypatch, caplog):
    def fail(_base_worker_id):
        raise RuntimeError("terminating connection due to administrator command")

    slept = []
    monkeypatch.setattr(worker, "process_one_job", fail)
    monkeypatch.setattr(worker.time, "sleep", slept.append)
    results = _Queue()

    worker._poll_once("w", results, 2.5)

    assert slept == [2.5]
    assert results.items == []
    assert "Reconcile pass failed" in caplog.text


def test_finished_job_is_forwarded_without_sleeping(monkeypatch):
    slept = []
    monkeypatch.setattr(worker, "process_one_job", lambda _id: {"id": 7})
    monkeypatch.setattr(worker.time, "sleep", slept.append)
    results = _Queue()

    worker._poll_once("w", results, 2.5)

    assert results.items == [{"id": 7}]
    assert slept == []


def test_only_abnormally_exited_workers_count_as_crashed():
    running = SimpleNamespace(is_alive=lambda: True, exitcode=None)
    finished = SimpleNamespace(is_alive=lambda: False, exitcode=0)
    killed = SimpleNamespace(is_alive=lambda: False, exitcode=-9)
    failed = SimpleNamespace(is_alive=lambda: False, exitcode=1)

    assert worker._crashed([running, finished, killed, failed]) == [killed, failed]
