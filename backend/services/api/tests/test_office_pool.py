"""Deployment settings, cross-process sharing and recovery of failed conversion slots."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from backend.services.api import launcher, office_pool


def test_launcher_reads_worker_count_once(monkeypatch):
    from contextlib import contextmanager

    starts = []

    @contextmanager
    def pool(count, _binary):
        starts.append(count)
        yield

    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("API_WORKERS", "4")
    monkeypatch.setenv("API_RELOAD", "false")
    monkeypatch.delenv("LIBREOFFICE_WORKERS", raising=False)
    monkeypatch.setattr(launcher, "launcher_pool", pool)
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda *a, **kw: monkeypatch.setenv("LIBREOFFICE_WORKERS", "2"),
    )
    launcher.main()
    launcher.main()
    assert starts == [1, 2]
    monkeypatch.setenv("LIBREOFFICE_WORKERS", "0")
    with pytest.raises(RuntimeError, match="at least 1"):
        launcher.main()


@pytest.fixture
def fake_office(tmp_path):
    # Stand-in writes a PID/lock like LibreOffice. SIGKILL is sent only to a
    # verified resident created by this test's private supervisor.
    binary = tmp_path / "office"
    binary.write_text("#!" + sys.executable + "\n" + """
import os, sys, time
from pathlib import Path
args = sys.argv[1:]
source = Path(args[-1])
if '--convert-to' in args:
    output = Path(args[args.index('--outdir') + 1])
    profile = next(a for a in args if a.startswith('-env:')).split('file://', 1)[1]
    if source.name == 'crash.txt':
        marker = output / 'first-worker'
        try:
            with marker.open('x') as stream:
                stream.write((Path(profile).parent / 'pid').read_text())
            time.sleep(60)
        except FileExistsError:
            pass
    pid = (Path(profile).parent / 'pid').read_bytes()
    (output / (source.stem + '.pdf')).write_bytes(b'%PDF-' + pid)
else:
    pid = next(a.split('=', 1)[1] for a in args if a.startswith('--pidfile='))
    Path(pid).write_text(str(os.getpid()))
    (source.parent / ('.~lock.' + source.name + '#')).touch()
    time.sleep(120)
""")
    binary.chmod(0o700)
    return binary


def test_crashed_export_is_requeued_and_idle_slot_is_replenished(tmp_path, fake_office):
    binary = fake_office
    source = tmp_path / "crash.txt"
    source.write_text("document")
    with office_pool.launcher_pool(2, str(binary)):
        address = office_pool.endpoint()
        root = Path(address).parent
        initial = {int(file.read_text()) for file in root.glob("*/pid")}
        assert len(initial) == 2
        with ThreadPoolExecutor(1) as jobs:
            job = jobs.submit(office_pool.request_export, address, source, tmp_path, 15)
            marker = tmp_path / "first-worker"
            for _ in range(100):
                if marker.exists() and marker.read_text():
                    break
                time.sleep(0.05)
            victim = int(marker.read_text())
            assert victim in initial
            os.kill(victim, signal.SIGKILL)
            job.result(timeout=20)
        assert int((tmp_path / "crash.pdf").read_bytes()[5:]) in initial - {victim}
        for _ in range(100):
            live = {
                int(file.read_text())
                for file in root.glob("*/pid")
                if file.stat().st_size
            }
            if len(live) == 2 and victim not in live:
                break
            time.sleep(0.05)
        assert len(live - initial) == 1 and len(live) == 2
    assert not root.exists()


def test_two_api_workers_share_one_resident(client, record, fake_office):
    import socket
    from uuid import uuid4
    import httpx

    upload = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("sample.txt", b"example", "text/plain")},
    )
    upload.raise_for_status()
    path = f"/api/v1/digital-components/{upload.json()['id']}/rendition"
    # Hold an OS-assigned listener through launch, so all requests reach only this test API.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        code = (
            "from functools import partial; from backend.services.api import launcher; "
            f"launcher.uvicorn.run=partial(launcher.uvicorn.run, fd={listener.fileno()}); launcher.main()"
        )
        service = subprocess.Popen(
            [sys.executable, "-c", code],
            pass_fds=(listener.fileno(),),
            env={
                **os.environ,
                "API_WORKERS": "2",
                "API_RELOAD": "false",
                "LIBREOFFICE_WORKERS": "1",
                "LIBREOFFICE_BINARY": str(fake_office),
            },
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                cookies=dict(client.cookies),
                timeout=30,
                trust_env=False,
            ) as api:
                for _ in range(150):
                    try:
                        if api.get("/health", timeout=1).is_success:
                            break
                    except httpx.TransportError:
                        pass
                    assert service.poll() is None
                    time.sleep(0.1)

                def open_preview(_):
                    token = str(uuid4())
                    headers = {
                        "X-Wathiq-Converted-PDF": token,
                        "X-Request-ID": token,
                        "X-Wathiq-Open-PDF": "1",
                    }
                    head = api.head(path, headers=headers)
                    head.raise_for_status()
                    pdf = api.get(
                        path,
                        headers={
                            "X-Wathiq-Converted-PDF": token,
                            "If-Match": head.headers["etag"],
                        },
                    )
                    pdf.raise_for_status()
                    return int(pdf.content.removeprefix(b"%PDF-"))

                with ThreadPoolExecutor(3) as threads:
                    assert len(set(threads.map(open_preview, range(3)))) == 1
        finally:
            service.terminate()
            service.wait(timeout=30)


def test_deadline_retires_stalled_slot_and_allows_new_export(tmp_path, fake_office):
    with office_pool.launcher_pool(1, str(fake_office)):
        endpoint = office_pool.endpoint()
        source = (
            tmp_path / "crash.txt"
        )  # Test converter blocks its first export of this file.
        source.write_text("deadline")
        with pytest.raises((TimeoutError, RuntimeError)):
            office_pool.request_export(endpoint, source, tmp_path, 1)
        assert not source.with_suffix(".pdf").exists()
        old_pid = int((tmp_path / "first-worker").read_text())
        source = tmp_path / "next.txt"
        source.write_text("new request")
        office_pool.request_export(endpoint, source, tmp_path, 15)
        assert int(source.with_suffix(".pdf").read_bytes()[5:]) != old_pid
