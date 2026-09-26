from types import SimpleNamespace

import httpx
import pytest

from backend.services.text_indexer import worker as worker_module
from backend.services.text_indexer import supervisor as supervisor_module
from backend.services.text_indexer.__main__ import process_count, worker_id
from backend.services.text_indexer.config import Settings
from backend.services.text_indexer.worker import Worker


def _worker(monkeypatch) -> Worker:
    monkeypatch.setattr(worker_module, "self_test", lambda _: None)
    instance = object.__new__(Worker)
    instance.settings = SimpleNamespace(tika_home=None, poll_seconds=1)
    instance.recover_temporary_files = lambda: 0
    return instance


def test_worker_claim_batch_defaults_to_one(monkeypatch):
    monkeypatch.setenv("TEXT_INDEXER_API_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TEXT_INDEXER_API_KEY", "wti_test.secret")
    monkeypatch.setenv("TEXT_INDEXER_TIKA_HOME", "vendor/tika")
    monkeypatch.delenv("TEXT_INDEXER_CLAIM_BATCH_SIZE", raising=False)
    assert Settings.from_environment().claim_batch_size == 1


def test_supervisor_defaults_to_two_processes_with_unique_runtime_ids(monkeypatch):
    monkeypatch.delenv("TEXT_INDEXER_PROCESS_COUNT", raising=False)
    assert process_count() == 2
    assert worker_id("records-indexer-a", 1842, 1) == "records-indexer-a-1842-1"
    assert worker_id("records-indexer-a", 1842, 2) == "records-indexer-a-1842-2"
    assert worker_id("records-indexer-a", 1843, 1) != worker_id(
        "records-indexer-a", 1842, 1,
    )


def test_supervisor_rejects_zero_processes(monkeypatch):
    monkeypatch.setenv("TEXT_INDEXER_PROCESS_COUNT", "0")
    try:
        process_count()
    except ValueError as error:
        assert str(error) == "TEXT_INDEXER_PROCESS_COUNT must be at least 1"
    else:
        raise AssertionError("zero worker processes must be rejected")


def test_claimed_batch_heartbeats_all_jobs_before_sequential_processing(monkeypatch):
    worker = _worker(monkeypatch)
    jobs = [
        {"job_id": 1, "lease_token": "one", "lease_generation": 1},
        {"job_id": 2, "lease_token": "two", "lease_generation": 1},
    ]
    active: set[int] = set()
    processed: list[int] = []
    worker._claim = lambda: jobs

    def start(job):
        active.add(job["job_id"])
        return job["job_id"], None

    def stop(heartbeat):
        active.discard(heartbeat[0])

    def process(job, heartbeat=None):
        expected_active = {1, 2} if job["job_id"] == 1 else {2}
        assert active == expected_active
        assert heartbeat[0] == job["job_id"]
        processed.append(job["job_id"])

    worker._start_heartbeat = start
    worker._stop_heartbeat = stop
    worker.process = process
    worker.run(once=True)
    assert processed == [1, 2]
    assert active == set()


def test_lease_loss_discards_one_job_without_stopping_batch(monkeypatch):
    worker = _worker(monkeypatch)
    jobs = [
        {"job_id": 1, "lease_token": "one", "lease_generation": 1},
        {"job_id": 2, "lease_token": "two", "lease_generation": 1},
    ]
    processed: list[int] = []
    worker._claim = lambda: jobs
    worker._start_heartbeat = lambda job: (job["job_id"], None)
    worker._stop_heartbeat = lambda heartbeat: None

    def process(job, heartbeat=None):
        processed.append(job["job_id"])
        if job["job_id"] == 1:
            request = httpx.Request("POST", "http://api/jobs/1/fail")
            response = httpx.Response(
                409, request=request, json={"detail": {"code": "lease_lost"}},
            )
            raise httpx.HTTPStatusError("lease lost", request=request, response=response)

    worker.process = process
    worker.run(once=True)
    assert processed == [1, 2]


def test_worker_exits_with_terminal_code_when_credential_is_rejected(monkeypatch):
    request = httpx.Request("POST", "http://api/jobs/claim")
    response = httpx.Response(401, request=request)

    class RejectedWorker:
        def __init__(self, _settings):
            pass

        def run(self):
            raise httpx.HTTPStatusError(
                "unauthorized", request=request, response=response,
            )

    monkeypatch.setattr(supervisor_module, "Worker", RejectedWorker)
    monkeypatch.setattr(supervisor_module.signal, "signal", lambda *_: None)
    with pytest.raises(SystemExit) as error:
        supervisor_module.run_worker(SimpleNamespace())
    assert error.value.code == supervisor_module.AUTH_FAILURE_EXIT_CODE


def test_supervisor_workers_watch_their_parent_and_auth_failure_stops_pool():
    main_source = __import__(
        "inspect"
    ).getsource(__import__(
        "backend.services.text_indexer.__main__", fromlist=["run_pool"]
    ).run_pool)
    supervisor_source = __import__("inspect").getsource(supervisor_module)
    assert "args=(replace(settings, worker_id=identity), run_id)" in main_source
    assert "process.exitcode == AUTH_FAILURE_EXIT_CODE" in main_source
    assert "sibling.terminate()" in main_source
    assert "os.getppid() != supervisor_pid" in supervisor_source
