"""Original PDF opens, immutable slices and the per-open audit contract."""

from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import psycopg
import pytest

from backend.services.api.tests.test_phase7_mutation_authorization import (
    _grant_principal,
    _login_as_phase7,
    _set_record_acl,
)
from backend.services.api.tests.test_staged_component_preview import stage, url


def upload(client, record, data):
    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1},
        files={"file": ("saved.pdf", data, "application/pdf")},
    )
    response.raise_for_status()
    return response.json()


def open_pdf(client, path):
    receipt = str(uuid4())
    headers = {"X-Request-ID": receipt, "X-Wathiq-Open-PDF": "1"}
    result = client.head(path, headers=headers)
    assert result.status_code == 200 and not result.content
    assert client.head(path, headers=headers).status_code == 200  # network retry
    return {"X-Wathiq-Preview-Event": receipt, "If-Match": result.headers["etag"]}


def test_view_receipt_rechecks_permissions_version_and_session(client, record):
    data = b"%PDF-1.7\noriginal"
    item = upload(client, record, data)
    path = f"/api/v1/digital-components/{item['id']}/rendition"
    admin = open_pdf(client, path)
    _, role = _grant_principal({"record.view", "record.component.list", "record.component.view"})
    _set_record_acl(record["id"], role, {"record.view", "record.component.list", "record.component.view"})
    _login_as_phase7(client)
    assert client.get(path, headers=admin).status_code == 412
    opened = open_pdf(client, path)
    for value, expected in [("bytes=0-3", data[:4]), ("bytes=-4", data[-4:]), ("bytes=5-", data[5:])]:
        result = client.get(path, headers={**opened, "Range": value})
        assert result.status_code == 206 and result.content == expected
    assert client.head(path, headers=opened).status_code == 200
    assert (
        client.get(path, headers={**opened, "Range": "bytes=925-"}).headers["content-range"]
        == f"bytes */{len(data)}"
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM event_history WHERE entity_id=%s AND operation='CONTENT_VIEWED'",
                (item["id"],),
            ).fetchone()[0]
            == 2
        )
    _set_record_acl(record["id"], role, {"record.view", "record.component.list"})
    for method in (client.get, client.head):
        assert method(path, headers={**opened, "Range": "bytes=1-3"}).status_code == 403


def test_replacement_invalidates_an_open_pdf(client, record):
    component = upload(client, record, b"%PDF-1.7 old")
    path = f"/api/v1/digital-components/{component['id']}"
    opened = open_pdf(client, path + "/rendition")
    result = client.put(
        path + "/content",
        headers={"If-Match": str(component["version"])},
        files={"file": ("replacement.pdf", b"%PDF-1.7 new", "application/pdf")},
    )
    assert result.status_code == 200, result.text
    assert client.get(path + "/rendition", headers={**opened, "Range": "bytes=3-5"}).status_code == 412
    assert (
        client.get(path + "/rendition", headers=open_pdf(client, path + "/rendition")).content
        == b"%PDF-1.7 new"
    )


def test_staged_irregular_segments_exclude_earlier_payloads(client, aggregation, monkeypatch):
    from backend.services.api.content_storage import PostgreSQLContentStorage
    from psycopg import Connection

    data = b"%PDF-1.7\nfirst middle last"
    draft, component = stage(client, aggregation, content=data)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        owner = component["id"]
        conn.execute(
            "DELETE FROM record_draft_component_blobs WHERE record_draft_component_id=%s", (owner,)
        )
        ids = [
            conn.execute(
                """INSERT INTO record_draft_component_blobs
                 (record_draft_component_id,segment_no,segment_size,content) VALUES (%s,%s,%s,%s) RETURNING id""",
                (owner, index, len(part), part),
            ).fetchone()[0]
            for index, part in enumerate((data[:7], data[7:18], data[18:]))
        ]
        conn.execute("UPDATE record_draft_components SET segment_count=3 WHERE id=%s", (owner,))

    reads = []
    execute = Connection.execute

    def observed(conn, query, params=None, **kwargs):
        if "substring(content FROM" in str(query):
            reads.append(tuple(params))
        return execute(conn, query, params, **kwargs)

    monkeypatch.setattr(Connection, "execute", observed)
    monkeypatch.setattr(PostgreSQLContentStorage, "read_draft", lambda *_: pytest.fail("whole-file read"))
    path = url(draft, component)
    opened = client.head(path, headers={"X-Wathiq-Open-PDF": "1"})
    assert opened.status_code == 200 and not reads
    headers = {"If-Match": opened.headers["etag"], "Range": "bytes=15-20"}
    assert client.get(path, headers=headers).content == data[15:21]
    assert reads == [(9, 3, ids[1], owner), (1, 3, ids[2], owner)]
    assert client.delete(f"/api/v1/record-drafts/{draft['id']}").status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert (
            conn.execute("SELECT count(*) FROM event_history WHERE operation='CONTENT_VIEWED'").fetchone()[
                0
            ]
            == 0
        )


def test_simultaneous_readers_get_their_own_ranges(client, record):
    data = b"%PDF-1.7\n" + bytes(range(256)) * 8192
    item = upload(client, record, data)
    path = f"/api/v1/digital-components/{item['id']}/rendition"
    views = [open_pdf(client, path) for _ in range(3)]

    def get_range(index):
        start = index * 350000
        response = client.get(path, headers={**views[index], "Range": f"bytes={start}-{start+300000}"})
        assert response.status_code == 206
        assert response.content == data[start : start + 300001]

    with ThreadPoolExecutor(max_workers=3) as workers:
        list(workers.map(get_range, range(3)))
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert conn.execute("SELECT count(*) FROM disposition_private.processing_copies").fetchone()[0] == 0
