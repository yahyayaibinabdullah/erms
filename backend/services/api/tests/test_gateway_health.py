"""GH-001–007: runner-owned disposable databases only, including real gateways."""

import asyncio
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import socket
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx

from .test_messaging import account, db, PREFIX
from .test_global_privilege_enforcement import _bearer
from .test_messaging_phase3 import gateways
from backend.services.api.messaging import gateway_health as health
from backend.services.api.messaging.operations import Worker
from backend.services.api.messaging.realtime import Gateway


def report(c, *, age="0 seconds", connected=True, endpoint=True):
    identity = uuid4()
    c.execute(
        """INSERT INTO messaging_gateway_health
        (instance_id,observed_at,listener_connected,listener_generation,
         notifications_received,active_connections,slow_disconnects,host_addresses,api_port)
        VALUES (%s,CURRENT_TIMESTAMP-%s::interval,%s,1,0,0,0,%s::inet[],%s)""",
        (identity, age, connected, ["127.0.0.1"] if endpoint else None, 8001 if endpoint else None),
    )
    return identity


def monitor_page(client, token, **params):
    response = client.get(PREFIX + "/monitor/gateways", headers=_bearer(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_fixed_time_boundaries_and_retirement(client):
    with db() as c:
        ids = [report(c, age=age, connected=False) for age in (
            "45 seconds", "45.000001 seconds", "23 hours 59 minutes 59.999999 seconds", "24 hours"
        )]
        rows = c.execute(
            f"SELECT instance_id,{health.HEALTH_STATUS_SQL} AS status,{health.CURRENT_REPORT_SQL} AS current FROM messaging_gateway_health WHERE instance_id=ANY(%s)",
            (ids,),
        ).fetchall()
        result = {r["instance_id"]: r for r in rows}
        assert [result[i]["status"] for i in ids[:3]] == ["disconnected", "overdue", "overdue"]
        assert [result[i]["current"] for i in ids] == [True, True, True, False]
        assert health.retire_expired(c) >= 1
        remaining = c.execute("SELECT instance_id FROM messaging_gateway_health WHERE instance_id=ANY(%s)", (ids,)).fetchall()
        assert {r["instance_id"] for r in remaining} == set(ids[:3])


def test_paged_health_identity_and_privilege_isolation(client):
    token, _, _ = account(client, privileges=("messaging.monitor",))
    denied, _, _ = account(client, privileges=("messaging.user_messages.exchange",))
    with db() as c:
        connected = report(c)
        disconnected = report(c, connected=False)
        overdue = report(c, age="1 minute", endpoint=False)
        retired = report(c, age="24 hours")
    seen = {}
    after = ""
    while True:
        page = monitor_page(client, token, limit=1, after=after)
        assert len(page["items"]) <= 1
        seen.update({r["instance_id"]: r for r in page["items"]})
        after = page["next_cursor"]
        if not after:
            break
    assert str(retired) not in seen
    assert seen[str(connected)]["health_status"] == "connected"
    assert seen[str(disconnected)]["health_status"] == "disconnected"
    assert seen[str(disconnected)]["host_addresses"] == ["127.0.0.1"]
    assert seen[str(disconnected)]["api_port"] == 8001
    assert seen[str(overdue)]["health_status"] == "overdue"
    assert seen[str(overdue)]["host_addresses"] == [] and seen[str(overdue)]["api_port"] is None
    assert all("observed_at" in r for r in seen.values())
    assert client.get(PREFIX + "/monitor/gateways", headers=_bearer(denied)).status_code == 403
    with db() as c:
        c.execute("UPDATE messaging_gateway_health SET listener_connected=true,observed_at=CURRENT_TIMESTAMP WHERE instance_id=ANY(%s)", ([disconnected, overdue],))
    assert all(r["health_status"] == "connected" for r in monitor_page(client, token)["items"] if r["instance_id"] in {str(disconnected), str(overdue)})


def test_snapshot_retirement_recreation_and_own_shutdown(client, monkeypatch):
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8002")
    gateway = Gateway()
    gateway.ready = True
    worker = Worker(gateway)
    with db() as c:
        expired = report(c, age="2 days")
        survivor = report(c)
    worker.snapshot()
    with db() as c:
        assert c.execute("SELECT 1 FROM messaging_gateway_health WHERE instance_id=%s", (expired,)).fetchone() is None
        row = c.execute("SELECT * FROM messaging_gateway_health WHERE instance_id=%s", (worker.instance_id,)).fetchone()
        assert list(map(str, row["host_addresses"])) == ["127.0.0.1"] and row["api_port"] == 8002
        c.execute("UPDATE messaging_gateway_health SET observed_at=CURRENT_TIMESTAMP-interval '24 hours' WHERE instance_id=%s", (worker.instance_id,))
        health.retire_expired(c)
    worker.snapshot()
    with db() as c:
        assert c.execute("SELECT 1 FROM messaging_gateway_health WHERE instance_id=%s", (worker.instance_id,)).fetchone()
    asyncio.run(worker.stop())
    with db() as c:
        assert c.execute("SELECT 1 FROM messaging_gateway_health WHERE instance_id=%s", (worker.instance_id,)).fetchone() is None
        assert c.execute("SELECT 1 FROM messaging_gateway_health WHERE instance_id=%s", (survivor,)).fetchone()


def test_cleanup_preserves_concurrent_heartbeat(client):
    with db() as c:
        identity = report(c, age="2 days")
    with db() as update, ThreadPoolExecutor(max_workers=1) as executor:
        update.execute("UPDATE messaging_gateway_health SET observed_at=CURRENT_TIMESTAMP WHERE instance_id=%s", (identity,))
        def cleanup():
            with db() as c:
                c.execute("SET application_name='gateway-retirement-test'")
                return health.retire_expired(c)
        pending = executor.submit(cleanup)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with db() as probe:
                    waiting = probe.execute("SELECT 1 FROM pg_stat_activity WHERE application_name='gateway-retirement-test' AND wait_event_type='Lock'").fetchone()
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "cleanup did not reach the locked old report"
        finally:
            update.commit()
        pending.result(timeout=5)
    with db() as c:
        assert c.execute("SELECT 1 FROM messaging_gateway_health WHERE instance_id=%s", (identity,)).fetchone()


def test_runtime_identity_concrete_wildcard_and_failure(client, monkeypatch):
    monkeypatch.setenv("API_PORT", "8123")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    assert health.endpoint_identity() == (["127.0.0.1"], 8123)
    monkeypatch.setenv("API_HOST", "::1")
    assert health.endpoint_identity() == (["::1"], 8123)
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setattr(health.psutil, "net_if_stats", lambda: {"lo": SimpleNamespace(isup=True), "lan": SimpleNamespace(isup=True), "off": SimpleNamespace(isup=False)})
    monkeypatch.setattr(health.psutil, "net_if_addrs", lambda: {
        "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
        "lan": [SimpleNamespace(family=socket.AF_INET, address="10.0.0.2"), SimpleNamespace(family=socket.AF_INET6, address="::1")],
        "off": [SimpleNamespace(family=socket.AF_INET, address="10.0.0.3")],
    })
    assert health.endpoint_identity() == (["10.0.0.2", "127.0.0.1"], 8123)
    monkeypatch.setenv("API_HOST", "::")
    assert health.endpoint_identity() == (["10.0.0.2", "127.0.0.1", "::1"], 8123)
    def failed():
        raise OSError("network discovery failed")
    monkeypatch.setattr(health.psutil, "net_if_addrs", failed)
    assert health.endpoint_identity() == ([], 8123)


def test_two_live_gateways_separate_reports_and_process_exit(client):
    token, _, _ = account(client, privileges=("messaging.monitor",))
    with gateways() as (urls, processes):
        ports = [int(url.rsplit(":", 1)[1]) for url in urls]
        deadline = time.monotonic() + 20
        while True:
            rows = monitor_page(client, token)["items"]
            pair = {r["api_port"]: r for r in rows if r["api_port"] in ports}
            if len(pair) == 2 and all(r["health_status"] == "connected" for r in pair.values()):
                break
            assert time.monotonic() < deadline, rows
            time.sleep(0.1)
        assert pair[ports[0]]["instance_id"] != pair[ports[1]]["instance_id"]
        for row in pair.values():
            assert row["host_addresses"] == ["127.0.0.1"]
        print("Two live gateway reports:", {p: {k: r[k] for k in ("instance_id", "host_addresses", "api_port", "health_status", "observed_at")} for p, r in pair.items()})
        processes[0].terminate()
        processes[0].wait(timeout=10)
        assert not any(r["instance_id"] == pair[ports[0]]["instance_id"] for r in monitor_page(client, token)["items"])
        assert httpx.get(urls[1] + "/health").json()["messaging_realtime"]["listener_connected"]
        processes[1].kill()
        processes[1].wait(timeout=5)
        identity = pair[ports[1]]["instance_id"]
        with db() as c:
            c.execute("UPDATE messaging_gateway_health SET observed_at=CURRENT_TIMESTAMP-interval '1 minute' WHERE instance_id=%s", (identity,))
        row = next(r for r in monitor_page(client, token)["items"] if r["instance_id"] == identity)
        assert row["health_status"] == "overdue" and row["api_port"] == ports[1]
        with db() as c:
            c.execute("UPDATE messaging_gateway_health SET observed_at=CURRENT_TIMESTAMP-interval '24 hours' WHERE instance_id=%s", (identity,))
            health.retire_expired(c)
        assert not any(r["instance_id"] == identity for r in monitor_page(client, token)["items"])


def test_one_real_listener_failure_and_recovery_does_not_hide_other(client, monkeypatch):
    token, _, _ = account(client, privileges=("messaging.monitor",))
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8124")

    async def scenario():
        a, b = Gateway(), Gateway()
        wa, wb = Worker(a), Worker(b)
        wa.start()
        wb.start()
        a.start()
        b.start()

        async def wait_for_report(worker, connected):
            def matches():
                with db() as c:
                    row = c.execute(
                        "SELECT listener_connected FROM messaging_gateway_health WHERE instance_id=%s",
                        (worker.instance_id,),
                    ).fetchone()
                    return row is not None and row["listener_connected"] == connected

            # Well below the 15-second heartbeat: transitions must wake reporting.
            async with asyncio.timeout(5):
                while not await asyncio.to_thread(matches):
                    await asyncio.sleep(0.01)

        try:
            async with asyncio.timeout(5):
                while not (a.ready and b.ready):
                    await asyncio.sleep(0.01)
            await wait_for_report(wa, True)
            await wait_for_report(wb, True)
            await a.stop()
            await wait_for_report(wa, False)
            pair = {r["instance_id"]: r for r in monitor_page(client, token)["items"]}
            assert pair[str(wa.instance_id)]["health_status"] == "disconnected"
            assert pair[str(wb.instance_id)]["health_status"] == "connected"
            assert pair[str(wa.instance_id)]["api_port"] == pair[str(wb.instance_id)]["api_port"] == 8124
            a.start()
            async with asyncio.timeout(5):
                while not a.ready:
                    await asyncio.sleep(0.01)
            await wait_for_report(wa, True)
            assert next(r for r in monitor_page(client, token)["items"] if r["instance_id"] == str(wa.instance_id))["health_status"] == "connected"
            assert a.generation == 2 and b.generation == 1
        finally:
            await wa.stop()
            await wb.stop()
            await a.stop()
            await b.stop()

    asyncio.run(scenario())


def test_health_transition_during_snapshot_is_not_lost(client, monkeypatch):
    async def scenario():
        gateway = Gateway()
        worker = Worker(gateway)
        reports = []
        reported = asyncio.Event()
        loop = asyncio.get_running_loop()

        def snapshot():
            reports.append(gateway.ready)
            if len(reports) == 1:
                # A connection completes while the old state is being persisted.
                gateway.ready = True
                loop.call_soon_threadsafe(gateway.health_changed.set)
            else:
                loop.call_soon_threadsafe(reported.set)

        monkeypatch.setattr(worker, "snapshot", snapshot)
        worker.start()
        try:
            await asyncio.wait_for(reported.wait(), 2)
            assert reports == [False, True]
            await asyncio.sleep(0.05)
            assert reports == [False, True]  # Consumed wake must not spin.
        finally:
            await worker.stop()

    asyncio.run(scenario())


def test_new_arabic_entries_seed_with_their_own_generation_provenance(client):
    from backend.services.api.localization import synchronize_generated_arabic_drafts

    result = synchronize_generated_arabic_drafts()
    assert result["failed"] == 0 and result["awaiting_generation"] == 0
    with db() as c:
        row = c.execute("SELECT origin,status,generation_metadata FROM ui_message_translations WHERE language_tag='ar' AND message_key='messaging.monitor.overdue'").fetchone()
        artifact = json.loads((Path(__file__).resolve().parents[4] / "frontend/webui/i18n/messages.ar.generated.json").read_text())
        canonical = next(item for item in artifact["items"] if item["message_key"] == 'messaging.monitor.overdue')
        assert row["origin"] == "imported" and row["status"] == "draft"
        assert row["generation_metadata"]["export_provenance"] == canonical["provenance"]
        assert canonical["provenance"]["source_origin"] == "generated"
        old = c.execute("SELECT origin,generation_metadata FROM ui_message_translations WHERE language_tag='ar' AND message_key='messaging.monitor.disconnected'").fetchone()
        assert old["origin"] == "imported"
        assert old["generation_metadata"]["export_provenance"]["kind"] == "admin_catalogue_export"
