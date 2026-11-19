"""Launcher-owned headless LibreOffice pool, shared over a private Unix socket."""

from contextlib import ExitStack, contextmanager, suppress
import json
import logging
import multiprocessing
from multiprocessing.connection import wait
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from backend.services.processing_workspace import working_copy_fds

log = logging.getLogger(__name__)
# Private launcher-to-child IPC address, never sourced as deployment configuration.
_ENDPOINT = "_WATHIQ_OFFICE_POOL_SOCKET"
_ANCHOR = (
    '<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'office:mimetype="application/vnd.oasis.opendocument.text" office:version="1.3">'
    "<office:body><office:text><text:p>Wathiq</text:p></office:text></office:body></office:document>"
)

_PROFILE_SETTINGS = """<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/History">
  <prop oor:name="PickListSize" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Recovery/AutoSave">
  <prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Save/Document">
  <prop oor:name="CreateBackup" oor:op="fuse"><value>false</value></prop></item>
</oor:items>"""


def endpoint():
    return os.environ.get(_ENDPOINT)


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("document conversion timed out")
    return seconds


def request_export(address, source, output, timeout):
    """Pass the processing-copy locks with the request, including across API worker death."""
    deadline = time.monotonic() + timeout
    payload = json.dumps([str(source), str(output), deadline]).encode()
    for attempt in range(2):
        with socket.socket(socket.AF_UNIX) as conn:
            conn.setblocking(False)
            while True:
                try:
                    conn.connect(address)
                    break
                except (BlockingIOError, ConnectionRefusedError):
                    time.sleep(min(0.05, remaining(deadline)))
            conn.settimeout(remaining(deadline))
            socket.send_fds(conn, [b"J"], list(working_copy_fds()))
            conn.sendall(payload)
            conn.shutdown(socket.SHUT_WR)
            with conn.makefile("rb") as reader:
                reply = reader.readline(4096)
        if reply == b"OK\n":
            return
        if reply == b"WORKER_EXITED\n" and attempt == 0:
            remaining(deadline)
            continue
        raise RuntimeError(
            reply.decode(errors="replace").strip() or "LibreOffice worker disconnected"
        )


class WorkerExited(RuntimeError):
    pass


class Resident:
    def __init__(self, root, binary):
        self.root = root
        self.binary = binary
        self.process = None
        self.profile = "-env:UserInstallation=" + (root / "profile").as_uri()

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
            self.process = None
        if self.root.exists():
            shutil.rmtree(self.root)

    def start(self, deadline):
        self.stop()
        self.root.mkdir(mode=0o700)
        user = self.root / "profile" / "user"
        user.mkdir(parents=True, mode=0o700)
        (user / "registrymodifications.xcu").write_text(_PROFILE_SETTINGS)
        anchor = self.root / "resident.fodt"
        anchor.write_text(_ANCHOR)
        self.options = [
            self.binary,
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            self.profile,
        ]
        self.env = {**os.environ, "SAL_DISABLE_OPENCL": "1", "TMPDIR": str(self.root)}
        self.process = subprocess.Popen(
            [*self.options, "--pidfile=" + str(self.root / "pid"), str(anchor)],
            env=self.env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        while not (self.root / ".~lock.resident.fodt#").exists():
            if self.process.poll() is not None:
                raise RuntimeError("LibreOffice worker failed to start")
            time.sleep(min(0.05, remaining(deadline)))
        probe = self.root / "ready.txt"
        probe.write_text("Ready")
        self.export(probe, self.root, deadline)
        if not probe.with_suffix(".pdf").read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("LibreOffice produced an invalid readiness PDF")
        log.info("LibreOffice slot %s ready (PID %s)", self.root.name, self.process.pid)

    def export(self, source, output, deadline):
        # The short-lived CLI forwards this command to the private profile owner.
        with subprocess.Popen(
            [
                *self.options,
                "--convert-to",
                "pdf",
                "--outdir",
                str(output),
                str(source),
            ],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as client:
            try:
                while client.poll() is None:
                    if self.process.poll() is not None:
                        raise WorkerExited("LibreOffice worker exited during export")
                    try:
                        client.wait(timeout=min(0.2, remaining(deadline)))
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if client.poll() is None:
                    client.kill()
            if self.process.poll() is not None:
                raise WorkerExited("LibreOffice worker exited during export")
        if (
            client.returncode
            or not (output / source.with_suffix(".pdf").name).is_file()
        ):
            raise RuntimeError("LibreOffice could not complete the PDF export")


def serve_job(conn, resident):
    reply = b"OK\n"
    with ExitStack() as locks:
        try:
            conn.settimeout(5)
            marker, fds, flags, _ = socket.recv_fds(conn, 1, 16)
            for fd in fds:
                locks.callback(os.close, fd)
            if marker != b"J" or flags & socket.MSG_CTRUNC:
                raise ValueError("Invalid conversion request")
            with conn.makefile("rb") as reader:
                source, output, deadline = json.loads(reader.read(16384))
            if deadline <= time.monotonic():
                reply = b"Conversion queue deadline expired\n"
            elif resident.process.poll() is not None:
                raise WorkerExited("LibreOffice exited before export")
            else:
                resident.export(Path(source), Path(output), deadline)
        except WorkerExited:
            resident.stop()
            (Path(output) / (Path(source).stem + ".pdf")).unlink(missing_ok=True)
            log.warning(
                "LibreOffice worker exited during conversion; releasing slot for recovery"
            )
            reply = b"WORKER_EXITED\n"
        except (TypeError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            resident.stop()  # Stop work before releasing any inherited disposition fence.
            log.warning("LibreOffice export failed (%s)", type(exc).__name__)
            reply = b"LibreOffice conversion failed or timed out\n"
    try:
        conn.sendall(reply)
    except OSError:
        pass  # Caller closed during conversion.


def serve_slot(listener, resident, stopped, ready):
    try:
        while not stopped.is_set():
            dead = resident.process is None or resident.process.poll() is not None
            if dead:
                try:
                    resident.start(time.monotonic() + 30)
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    resident.stop()
                    log.warning(
                        "LibreOffice readiness export unavailable (%s)",
                        type(exc).__name__,
                    )
                    ready.set()
                    stopped.wait(10)
                    continue
            ready.set()
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            with conn:
                serve_job(conn, resident)
    finally:
        resident.stop()


def supervise(control, count, binary):
    # This spawned process does not inherit Uvicorn logging configuration.
    logging.basicConfig(level=logging.INFO)
    # A separate process holds job fences even if an individual ASGI process exits.
    with (
        tempfile.TemporaryDirectory(prefix="wathiq-office-", dir="/tmp") as directory,
        socket.socket(socket.AF_UNIX) as listener,
    ):
        address = str(Path(directory) / "jobs")
        listener.bind(address)
        listener.listen(socket.SOMAXCONN)
        listener.settimeout(0.25)
        stopped = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stopped.set())
        threads = []
        readiness = []
        try:
            for index in range(count):
                resident = Resident(Path(directory) / str(index), binary)
                ready = threading.Event()
                readiness.append(ready)
                thread = threading.Thread(
                    target=serve_slot, args=(listener, resident, stopped, ready)
                )
                thread.start()
                threads.append(thread)
            for ready in readiness:
                ready.wait()
            control.send(address)
            while not stopped.is_set():
                if wait([control, multiprocessing.parent_process().sentinel], timeout=.5):
                    break
        finally:
            stopped.set()
            for thread in threads:
                thread.join()
            control.close()


@contextmanager
def launcher_pool(count, binary):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    supervisor = ctx.Process(
        target=supervise, args=(child, count, binary), name="wathiq-office-pool"
    )
    supervisor.start()
    child.close()
    previous = os.environ.pop(_ENDPOINT, None)
    try:
        if not parent.poll(45):
            raise RuntimeError("LibreOffice pool supervisor failed to start")
        os.environ[_ENDPOINT] = parent.recv()
        yield
    finally:
        os.environ.pop(_ENDPOINT, None)
        if previous is not None:
            os.environ[_ENDPOINT] = previous
        parent.close()
        supervisor.join()
