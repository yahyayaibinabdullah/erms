"""Exercise converted PDF ranges through the authorized saved-record and draft routes."""
import os
from uuid import uuid4

import psycopg
import pytest

from backend.services.api import converted_previews as previews, session_cleanup
from backend.services.api.tests.test_phase7_mutation_authorization import (
    _grant_principal, _login_as_phase7, _set_record_acl,
)
from backend.services.api.tests.test_staged_component_preview import stage, url

SOURCE = b"editable document"
PDF = b"%PDF-" + bytes(range(256)) * 2100


@pytest.fixture
def conversions(monkeypatch):
    calls = []

    def convert(source, workspace, settings):
        calls.append(source.read_bytes())
        output = workspace / "render.pdf"
        output.write_bytes(PDF)
        return output, "libreoffice"

    monkeypatch.setattr(previews.document_conversion, "convert_file", convert)
    return calls


def open_document(client, path):
    receipt = str(uuid4())
    opening = {"X-Wathiq-Open-PDF": "1", "X-Wathiq-Converted-PDF": receipt, "X-Request-ID": receipt}
    opened = client.head(path, headers=opening)
    assert opened.status_code == 200, opened.headers
    assert opened.headers["content-length"] == str(len(PDF))
    assert client.head(path, headers=opening).headers["etag"] == opened.headers["etag"]
    return {"X-Wathiq-Converted-PDF": receipt, "If-Match": opened.headers["etag"]}


def upload(client, record):
    result = client.post(f"/api/v1/records/{record['id']}/digital-components/upload",
                         data={"component_order": "1"}, files={"file": ("letter.docx", SOURCE, "application/octet-stream")})
    result.raise_for_status()
    item = result.json()
    return item, f"/api/v1/digital-components/{item['id']}/rendition"


@pytest.mark.parametrize("draft", [False, True])
def test_convert_once_serve_exact_ranges_and_release(client, record, aggregation, draft, conversions):
    if draft:
        parent, item = stage(client, aggregation, name="letter.docx", content=SOURCE, mime="application/octet-stream")
        path = url(parent, item)
    else:
        item, path = upload(client, record)
    headers = open_document(client, path)
    for first, end in [(0, 5), (262140, 262152), (len(PDF)-18, len(PDF))]:
        result = client.get(path, headers={**headers, "Range": f"bytes={first}-{end-1}"})
        assert result.status_code == 206 and result.content == PDF[first:end]
        assert result.headers["content-range"] == f"bytes {first}-{end-1}/{len(PDF)}"
        assert result.headers["accept-ranges"] == "bytes" and "no-store" in result.headers["cache-control"]
    assert client.get(path, headers=headers).content == PDF
    assert client.get(path, headers={**headers, "If-Match": '"wrong"'}).status_code == 412
    invalid = client.get(path, headers={**headers, "Range": f"bytes={len(PDF)}-"})
    assert invalid.status_code == 416 and invalid.headers["content-range"] == f"bytes */{len(PDF)}"
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(path, headers=headers).status_code == 412
    assert conversions == [SOURCE]
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(*) FROM preview_rendition_chunks").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM event_history WHERE operation='CONTENT_VIEWED'").fetchone()[0] == int(not draft)


def test_saved_access_replacement_and_expiry(client, record, conversions):
    item, path = upload(client, record)
    old = open_document(client, path)
    replacement = client.put(path.replace("/rendition","/content"), headers={"If-Match": str(item["version"])},
                             files={"file": ("new.docx", b"replacement", "application/octet-stream")})
    assert replacement.status_code == 200
    assert client.get(path, headers=old).status_code == 412
    current = open_document(client, path)
    _, role = _grant_principal({"record.view", "record.component.list", "record.component.view"})
    _set_record_acl(record["id"], role, {"record.view", "record.component.list", "record.component.view"})
    _login_as_phase7(client)
    assert client.get(path, headers=current).status_code == 412
    own = open_document(client, path)
    _set_record_acl(record["id"], role, {"record.view", "record.component.list"})
    for method in [client.get, client.head, client.delete]:
        assert method(path, headers=own).status_code == 403
    _set_record_acl(record["id"], role, {"record.view", "record.component.list", "record.component.view"})
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute("UPDATE preview_renditions SET expires_at=now()")
    assert client.get(path, headers=own).status_code == 412
    session_cleanup._run_due_passes(session_cleanup.CleanupSchedule())
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(*) FROM preview_rendition_chunks").fetchone()[0] == 0


def test_discard_removes_converted_draft(client, aggregation, conversions):
    draft, item = stage(client, aggregation, name="letter.docx", content=SOURCE, mime="application/octet-stream")
    path = url(draft, item)
    own = open_document(client, path)
    assert client.delete(f"/api/v1/record-drafts/{draft['id']}").status_code == 204
    assert client.get(path, headers=own).status_code == 404
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(*) FROM preview_renditions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM preview_rendition_chunks").fetchone()[0] == 0


def test_new_open_reclaims_an_abandoned_copy_and_conversion_failure_leaves_no_bytes(client, record, conversions, monkeypatch):
    _, path = upload(client, record)
    abandoned = open_document(client, path)
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        db.execute("UPDATE preview_renditions SET expires_at=now()")
    fresh = open_document(client, path)
    assert client.head(path, headers=abandoned).status_code == 412
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT DISTINCT open_id FROM preview_rendition_chunks").fetchall() == [
            (previews.open_id(fresh["X-Wathiq-Converted-PDF"]),)
        ]

    def fail(source, workspace, settings):
        raise previews.document_conversion.ConversionUnavailable("conversion failed")

    monkeypatch.setattr(previews.document_conversion, "convert_file", fail)
    identity = str(uuid4())
    assert client.head(path, headers={"X-Wathiq-Open-PDF": "1", "X-Wathiq-Converted-PDF": identity,
                                      "X-Request-ID": identity}).status_code == 503
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(*) FROM preview_renditions WHERE open_id=%s", (identity,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM disposition_private.processing_copies").fetchone()[0] == 0


def test_non_owner_cannot_read_or_release_converted_draft(client, aggregation, conversions):
    draft, item = stage(client, aggregation, name="letter.docx", content=SOURCE, mime="application/octet-stream")
    path = url(draft, item)
    own = open_document(client, path)
    _grant_principal({"record.create", "aggregation.view"})
    _login_as_phase7(client)
    for method in (client.get, client.head, client.delete):
        assert method(path, headers=own).status_code == 404


def test_retry_shares_one_rendition_but_independent_opens_do_not(client, record, conversions):
    from concurrent.futures import ThreadPoolExecutor
    _, path = upload(client, record)
    receipt = str(uuid4())
    retry = {"X-Wathiq-Open-PDF": "1", "X-Wathiq-Converted-PDF": receipt, "X-Request-ID": receipt}
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: client.head(path, headers=retry), range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].headers["etag"] == results[1].headers["etag"]
    assert conversions == [SOURCE]
    independent = open_document(client, path)
    assert independent["X-Wathiq-Converted-PDF"] != receipt
    assert conversions == [SOURCE, SOURCE]
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(DISTINCT open_id) FROM preview_rendition_chunks").fetchone()[0] == 2
    assert client.delete(path, headers=independent).status_code == 204
    assert client.get(path, headers={"X-Wathiq-Converted-PDF": receipt, "If-Match": results[0].headers["etag"],
                                     "Range": "bytes=-10"}).content == PDF[-10:]


def test_second_api_process_serves_existing_open(client, record, conversions):
    import json
    import subprocess
    import sys
    from backend.services.api.authentication import SESSION_COOKIE

    _, path = upload(client, record)
    headers = open_document(client, path)
    # A separate application lifespan and pool see only committed PostgreSQL rows.
    probe = """
import json, sys
from fastapi.testclient import TestClient
from backend.services.api.main import app
from backend.services.api.authentication import SESSION_COOKIE
from backend.services.api import document_conversion
def unexpected_conversion(*args):
    raise AssertionError('a range request started another converter')
document_conversion.convert_file = unexpected_conversion
path, session, headers = json.load(sys.stdin)
with TestClient(app) as other:
    other.cookies.set(SESSION_COOKIE, session)
    response = other.get(path, headers={**headers, 'Range': 'bytes=0-4'})
    assert response.status_code == 206 and response.content == b'%PDF-'
"""
    subprocess.run([sys.executable, "-c", probe], text=True, check=True, timeout=60,
                   input=json.dumps([path, client.cookies[SESSION_COOKIE], headers]))
    assert conversions == [SOURCE]


def test_viewer_reselect_renew_and_release(client, record, conversions):
    _, path = upload(client, record)
    first = open_document(client, path)
    second_viewer = open_document(client, path)
    ids = [first["X-Wathiq-Converted-PDF"]]
    reselect = {"X-Wathiq-Open-PDF": "reuse", "X-Wathiq-Converted-PDF": ids[0], "X-Request-ID": str(uuid4())}
    for _ in range(2):
        assert client.head(path, headers=reselect).headers["etag"] == first["If-Match"]
    assert len(conversions) == 2
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT count(*) FROM event_history WHERE operation='CONTENT_VIEWED'").fetchone() == (3,)
        db.execute("UPDATE preview_renditions SET expires_at=now()+interval '1 minute' WHERE open_id=%s", ids)
        last_seen = db.execute("UPDATE login_sessions SET last_seen_at=now()-interval '2 minutes' RETURNING last_seen_at").fetchone()
    assert client.post("/api/v1/preview-renditions/renew", json=ids).status_code == 204
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT last_seen_at FROM login_sessions").fetchone() == last_seen
        remaining = db.execute("SELECT expires_at - statement_timestamp() FROM preview_renditions WHERE open_id=%s", ids).fetchone()[0]
        assert 590 < remaining.total_seconds() <= 600
        db.execute("UPDATE preview_renditions SET expires_at=now()-interval '1 minute' WHERE open_id=%s", ids)
    assert client.post("/api/v1/preview-renditions/renew", json=ids).status_code == 204
    assert client.head(path, headers=reselect).status_code == 412
    assert client.post("/api/v1/preview-renditions/release", json=ids).status_code == 204
    assert client.head(path, headers=reselect).status_code == 412
    assert client.head(path, headers=second_viewer).status_code == 200
    assert len(conversions) == 2
    foreign = [second_viewer["X-Wathiq-Converted-PDF"]]
    _, _role = _grant_principal({"record.view"})
    _login_as_phase7(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        before = db.execute("SELECT expires_at FROM preview_renditions WHERE open_id=%s", foreign).fetchone()
    for action in ("renew", "release"):
        assert client.post("/api/v1/preview-renditions/" + action, json=foreign).status_code == 204
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        assert db.execute("SELECT expires_at FROM preview_renditions WHERE open_id=%s", foreign).fetchone() == before
    client.cookies.clear()
    for action in ("renew", "release"):
        assert client.post("/api/v1/preview-renditions/" + action, json=foreign).status_code == 401
