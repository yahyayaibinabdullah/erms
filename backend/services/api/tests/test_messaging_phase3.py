"""Real network/process integration; runner supplies a unique disposable database."""

import asyncio
from contextlib import contextmanager, suppress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest
from websockets.asyncio.client import connect

from .test_messaging import account, db, payload, post, PREFIX
from .test_global_privilege_enforcement import _bearer
from backend.services.api.messaging.models import Send
from backend.services.api.messaging.service import send
from backend.services.api.messaging.realtime import (
    Gateway,
    Subscriber,
    event,
    BoundedStream,
)

ROOT = Path(__file__).resolve().parents[4]


def test_idle_listener_shutdown_is_bounded(client):
    async def scenario():
        gateway = Gateway()
        gateway.start()
        try:
            async with asyncio.timeout(5):
                while not gateway.ready:
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            await asyncio.wait_for(gateway.stop(), timeout=2)
            assert gateway.task.done() and not gateway.ready
        finally:
            if gateway.connection is not None:
                await gateway.connection.close()

    asyncio.run(scenario())


@contextmanager
def gateways(count=2, on_start=None):
    processes, urls = [], []
    try:
        for _ in range(count):
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.services.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--timeout-graceful-shutdown",
                    "5",
                ],
                cwd=ROOT,
                env={**os.environ, "MESSAGING_STREAM_HEARTBEAT_SECONDS": "1",
                     "API_HOST": "127.0.0.1", "API_PORT": str(port)},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            if on_start is not None:
                on_start()
            url = f"http://127.0.0.1:{port}"
            readiness = {}
            for attempt in range(150):
                if process.poll() is not None:
                    pytest.fail("isolated gateway failed to start")
                try:
                    response = httpx.get(url + "/health", timeout=0.5)
                    if (
                        response.status_code == 200
                        and response.json()["messaging_realtime"]["listener_connected"]
                    ):
                        break
                    state = f"HTTP {response.status_code}, listener not ready"
                except httpx.HTTPError as error:
                    state = type(error).__name__
                readiness[state] = readiness.get(state, 0) + 1
                time.sleep(0.1)
            else:
                pytest.fail(f"isolated gateway startup timeout ({readiness})")
            urls.append(url)
        yield urls, processes
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def ws(url):
    return url.replace("http:", "ws:") + PREFIX + "/stream/ws"


async def hint(socket, kind="message_available"):
    async with asyncio.timeout(12):
        while True:
            value = json.loads(await socket.recv())
            if value["event_type"] == kind:
                return value


def test_gateway_startup_during_commits_reconciles_every_delivery(client):
    from concurrent.futures import ThreadPoolExecutor

    sender, _, _ = account(client)
    recipient, rid, _ = account(client)
    pending = []

    def send_during_startup():
        identities = []
        for _ in range(3):
            response = post(client, sender, payload(rid))
            assert response.status_code == 200
            identities.append(response.json()["deliveries"][0]["id"])
        return identities

    with ThreadPoolExecutor(max_workers=1) as executor:
        with gateways(
            1, on_start=lambda: pending.append(executor.submit(send_during_startup))
        ) as (urls, _):
            expected = set(pending[0].result(timeout=10))

            async def scenario():
                async with connect(
                    ws(urls[0]), additional_headers=_bearer(recipient)
                ) as stream:
                    await hint(stream, "reconciliation_required")
                    # Commit once more after subscription but before snapshot.
                    response = await asyncio.to_thread(
                        post, client, sender, payload(rid)
                    )
                    assert response.status_code == 200
                    expected.add(response.json()["deliveries"][0]["id"])
                    async with httpx.AsyncClient() as rest:
                        page = await rest.get(
                            urls[0] + PREFIX + "/catch-up",
                            headers=_bearer(recipient),
                            params={"after": 0, "limit": 50},
                        )
                    assert page.status_code == 200
                    assert {item["id"] for item in page.json()["items"]} == expected
                    assert page.json()["next_cursor"] == 4

            asyncio.run(scenario())


def test_cross_instance_all_connections_postcommit_rollback_and_listener_recovery(
    client,
):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    other, _, _ = account(client)
    with gateways() as (urls, processes):

        async def scenario():
            async with (
                connect(ws(urls[0]), additional_headers=_bearer(recipient)) as a,
                connect(ws(urls[1]), additional_headers=_bearer(recipient)) as b,
                connect(ws(urls[1]), additional_headers=_bearer(recipient)) as c,
                connect(ws(urls[1]), additional_headers=_bearer(other)) as outsider,
            ):
                for stream in (a, b, c, outsider):
                    await hint(stream, "reconciliation_required")
                with db() as transaction:
                    transaction.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    transaction.execute(
                        "SELECT set_config('app.user_id',%s,true)", (str(uid),)
                    )
                    result = send(transaction, uid, Send(**payload(rid)))
                    # No event can become visible while the rows are uncommitted.
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(hint(a), 0.2)
                    transaction.commit()
                expected = str(result["deliveries"][0]["id"])
                for stream in (a, b, c):
                    value = await hint(stream)
                    assert set(value) == {
                        "schema_version",
                        "event_type",
                        "delivery_id",
                        "mailbox_cursor",
                    }
                    assert value["delivery_id"] == expected
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(hint(outsider), 0.2)
                with db() as transaction:
                    transaction.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    transaction.execute(
                        "SELECT set_config('app.user_id',%s,true)", (str(uid),)
                    )
                    send(transaction, uid, Send(**payload(rid)))
                    transaction.rollback()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(hint(a), 0.2)
                # Disconnect every dedicated listener, including gateways whose
                # client WebSockets remain open. Recovery requests reconciliation.
                with db() as database:
                    rows = database.execute(
                        "SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='wathiq-message-listener'"
                    ).fetchall()
                    assert len(rows) >= 2
                    for row in rows:
                        database.execute(
                            "SELECT pg_terminate_backend(%s)", (row["pid"],)
                        )
                committed = await asyncio.to_thread(post, client, sender, payload(rid))
                assert committed.status_code == 200, committed.text
                for stream in (a, b, c):
                    await hint(stream, "reconciliation_required")
                async with httpx.AsyncClient() as rest:
                    page = await rest.get(
                        urls[1] + PREFIX + "/catch-up",
                        headers=_bearer(recipient),
                        params={"after": 1, "limit": 1},
                    )
                    assert page.status_code == 200
                    assert len(page.json()["items"]) == 1
                    assert (
                        page.json()["items"][0]["id"]
                        == committed.json()["deliveries"][0]["id"]
                    )

        asyncio.run(scenario())


def test_websocket_sse_equivalence_authentication_and_session_revocation(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    with gateways() as (urls, processes):

        async def scenario():
            from frontend.webui.messaging_live import stream_events

            async with connect(
                ws(urls[0]), additional_headers=_bearer(recipient)
            ) as websocket:
                stream = stream_events(urls[1], recipient, "sse")
                assert (await anext(stream))["event_type"] == "reconciliation_required"
                await hint(websocket, "reconciliation_required")
                result = await asyncio.to_thread(post, client, sender, payload(rid))
                assert result.status_code == 200
                while True:
                    sse = await asyncio.wait_for(anext(stream), 10)
                    if sse["event_type"] == "message_available":
                        break
                assert sse == await hint(websocket)
                async with httpx.AsyncClient() as rest:
                    for base in urls:
                        page = await rest.get(
                            base + PREFIX + "/catch-up",
                            headers=_bearer(recipient),
                            params={"after": 0},
                        )
                        assert page.json()["items"][0]["id"] == sse["delivery_id"]
                    assert (
                        await rest.get(urls[0] + PREFIX + "/stream/sse")
                    ).status_code == 401
                    assert (
                        await rest.get(
                            urls[0] + PREFIX + "/stream/sse?user_id=" + str(uid),
                            headers=_bearer(recipient),
                        )
                    ).status_code == 401
                with db() as database:
                    database.execute(
                        "UPDATE login_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=%s",
                        (rid,),
                    )
                from websockets.exceptions import ConnectionClosed

                with pytest.raises(ConnectionClosed):
                    while True:
                        await websocket.recv()
                with pytest.raises(StopAsyncIteration):
                    while True:
                        await asyncio.wait_for(anext(stream), 5)
                await stream.aclose()
            from websockets.exceptions import InvalidStatus

            for kwargs in (
                {},
                {
                    "additional_headers": {
                        "Cookie": "erms_session=" + recipient,
                        "Origin": "https://untrusted.example",
                    }
                },
                {"additional_headers": _bearer(recipient)},
            ):
                with pytest.raises(InvalidStatus):
                    async with connect(ws(urls[0]), **kwargs):
                        pass

        asyncio.run(scenario())


def test_bounded_queues_slow_client_isolation_and_unknown_payloads(client, monkeypatch):
    import backend.services.api.messaging.realtime as realtime

    monkeypatch.setattr(realtime, "QUEUE_SIZE", 2)
    monkeypatch.setattr(realtime, "MAX_CONNECTIONS", 3)
    monkeypatch.setattr(realtime, "MAX_USER_CONNECTIONS", 2)

    async def scenario():
        gateway = Gateway()
        slow, fast = gateway.subscribe(1), gateway.subscribe(1)
        gateway.subscribe(2)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            gateway.subscribe(3)
        with pytest.raises(HTTPException):
            gateway.subscribe(1)
        await slow.queue.get()
        await fast.queue.get()
        from uuid import uuid4

        data = {
            "recipient_user_id": 1,
            "delivery_id": str(uuid4()),
            "mailbox_sequence": 1,
        }
        for i in range(5):
            data["mailbox_sequence"] = i + 1
            gateway.broadcast(json.dumps(data))
            assert (await fast.queue.get())["mailbox_cursor"] == i + 1
        assert slow.overflow and slow.queue.qsize() == 1
        gateway.broadcast("malformed")
        gateway.broadcast(json.dumps({**data, "mailbox_sequence": False}))
        assert fast.queue.empty()
        # A stalled network send is timed out; generator cleanup still runs.
        monkeypatch.setattr(realtime, "SEND_TIMEOUT", 0.01)
        closed = []

        async def body():
            try:
                yield "data: {}\n\n"
            finally:
                closed.append(True)

        async def stalled_send(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(10)

        await BoundedStream(body()).stream_response(stalled_send)
        assert closed
        await gateway.stop()

    asyncio.run(scenario())


def test_two_frontend_processes_duplicate_hints_and_api_frontend_restart(
    client, tmp_path
):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    initial = post(client, sender, payload(rid))
    assert initial.status_code == 200
    workers = []
    folders = [tmp_path / "frontend-a", tmp_path / "frontend-b"]

    def effects(index):
        path = folders[index] / "events.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def wait_for(predicate):
        for _ in range(200):
            if predicate():
                return
            assert all(p.poll() is None for p in workers), "frontend probe exited"
            time.sleep(0.05)
        pytest.fail("frontend effects did not converge")

    def start(base, transport, index):
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tools.messaging_consumer_probe",
                base,
                transport,
                str(folders[index]),
            ],
            cwd=ROOT,
            env={**os.environ, "MESSAGING_PROBE_TOKEN": recipient},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    with gateways() as (urls, processes):
        try:
            workers.extend([start(urls[0], "ws", 0), start(urls[1], "sse", 1)])
            wait_for(
                lambda: all(
                    any(x["kind"] == "summary" and x["value"] == 1 for x in effects(i))
                    for i in range(2)
                )
            )
            sent = post(client, sender, payload(rid)).json()
            identity = sent["deliveries"][0]["id"]
            wait_for(
                lambda: all(
                    any(x == {"kind": "message", "value": identity} for x in effects(i))
                    for i in range(2)
                )
            )
            with db() as database:
                for _ in range(3):
                    database.execute(
                        "SELECT pg_notify('wathiq_messages',%s)",
                        (
                            json.dumps(
                                {
                                    "delivery_id": identity,
                                    "recipient_user_id": rid,
                                    "mailbox_sequence": 2,
                                }
                            ),
                        ),
                    )
                    database.commit()
            # Restart one API. A new committed message during the gap is recovered
            # through REST or the stream's initial reconciliation handshake.
            old = processes[0]
            args = old.args
            old.terminate()
            old.wait(10)
            gap = post(client, sender, payload(rid)).json()
            processes[0] = subprocess.Popen(
                args,
                cwd=ROOT,
                env={**os.environ, "MESSAGING_STREAM_HEARTBEAT_SECONDS": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for(
                lambda: all(
                    (folders[i] / "cursor").exists()
                    and int((folders[i] / "cursor").read_text()) >= 3
                    for i in range(2)
                )
            )
            # Restart the frontend process with the same durable page checkpoint.
            workers[0].terminate()
            workers[0].wait(10)
            workers[0] = start(urls[0], "ws", 0)
            final = post(client, sender, payload(rid)).json()
            wait_for(
                lambda: all(
                    int((folders[i] / "cursor").read_text()) == 4 for i in range(2)
                )
            )
            for i in range(2):
                assert effects(i).count({"kind": "message", "value": identity}) == 1
                assert (
                    sum(x["value"] for x in effects(i) if x["kind"] == "summary") <= 3
                )
                assert not any(isinstance(x["value"], dict) for x in effects(i))
        finally:
            for worker in workers:
                worker.terminate()
            for worker in workers:
                try:
                    worker.wait(10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
