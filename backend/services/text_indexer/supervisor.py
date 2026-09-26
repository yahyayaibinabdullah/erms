from __future__ import annotations

import logging
import os
import signal
import threading
import time

import httpx

from .config import Settings
from .worker import Worker


LOG = logging.getLogger("wathiq.text_indexer.supervisor")
AUTH_FAILURE_EXIT_CODE = 78


def _exit_when_supervisor_disappears(supervisor_pid: int) -> None:
    """Prevent a worker from surviving an abruptly terminated supervisor."""
    while True:
        time.sleep(0.5)
        if os.getppid() != supervisor_pid:
            os._exit(0)


def run_worker(settings: Settings, supervisor_pid: int | None = None) -> None:
    """Importable multiprocessing entry point for one isolated worker slot."""
    # The supervisor owns service lifecycle. Ignore terminal Ctrl-C in children
    # so it can stop the complete pool without child KeyboardInterrupt traces.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if supervisor_pid is not None:
        threading.Thread(
            target=_exit_when_supervisor_disappears,
            args=(supervisor_pid,),
            daemon=True,
            name="text-indexer-parent-watchdog",
        ).start()
    try:
        Worker(settings).run()
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {401, 403}:
            LOG.error(
                "text-indexer credential was rejected; stopping the managed worker pool"
            )
            raise SystemExit(AUTH_FAILURE_EXIT_CODE) from error
        raise
