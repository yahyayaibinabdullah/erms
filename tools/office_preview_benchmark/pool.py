"""Disposable benchmark adapter. Only the browser test server installs this hook."""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import tempfile
import threading
import time

from backend.services.api import document_conversion
from tools.webui_test_events import EventWriter


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def converter(directory, workers):
    """Bound active and waiting jobs. Abort the trial on a broken resident."""
    original = document_conversion._run
    office = document_conversion._libreoffice_binary()
    leases = Queue(maxsize=workers)
    admission = threading.BoundedSemaphore(max(1, workers * 2))
    events = EventWriter(directory / "office-jobs.jsonl")
    lock = threading.Lock()
    started = time.monotonic()
    residents = []
    with ExitStack() as cleanup:
        cleanup.callback(events.close)
        for _ in range(workers):
            root = Path(
                cleanup.enter_context(
                    tempfile.TemporaryDirectory(prefix="wathiq-office-trial-")
                )
            )
            # A harmless document keeps the desktop alive after a forwarded CLI
            # export closes its own document. No UNO network listener is opened.
            anchor = root / "resident.fodt"
            anchor.write_text(
                '<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                'office:mimetype="application/vnd.oasis.opendocument.text" office:version="1.3">'
                "<office:body><office:text><text:p>Private benchmark worker.</text:p>"
                "</office:text></office:body></office:document>"
            )
            profile = "-env:UserInstallation=" + (root / "profile").as_uri()
            options = [
                office,
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                profile,
            ]
            pidfile = root / "pid"
            proc = subprocess.Popen(
                [*options, "--pidfile=" + str(pidfile), str(anchor)],
                env={**os.environ, "SAL_DISABLE_OPENCL": "1"},
            )
            residents.append((root, proc))
            cleanup.callback(stop, proc)
            deadline = time.monotonic() + 20
            # The PID file can appear before Writer has opened its anchor.
            # Sending the export then raced Writer import on macOS.
            anchor_lock = root / (".~lock." + anchor.name + "#")
            while not (pidfile.exists() and anchor_lock.exists()):
                if proc.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("LibreOffice resident failed to start")
                time.sleep(0.05)
            probe = root / "probe.txt"
            probe.write_text("Readiness probe.")
            subprocess.run(
                [*options, "--convert-to", "pdf", "--outdir", str(root), str(probe)],
                check=True,
                timeout=20,
                capture_output=True,
            )
            if not probe.with_suffix(".pdf").is_file() or proc.poll() is not None:
                raise RuntimeError("Resident could not complete the readiness export")
            leases.put((profile, proc))
        events.append(
            dict(
                event="ready",
                workers=workers,
                startup_s=round(time.monotonic() - started, 3),
            )
        )

        def measured(command, **kwargs):
            if "--convert-to" not in command:
                return original(command, **kwargs)
            arrival = time.monotonic()
            lease = None
            if workers:
                if not admission.acquire(blocking=False):
                    raise document_conversion.ConversionUnavailable(
                        "Benchmark pool queue full"
                    )
                try:
                    lease = leases.get(timeout=kwargs["timeout"])
                except Empty:
                    admission.release()
                    raise subprocess.TimeoutExpired(
                        command, kwargs["timeout"]
                    ) from None
            try:
                begin = time.monotonic()
                if lease:
                    profile, proc = lease
                    if proc.poll() is not None:
                        raise RuntimeError("Resident exited; refusing a cold fallback")
                    command = [
                        profile if arg.startswith("-env:UserInstallation=") else arg
                        for arg in command
                    ]
                    kwargs["timeout"] = max(
                        0.001, kwargs["timeout"] - (begin - arrival)
                    )
                try:
                    result = original(command, **kwargs)
                except subprocess.TimeoutExpired:
                    if lease:
                        stop(proc)
                    raise
                if lease and proc.poll() is not None:
                    raise RuntimeError("Resident exited during export")
                with lock:
                    events.append(
                        dict(
                            event="export",
                            format=Path(command[-1]).suffix,
                            arrival=arrival,
                            begin=begin,
                            end=time.monotonic(),
                            worker=proc.pid if lease else None,
                            status=result.returncode,
                        )
                    )
                return result
            finally:
                if lease:
                    leases.put(lease)
                    admission.release()

        document_conversion._run = measured
        try:
            yield
        finally:
            document_conversion._run = original
    assert all(
        proc.poll() is not None and not root.exists() for root, proc in residents
    )
    (directory / "office-shutdown.json").write_text(
        json.dumps(
            {
                "stopped_workers": [proc.pid for _, proc in residents],
                "profiles_removed": True,
            }
        )
        + "\n"
    )
