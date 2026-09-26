from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import signal
import time
from dataclasses import replace

from .config import Settings
from .supervisor import AUTH_FAILURE_EXIT_CODE, run_worker
from .tika import self_test
from .worker import Worker


LOG = logging.getLogger("wathiq.text_indexer.supervisor")


def process_count() -> int:
    value = int(os.getenv("TEXT_INDEXER_PROCESS_COUNT", "2"))
    if value < 1:
        raise ValueError("TEXT_INDEXER_PROCESS_COUNT must be at least 1")
    return value


def worker_id(base: str, run_id: int, slot: int) -> str:
    return f"{base}-{run_id}-{slot}"


def run_pool(settings: Settings, count: int) -> None:
    context = multiprocessing.get_context("spawn")
    run_id = os.getpid()
    stopping = False
    workers: dict[int, multiprocessing.Process] = {}

    def stop(_signum=None, _frame=None) -> None:
        nonlocal stopping
        stopping = True
        for process in workers.values():
            if process.is_alive():
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def start(slot: int) -> multiprocessing.Process:
        identity = worker_id(settings.worker_id, run_id, slot)
        process = context.Process(
            target=run_worker,
            args=(replace(settings, worker_id=identity), run_id),
            name=f"text-indexer-{slot}",
        )
        process.start()
        LOG.info("started worker process %s with ID %s", process.pid, identity)
        return process

    try:
        workers = {slot: start(slot) for slot in range(1, count + 1)}
        while not stopping:
            time.sleep(1)
            for slot, process in list(workers.items()):
                if process.is_alive():
                    continue
                process.join()
                if process.exitcode == AUTH_FAILURE_EXIT_CODE:
                    LOG.error(
                        "worker credential was rejected; stopping all text-indexer processes"
                    )
                    stopping = True
                    for sibling in workers.values():
                        if sibling.is_alive():
                            sibling.terminate()
                    break
                if not stopping:
                    LOG.error(
                        "worker slot %s exited with status %s; restarting",
                        slot, process.exitcode,
                    )
                    time.sleep(1)
                    workers[slot] = start(slot)
    finally:
        for process in workers.values():
            if process.is_alive():
                process.terminate()
        for process in workers.values():
            process.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wathiq REST-only text-indexing worker")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_environment()
    if args.self_test:
        self_test(settings.tika_home)
        return
    if args.once:
        Worker(settings).run(once=True)
        return
    run_pool(settings, process_count())


if __name__ == "__main__":
    main()
