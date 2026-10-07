"""Phase 5 lifecycle/capture acceptance; disposable database runner only."""

from uuid import UUID
from .test_messaging import account, db, payload, post, PREFIX
from .test_global_privilege_enforcement import _bearer
from backend.services.api.messaging.retention import purge_group


def age(envelopes, days):
    # Test clock fixture only: production cannot edit immutable expiry.
    with db() as c:
        c.execute(
            "ALTER TABLE message_envelopes DISABLE TRIGGER message_envelopes_immutable"
        )
        c.execute(
            "UPDATE message_envelopes SET sent_at=CURRENT_TIMESTAMP-interval '10 years',expires_at=CURRENT_TIMESTAMP-make_interval(days=>%s) WHERE id=ANY(%s::uuid[])",
            (days, envelopes),
        )
        c.execute(
            "ALTER TABLE message_envelopes ENABLE TRIGGER message_envelopes_immutable"
        )


def test_mailbox_expiry_restore_deadline_and_early_capture_gate(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    sent = post(client, sender, payload(rid)).json()
    did = sent["deliveries"][0]["id"]
    eid = sent["envelope_id"]
    url = PREFIX + "/inbox/" + did
    assert client.delete(url, headers=_bearer(recipient)).status_code == 409
    age([eid], 1)
    assert client.get(url, headers=_bearer(recipient)).status_code == 404
    items = client.get(
        PREFIX + "/recently-deleted/inbox", headers=_bearer(recipient)
    ).json()["items"]
    assert len(items) == 1
    deadline = items[0]["restorable_until"]
    for _ in range(2):
        restored = client.post(url + "/restore", headers=_bearer(recipient))
        assert restored.status_code == 200, restored.text
        assert restored.json()["restorable_until"] == deadline
        assert client.get(url, headers=_bearer(recipient)).status_code == 200
        assert client.delete(url, headers=_bearer(recipient)).status_code == 200
    assert (
        client.get(PREFIX + "/outbox/" + eid, headers=_bearer(sender)).status_code
        == 404
    )


def test_branched_group_retained_then_purged_atomically_and_replay(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original_payload = payload(rid)
    original = post(client, sender, original_payload).json()
    branches = [
        post(
            client,
            recipient,
            payload(
                uid,
                relationship_kind="reply",
                related_delivery_id=original["deliveries"][0]["id"],
            ),
        ).json()
        for _ in range(2)
    ]
    ids = [original["envelope_id"]] + [r["envelope_id"] for r in branches]
    age(ids[:2], 40)
    with db() as c:
        assert purge_group(c, UUID(ids[0])) == 0
    age(ids, 40)
    with db() as c:
        assert purge_group(c, UUID(ids[0])) == 3
    with db() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_envelopes WHERE id=ANY(%s::uuid[])",
                (ids,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_deliveries WHERE envelope_id=ANY(%s::uuid[])",
                (ids,),
            ).fetchone()["n"]
            == 0
        )
    assert post(client, sender, original_payload).status_code == 410
    catchup = client.get(
        PREFIX + "/catch-up?after=0", headers=_bearer(recipient)
    ).json()
    assert not catchup["items"] and catchup["next_cursor"] > 0


def test_capture_commits_ordered_validated_record_and_survives_purge(
    client, aggregation, monkeypatch, tmp_path
):
    import os
    from backend.services.api.messaging import capture_pdf

    # Integration requires the independent validator, never a mocked pass.
    assert os.environ.get(
        "MESSAGING_PDF_VALIDATOR"
    ), "Set the installed veraPDF executable"
    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    original = post(client, sender, payload(1)).json()
    selected = post(
        client,
        admin,
        payload(
            uid,
            action_required=True,
            relationship_kind="reply",
            related_delivery_id=original["deliveries"][0]["id"],
        ),
    ).json()
    response = client.post(
        PREFIX + "/" + selected["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft['medium'] == 'digital'
    with db() as c:
        selected_row = c.execute('SELECT sent_at,security_level_id FROM message_envelopes WHERE id=%s',
                                 (selected['envelope_id'],)).fetchone()
    from datetime import datetime
    assert datetime.fromisoformat(draft['date_originated'].replace('Z','+00:00')) == selected_row['sent_at']
    assert draft['security_level_id'] == selected_row['security_level_id']
    path = "/api/v1/record-drafts/" + str(draft["id"])
    for invalid_medium in ('mixed', 'physical', None):
        rejected = client.patch(path, headers=_bearer(admin), json={'medium':invalid_medium})
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()['detail']['code'] == 'message_capture_medium_fixed_digital'
    assert client.get(path, headers=_bearer(admin)).json()['medium'] == 'digital'
    assert (
        client.patch(
            path,
            headers=_bearer(admin),
            json={"aggregation_id": aggregation["id"], "record_number": "CAPTURE-1"},
        ).status_code
        == 200
    )
    committed = client.post(path + "/commit", headers=_bearer(admin))
    assert committed.status_code == 201, committed.text
    record = committed.json()
    with db() as c:
        cap = c.execute(
            "SELECT * FROM message_record_captures WHERE record_id=%s", (record["id"],)
        ).fetchone()
        components = c.execute(
            "SELECT * FROM message_record_capture_components WHERE capture_id=%s ORDER BY component_order",
            (cap["id"],),
        ).fetchall()
        assert (
            len(components) == 3
            and components[0]["is_selected_message"]
            and components[-1]["component_kind"] == "provenance"
        )
        assert str(components[1]["envelope_id"]) == original["envelope_id"]
        from backend.services.api.content_storage import configured_storage
        import subprocess

        evidence = tmp_path / "committed"
        evidence.mkdir(parents=True, exist_ok=True)
        preserved = {}
        for component in components:
            data = configured_storage().read(c, component["digital_component_id"])
            preserved[component["digital_component_id"]] = data
            path = evidence / (
                str(component["component_order"])
                + "-"
                + component["component_kind"]
                + ".pdf"
            )
            path.write_bytes(data)
            extracted = subprocess.check_output(
                ["pdftotext", str(path), "-"], text=True
            )
            if component["component_kind"] == "provenance":
                assert str(cap["id"]) in extracted
                assert str(record["record_number"]) in extracted
                assert selected["envelope_id"] in extracted
            else:
                assert "Durable message" in extracted

    from uuid import uuid4

    amended = client.post(
        PREFIX + "/outbox/" + selected["envelope_id"] + "/amendments",
        headers=_bearer(admin),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "due_date_added",
            "due_date": "2031-01-01",
            "reason": "After capture",
        },
    )
    assert amended.status_code == 200, amended.text
    staged = client.post(
        PREFIX + "/" + selected["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert staged.status_code == 201, staged.text
    staged_id = staged.json()["id"]
    with db() as c:
        parts = c.execute(
            "SELECT b.content FROM record_draft_component_blobs b JOIN record_draft_components x ON x.id=b.record_draft_component_id WHERE x.draft_id=%s AND x.component_order=1 ORDER BY b.segment_no",
            (staged_id,),
        ).fetchall()
        amended_path = evidence / "amended-message.pdf"
        amended_path.write_bytes(b"".join(bytes(part["content"]) for part in parts))
        amended_text = subprocess.check_output(
            ["pdftotext", str(amended_path), "-"], text=True
        )
        assert all(
            value in amended_text
            for value in (
                "After capture",
                "2031-01-01",
                "Previous action state",
                "Effective action state at capture",
            )
        )
    with db() as c:
        assert all(
            configured_storage().read(c, identity) == data
            for identity, data in preserved.items()
        )
        notice = c.execute(
            "SELECT id FROM message_envelopes WHERE message_kind='action_amendment_notice'"
        ).fetchone()["id"]
    assert (
        client.post(
            PREFIX + "/" + str(notice) + "/capture", headers=_bearer(admin)
        ).status_code
        == 409
    )
    assert (
        client.delete(
            PREFIX + "/inbox/" + selected["deliveries"][0]["id"],
            headers=_bearer(sender),
        ).status_code
        == 409
    )
    assert (
        client.delete(
            PREFIX + "/outbox/" + selected["envelope_id"], headers=_bearer(admin)
        ).status_code
        == 200
    )
    age([original["envelope_id"], selected["envelope_id"], str(notice)], 40)
    # Early manual deletion still has a live restoration period; cannot purge.
    with db() as c:
        assert purge_group(c, UUID(selected["envelope_id"])) == 0
    with db() as c:
        c.execute(
            "ALTER TABLE message_envelopes DISABLE TRIGGER message_envelopes_immutable"
        )
        c.execute(
            "UPDATE message_envelopes SET sender_purge_after=CURRENT_TIMESTAMP-interval '1 day' WHERE id=%s",
            (selected["envelope_id"],),
        )
        c.execute(
            "ALTER TABLE message_envelopes ENABLE TRIGGER message_envelopes_immutable"
        )
    with db() as c:
        assert purge_group(c, UUID(selected["envelope_id"])) == 3
    with db() as c:
        assert c.execute(
            "SELECT 1 FROM message_capture_drafts WHERE draft_id=%s", (staged_id,)
        ).fetchone()
    stale_path = "/api/v1/record-drafts/" + str(staged_id)
    assert (
        client.patch(
            stale_path,
            headers=_bearer(admin),
            json={
                "aggregation_id": aggregation["id"],
                "record_number": "PURGED-SOURCE",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(stale_path + "/commit", headers=_bearer(admin)).status_code == 404
    )
    with db() as c:
        cap = c.execute(
            "SELECT * FROM message_record_captures WHERE record_id=%s", (record["id"],)
        ).fetchone()
        assert (
            cap["selected_envelope_id"] is None
            and str(cap["selected_envelope_id_at_capture"]) == selected["envelope_id"]
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM digital_components WHERE record_id=%s",
                (record["id"],),
            ).fetchone()["n"]
            == 3
        )


def test_capture_validation_failure_leaves_no_partial_draft(client, monkeypatch):
    from backend.services.api.messaging import capture_pdf
    from backend.services.api.messaging.content import invalid

    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    sent = post(client, sender, payload(1)).json()
    monkeypatch.setattr(
        capture_pdf,
        "validate",
        lambda p, **kwargs: invalid("message_capture_pdf_nonconforming", 409),
    )
    result = client.post(
        PREFIX + "/" + sent["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert result.status_code == 409, result.text
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM record_drafts").fetchone()["n"] == 0
        assert (
            c.execute("SELECT count(*) AS n FROM message_record_captures").fetchone()[
                "n"
            ]
            == 0
        )


def test_capture_commit_failure_and_authorization_are_atomic(
    client, aggregation, monkeypatch
):
    from backend.services.api.messaging import capture, capture_pdf
    from backend.services.api.messaging.content import invalid

    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    sent = post(client, sender, payload(1)).json()
    denied = client.post(
        PREFIX + "/" + sent["envelope_id"] + "/capture", headers=_bearer(sender)
    )
    assert denied.status_code == 403
    response = client.post(
        PREFIX + "/" + sent["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert response.status_code == 201, response.text
    path = "/api/v1/record-drafts/" + str(response.json()["id"])
    assert (
        client.patch(
            path,
            headers=_bearer(admin),
            json={"aggregation_id": aggregation["id"], "record_number": "ROLLBACK"},
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        capture, "persist", lambda *args: invalid("message_capture_integrity", 409)
    )
    failed = client.post(path + "/commit", headers=_bearer(admin))
    assert failed.status_code == 409, failed.text
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        assert (
            c.execute("SELECT count(*) AS n FROM digital_components").fetchone()["n"]
            == 0
        )
        assert (
            c.execute("SELECT count(*) AS n FROM message_record_captures").fetchone()[
                "n"
            ]
            == 0
        )
        assert c.execute("SELECT count(*) AS n FROM record_drafts").fetchone()["n"] == 1


def test_large_group_atomic_rollback_and_parallel_workers(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend.services.api.messaging.config import LIMITS

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    parent = post(client, sender, payload(rid)).json()
    ids = [parent["envelope_id"]]
    for _ in range(8):
        ids.append(
            post(
                client,
                recipient,
                payload(
                    uid,
                    relationship_kind="reply",
                    related_delivery_id=parent["deliveries"][0]["id"],
                ),
            ).json()["envelope_id"]
        )
    age(ids, 40)
    monkeypatch.setitem(LIMITS, "CLEANUP_BATCH_SIZE", 2)
    import pytest

    with pytest.raises(RuntimeError):
        with db() as c:
            assert purge_group(c, UUID(ids[0])) == 9
            raise RuntimeError("Rollback after dependent deletes")
    with db() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM message_envelopes").fetchone()["n"]
            == 9
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_request_receipts WHERE result_purged_at IS NOT NULL"
            ).fetchone()["n"]
            == 0
        )

    def worker():
        with db() as c:
            return purge_group(c, UUID(ids[0]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: worker(), range(2))) == [0, 9]


def test_draft_does_not_pin_group_and_expired_draft_cleanup(client):
    from backend.services.api.messaging.retention import cleanup_drafts

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    source = post(client, sender, payload(rid)).json()
    content = payload(
        uid,
        relationship_kind="reply",
        related_delivery_id=source["deliveries"][0]["id"],
    )
    content.pop("request_id")
    draft = client.post(PREFIX + "/drafts", headers=_bearer(recipient), json=content)
    assert draft.status_code == 200, draft.text
    age([source["envelope_id"]], 40)
    with db() as c:
        assert purge_group(c, UUID(source["envelope_id"])) == 1
    assert (
        client.get(
            PREFIX + "/drafts/" + draft.json()["id"], headers=_bearer(recipient)
        ).status_code
        == 200
    )
    from uuid import uuid4

    attempted = client.post(
        PREFIX + "/drafts/" + draft.json()["id"] + "/send",
        headers=_bearer(recipient),
        json={"request_id": str(uuid4()), "version": draft.json()["version"]},
    )
    assert attempted.status_code in (404, 409, 422), attempted.text
    with db() as c:
        c.execute("ALTER TABLE message_drafts DISABLE TRIGGER USER")
        c.execute(
            "UPDATE message_drafts SET date_created=CURRENT_TIMESTAMP-interval '1 year',date_updated=CURRENT_TIMESTAMP-interval '1 year',expires_at=CURRENT_TIMESTAMP-interval '40 days' WHERE id=%s",
            (draft.json()["id"],),
        )
        c.execute("ALTER TABLE message_drafts ENABLE TRIGGER USER")
        assert cleanup_drafts(c) == 1


def test_monitor_is_privilege_gated_and_contains_no_message_content(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    post(
        client,
        sender,
        payload(rid, subject="SECRET SUBJECT", body_rich_text="<p>SECRET BODY</p>"),
    )
    assert client.get(PREFIX + "/monitor", headers=_bearer(sender)).status_code == 403
    monitor, mid, _ = account(client, privileges=("messaging.monitor",))
    result = client.get(PREFIX + "/monitor", headers=_bearer(monitor))
    assert result.status_code == 200, result.text
    assert "SECRET" not in result.text and "recipient_user_id" not in result.text
    assert not result.json()["can_view_audit"]
    assert (
        client.get(
            PREFIX + "/monitor/gateways?limit=1", headers=_bearer(monitor)
        ).status_code
        == 200
    )
    assert client.get(PREFIX + "/inbox", headers=_bearer(monitor)).json()["items"] == []


def test_expired_ancestor_read_only_and_restoration_deadline(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    source = post(client, sender, payload(rid)).json()
    child = post(
        client,
        recipient,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=source["deliveries"][0]["id"],
        ),
    ).json()
    age([source["envelope_id"]], 40)
    root = child["envelope_id"]
    target = source["envelope_id"]
    assert (
        client.get(
            PREFIX + "/linked/" + root + "/" + target, headers=_bearer(recipient)
        ).status_code
        == 200
    )
    assert (
        client.post(
            PREFIX + "/inbox/" + source["deliveries"][0]["id"] + "/restore",
            headers=_bearer(recipient),
        ).status_code
        == 404
    )
    assert post(
        client,
        recipient,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=source["deliveries"][0]["id"],
        ),
    ).status_code in (404, 409)
    with db() as c:
        assert purge_group(c, UUID(target)) == 0


def test_capture_limits_and_staging_rollback(client, monkeypatch):
    from backend.services.api.messaging import capture, capture_pdf
    from backend.services.api.messaging.config import LIMITS
    from backend.services.api.messaging.content import invalid

    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    original = post(client, sender, payload(1)).json()
    child = post(
        client,
        admin,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=original["deliveries"][0]["id"],
        ),
    ).json()
    monkeypatch.setitem(LIMITS, "CAPTURE_MAX_LINKED_MESSAGES", 0)
    assert (
        client.post(
            PREFIX + "/" + child["envelope_id"] + "/capture", headers=_bearer(admin)
        ).status_code
        == 413
    )
    monkeypatch.setitem(LIMITS, "CAPTURE_MAX_LINKED_MESSAGES", 100)
    monkeypatch.setattr(capture_pdf, "render", lambda *a, **k: b"x" * 20)
    monkeypatch.setitem(LIMITS, "CAPTURE_MAX_PDF_BYTES", 10)
    assert (
        client.post(
            PREFIX + "/" + original["envelope_id"] + "/capture", headers=_bearer(admin)
        ).status_code
        == 413
    )
    monkeypatch.setitem(LIMITS, "CAPTURE_MAX_PDF_BYTES", 100)
    monkeypatch.setattr(
        capture, "stage", lambda *a, **k: invalid("message_capture_render_failed", 409)
    )
    assert (
        client.post(
            PREFIX + "/" + original["envelope_id"] + "/capture", headers=_bearer(admin)
        ).status_code
        == 409
    )
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM record_drafts").fetchone()["n"] == 0
        assert (
            c.execute("SELECT count(*) AS n FROM record_draft_components").fetchone()[
                "n"
            ]
            == 0
        )


def test_operational_failure_resolution_and_producer_isolation(client):
    from backend.services.api.messaging.operations import observe, resolved

    monitor, uid, _ = account(client, privileges=("messaging.monitor",))
    with db() as c:
        observe("system_failure", producer="producer-a", failure=True, connection=c)
        observe("system_seconds", 2, producer="producer-a", connection=c)
        observe("test_success", producer="producer-a", connection=c)
        observe("test_seconds", 1, producer="producer-a", connection=c)
    overview = client.get(PREFIX + "/monitor", headers=_bearer(monitor)).json()
    assert any(a.get("metric") == "system_failure" for a in overview["alerts"])
    values = []
    after = ""
    while True:
        response = client.get(
            PREFIX + "/monitor/producers", params={"limit": 1, "after": after},
            headers=_bearer(monitor),
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert len({row["producer_code"] for row in page["items"]}) <= 1
        values.extend(row for row in page["items"] if row["producer_code"] == "producer-a")
        after = page["next_cursor"]
        if not after:
            break
    assert {v["metric"] for v in values} == {
        "system_failure",
        "system_seconds",
        "test_success",
        "test_seconds",
    }
    with db() as c:
        resolved("system_failure", "producer-a", connection=c)
    assert not any(
        a.get("metric") == "system_failure"
        for a in client.get(PREFIX + "/monitor", headers=_bearer(monitor)).json()[
            "alerts"
        ]
    )


import pytest


@pytest.mark.parametrize("boundary", ["finalize", "promote", "provenance"])
def test_capture_each_commit_boundary_rolls_back(
    client, aggregation, monkeypatch, boundary
):
    from backend.services.api.messaging import capture, capture_pdf
    from backend.services.api.messaging.content import invalid
    from backend.services.api.content_storage import configured_storage

    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    source = post(client, sender, payload(1)).json()
    # Fault-injection fixtures use small bytes; real PDF conformance is tested
    # separately and this test never commits these bytes as authoritative content.
    monkeypatch.setattr(capture_pdf, "render", lambda *a, **k: b"fault-injection-only")
    result = client.post(
        PREFIX + "/" + source["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert result.status_code == 201, result.text
    path = "/api/v1/record-drafts/" + str(result.json()["id"])
    assert (
        client.patch(
            path,
            headers=_bearer(admin),
            json={"aggregation_id": aggregation["id"], "record_number": "BOUNDARY"},
        ).status_code
        == 200
    )

    def fail(*a, **k):
        invalid("message_capture_integrity", 409)

    if boundary == "finalize":
        monkeypatch.setattr(capture, "finalize_staging", fail)
    elif boundary == "promote":
        monkeypatch.setattr(type(configured_storage()), "promote_draft", fail)
    else:
        monkeypatch.setattr(capture, "persist", fail)
    response = client.post(path + "/commit", headers=_bearer(admin))
    assert response.status_code == 409, response.text
    with db() as c:
        for table in (
            "records",
            "digital_components",
            "message_record_captures",
            "message_record_capture_components",
        ):
            assert c.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"] == 0
        assert (
            c.execute("SELECT count(*) AS n FROM record_draft_components").fetchone()[
                "n"
            ]
            == 1
        )


def test_capture_rechecks_exchange_and_fixed_components(
    client, aggregation, monkeypatch
):
    from backend.services.api.messaging import capture_pdf

    admin = client.cookies["erms_session"]
    sender, uid, _ = account(client)
    source = post(client, sender, payload(1)).json()
    monkeypatch.setattr(capture_pdf, "render", lambda *a, **k: b"staged-test-only")
    response = client.post(
        PREFIX + "/" + source["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert response.status_code == 201, response.text
    path = "/api/v1/record-drafts/" + str(response.json()["id"])
    assert (
        client.patch(
            path,
            headers=_bearer(admin),
            json={"aggregation_id": aggregation["id"], "record_number": "RECHECK"},
        ).status_code
        == 200
    )
    with db() as c:
        component = c.execute(
            "SELECT id FROM record_draft_components WHERE draft_id=%s",
            (response.json()["id"],),
        ).fetchone()["id"]
    assert (
        client.delete(
            path + "/components/" + str(component), headers=_bearer(admin)
        ).status_code
        == 409
    )
    with db() as c:
        c.execute("UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=1")
    assert client.post(path + "/commit", headers=_bearer(admin)).status_code in (
        401,
        403,
    )
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0


def test_capture_security_floor_is_rechecked(client, aggregation, monkeypatch):
    from backend.services.api.messaging import capture_pdf

    admin = client.cookies["erms_session"]
    sender, uid, role = account(client)
    with db() as c:
        high = c.execute("SELECT id FROM security_levels WHERE code='S'").fetchone()[
            "id"
        ]
        low = c.execute("SELECT id FROM security_levels WHERE code='G'").fetchone()[
            "id"
        ]
        c.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=%s OR id IN(SELECT role_id FROM user_role_assignments WHERE user_id=1)",
            (high, role),
        )
    source = post(client, sender, payload(1, security_level_id=high))
    assert source.status_code == 200, source.text
    monkeypatch.setattr(capture_pdf, "render", lambda *a, **k: b"staged-test-only")
    initialized = client.post(
        PREFIX + "/" + source.json()["envelope_id"] + "/capture", headers=_bearer(admin)
    )
    assert initialized.status_code == 201, initialized.text
    assert initialized.json()["security_level_id"] == high
    path = "/api/v1/record-drafts/" + str(initialized.json()["id"])
    patched = client.patch(
        path,
        headers=_bearer(admin),
        json={
            "aggregation_id": aggregation["id"],
            "record_number": "FLOOR",
            "security_level_id": low,
        },
    )
    assert patched.status_code == 200, patched.text
    response = client.post(path + "/commit", headers=_bearer(admin))
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "message_capture_security_floor"
    ), response.text
    with db() as c:
        assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0


def test_capture_locks_coordinate_with_group_cleanup(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from backend.services.api.messaging.capture import sources

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    root = post(client, sender, payload(rid)).json()
    child = post(
        client,
        recipient,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=root["deliveries"][0]["id"],
        ),
    ).json()
    age([root["envelope_id"]], 40)
    held = Event()
    release = Event()
    started = Event()

    def capture_reader():
        with db() as c:
            c.execute("SELECT set_config('app.user_id',%s,true)", (str(rid),))
            rows = sources(
                c, rid, UUID(root["envelope_id"]), UUID(child["envelope_id"])
            )
            assert len(rows) == 1
            held.set()
            assert release.wait(2)

    def cleanup():
        started.set()
        with db() as c:
            return purge_group(c, UUID(root["envelope_id"]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        capture_future = executor.submit(capture_reader)
        assert held.wait(2)
        purge_future = executor.submit(cleanup)
        assert started.wait(2)
        release.set()
        capture_future.result()
        assert purge_future.result() == 0
    with db() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM message_envelopes").fetchone()["n"]
            == 2
        )


def test_worker_cleanup_updates_content_free_metrics(client):
    from backend.services.api.messaging.operations import cleanup_page

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    source = post(client, sender, payload(rid)).json()
    child = post(
        client,
        recipient,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=source["deliveries"][0]["id"],
        ),
    ).json()
    age([source["envelope_id"], child["envelope_id"]], 40)
    with db() as c:
        before = c.execute(
            "SELECT COALESCE(sum(value),0) AS n FROM messaging_operational_metrics WHERE metric='purged_messages'"
        ).fetchone()["n"]
        attempts = c.execute(
            "SELECT COALESCE(sum(observations),0) AS n FROM messaging_operational_metrics WHERE metric='group_size'"
        ).fetchone()["n"]
    assert cleanup_page() is None
    with db() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM message_envelopes").fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT sum(value) AS n FROM messaging_operational_metrics WHERE metric='purged_messages'"
            ).fetchone()["n"]
            == before + 2
        )
        assert (
            c.execute(
                "SELECT observations FROM messaging_operational_metrics WHERE metric='cleanup_seconds'"
            ).fetchone()["observations"]
            > 0
        )

        assert (
            c.execute(
                "SELECT sum(observations) AS n FROM messaging_operational_metrics WHERE metric='group_size'"
            ).fetchone()["n"]
            == attempts + 1
        )


def test_disposed_record_no_longer_satisfies_personal_capture_gate(client, aggregation):
    admin = client.cookies["erms_session"]
    recipient, rid, _ = account(client)
    source = post(client, admin, payload(rid)).json()
    eid = source["envelope_id"]
    created = client.post(PREFIX + "/" + eid + "/capture", headers=_bearer(admin))
    assert created.status_code == 201, created.text
    path = "/api/v1/record-drafts/" + str(created.json()["id"])
    assert (
        client.patch(
            path,
            headers=_bearer(admin),
            json={"aggregation_id": aggregation["id"], "record_number": "DISPOSED"},
        ).status_code
        == 200
    )
    committed = client.post(path + "/commit", headers=_bearer(admin))
    assert committed.status_code == 201, committed.text
    record_id = committed.json()["id"]
    # Exercise the referential outcome of records disposition, not a new
    # disposition workflow or permission bypass exposed through messaging.
    with db() as c:
        c.execute("DELETE FROM digital_components WHERE record_id=%s", (record_id,))
        c.execute("DELETE FROM records WHERE id=%s", (record_id,))
        provenance = c.execute(
            "SELECT record_id,record_id_at_capture FROM message_record_captures WHERE selected_envelope_id=%s",
            (eid,),
        ).fetchone()
        assert (
            provenance["record_id"] is None
            and provenance["record_id_at_capture"] == record_id
        )
        assert c.execute(
            "SELECT 1 FROM message_envelopes WHERE id=%s", (eid,)
        ).fetchone()
    response = client.delete(PREFIX + "/outbox/" + eid, headers=_bearer(admin))
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "message_capture_required"
    )


def test_record_destination_search_filters_before_pagination_and_browse(client, aggregation):
    child = client.post('/api/v1/aggregations', json=dict(aggregation_number='DEST-CHILD', title='Child',
                                                        parent_aggregation_id=aggregation['id'])).json()
    query = dict(limit=1, sort=[dict(field='aggregation_number', direction='asc')])
    url = '/api/v1/aggregations/search?record_creation=true&digital_only=true'
    response = client.post(url, json=query)
    assert response.status_code == 200, response.text
    assert response.json()['items']
    browse = client.get('/api/v1/browse/aggregations/'+str(aggregation['id'])+'/children',
                        params=dict(record_creation=True, digital_only=True))
    assert browse.status_code == 200, browse.text
    assert [r['id'] for r in browse.json()['items']] == [child['id']]
    closed = client.patch('/api/v1/aggregations/'+str(aggregation['id']),
                          headers={'If-Match':str(client.get('/api/v1/aggregations/'+str(aggregation['id'])).json()['version'])},
                          json=dict(date_closed=aggregation['date_created']))
    assert closed.status_code == 200, closed.text
    assert client.post(url, json=query).json()['items'] == []
    assert client.get('/api/v1/browse/aggregations/'+str(aggregation['id'])+'/children',
                      params=dict(record_creation=True, digital_only=True)).json()['items'] == []
    # Ordinary view search remains available for closed items.
    assert client.post('/api/v1/aggregations/search', json=query).json()['items']


def test_record_destination_excludes_visible_but_unusable_aggregations(client, aggregation):
    token, uid, role_id = account(client, privileges=('record.create','aggregation.view'))
    query = dict(limit=25)
    with db() as c:
        c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id) SELECT %s,'everyone',id FROM permissions WHERE code IN ('aggregation.view','aggregation.add_record') ON CONFLICT DO NOTHING", (aggregation['id'],))
    headers = _bearer(token)
    normal = client.post('/api/v1/aggregations/search',json=query,headers=headers)
    assert normal.status_code==200, normal.text
    assert aggregation['id'] in [r['id'] for r in normal.json()['items']]
    url='/api/v1/aggregations/search?record_creation=true'
    # This user's effective role belongs to another owner unit.
    assert client.post(url,json=query,headers=headers).json()['items']==[]
    with db() as c:
        c.execute('UPDATE roles SET org_unit_id=%s WHERE id=%s',(aggregation['owning_org_unit_id'],role_id))
    assert aggregation['id'] in [r['id'] for r in client.post(url,json=query,headers=headers).json()['items']]
    with db() as c:
        c.execute("DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s AND principal_type='everyone' AND permission_id=(SELECT id FROM permissions WHERE code='aggregation.add_record')",(aggregation['id'],))
    assert client.post(url,json=query,headers=headers).json()['items']==[]


def test_capture_preview_is_authorized_ordered_and_does_not_convert_or_create(client, monkeypatch):
    from backend.services.api.messaging import capture
    admin=client.cookies['erms_session']
    sender,uid,_=account(client)
    original=post(client,sender,payload(1)).json()
    selected=post(client,admin,payload(uid,relationship_kind='reply',
        related_delivery_id=original['deliveries'][0]['id'])).json()
    def unexpected_conversion(*args,**kwargs):
        raise AssertionError('Preview must not render or stage PDFs')
    monkeypatch.setattr(capture,'stage_messages',unexpected_conversion)
    response=client.get(PREFIX+'/'+selected['envelope_id']+'/capture-preview',headers=_bearer(admin))
    assert response.status_code==200,response.text
    manifest=response.json()
    assert manifest['medium']=='digital' and manifest['security_level_id']==1
    assert len(manifest['components'])==2
    assert selected['envelope_id'] in manifest['components'][0]['file_name']
    assert original['envelope_id'] in manifest['components'][1]['file_name']
    with db() as c:
        row=c.execute('SELECT subject,sent_at FROM message_envelopes WHERE id=%s',(selected['envelope_id'],)).fetchone()
        assert manifest['title']==row['subject']
        from datetime import datetime
        assert datetime.fromisoformat(manifest['date_originated'])==row['sent_at']
        for table in ('record_drafts','record_draft_components','message_capture_drafts','message_record_captures'):
            assert c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']==0
    outsider,_,_=account(client)
    denied=client.get(PREFIX+'/'+selected['envelope_id']+'/capture-preview',headers=_bearer(outsider))
    assert denied.status_code in (403,404),denied.text


def test_capture_pdf_resource_names_are_authorized_for_earlier_messages(client,record,aggregation,monkeypatch,tmp_path):
    from uuid import uuid4
    from backend.services.api.messaging import capture,reading
    admin=client.cookies['erms_session']
    recipient,uid,_=account(client)
    tokens=[str(uuid4()),str(uuid4())]
    original=post(client,admin,payload(uid,
        body_rich_text='<p>Resources</p>'+''.join('<span data-wathiq-link="'+t+'"></span>' for t in tokens),
        resource_links=[{'link_token':tokens[0],'resource_kind':'record','target_id':record['id']},
                        {'link_token':tokens[1],'resource_kind':'aggregation','target_id':aggregation['id']}])).json()
    selected=post(client,recipient,payload(1,relationship_kind='reply',
        related_delivery_id=original['deliveries'][0]['id'])).json()
    import subprocess
    from time import monotonic
    rendered=[]
    pdfs=[]
    real_render=capture.capture_pdf.render
    def render(title,html,*args,**kwargs):
        rendered.append(html)
        pdfs.append(real_render(title,html,*args,**kwargs))
        return pdfs[-1]
    monkeypatch.setattr(capture.capture_pdf,'render',render)
    with db() as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        rows=capture.sources(c,1,selected['envelope_id'],selected['envelope_id'])
        earlier=rows[1]
        text=capture.labels(c,'en')
        capture.message_pdf(c,earlier,'en','ltr',text,monotonic()+600)
        assert 'REC-001 — Example record' in rendered[-1]
        assert 'AGG-001 — Root aggregation' in rendered[-1]
        pdf_path=tmp_path/'authorized.pdf'
        pdf_path.write_bytes(pdfs[-1])
        extracted=subprocess.check_output(['pdftotext',str(pdf_path),'-'],text=True)
        assert 'REC-001' in extracted and 'Example record' in extracted
        assert 'AGG-001' in extracted and 'Root aggregation' in extracted
        # The exact authorization projection removes inaccessible metadata.
        c.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
        inaccessible=reading.links_for(c,[dict(earlier,readable=True)])[earlier['id']]
        assert all(not item['available'] and 'number' not in item and 'title' not in item for item in inaccessible)
        capture.message_pdf(c,earlier,'en','ltr',text,monotonic()+600)
        assert 'REC-001' not in rendered[-1] and 'Example record' not in rendered[-1]
        assert 'AGG-001' not in rendered[-1] and 'Root aggregation' not in rendered[-1]
        assert text['unavailable'] in rendered[-1]
        pdf_path=tmp_path/'unavailable.pdf'
        pdf_path.write_bytes(pdfs[-1])
        extracted=subprocess.check_output(['pdftotext',str(pdf_path),'-'],text=True)
        assert 'REC-001' not in extracted and 'Example record' not in extracted
        assert 'AGG-001' not in extracted and 'Root aggregation' not in extracted


def test_capture_localizes_all_entity_names_and_provenance_in_saved_language(client,aggregation,monkeypatch,tmp_path):
    import subprocess
    import unicodedata
    from psycopg.types.json import Jsonb
    from backend.services.api.messaging import capture_pdf
    from backend.services.api.content_storage import configured_storage
    admin=client.cookies['erms_session']
    recipient,uid,role=account(client)
    with db() as c:
        unit=c.execute('SELECT org_unit_id FROM roles WHERE id=%s',(role,)).fetchone()['org_unit_id']
        c.execute("SELECT set_config('app.change_reason','Verify localized capture entity names',true)")
        for table,identity,name,arabic in [('users',1,'English Sender','مرسل'),('users',uid,'English Recipient','مستخدم'),
                ('roles',role,'English Role','دور'),('org_units',unit,'English Unit','وحدة'),
                ('security_levels',1,'English Security','سرية')]:
            c.execute(f'UPDATE {table} SET name=%s,translations=%s WHERE id=%s',(name,Jsonb({'ar':{'name':arabic}}),identity))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
    original=post(client,admin,payload(uid,subject='Authored subject',body_rich_text='<p>Authored body</p>',selectors=[
        {'selector_kind':'user','target_id':uid,'recipient_type':'to'},
        {'selector_kind':'role','target_id':role,'recipient_type':'cc'},
        {'selector_kind':'org_unit','target_id':unit,'recipient_type':'cc'}])).json()
    selected=post(client,recipient,payload(1,relationship_kind='reply',related_delivery_id=original['deliveries'][0]['id'])).json()
    # Observe the renderer input without replacing conversion or validation.
    rendered=[]
    real_render=capture_pdf.render
    def render(title,html,language,direction,**kwargs):
        rendered.append((html,language,direction))
        return real_render(title,html,language,direction,**kwargs)
    monkeypatch.setattr(capture_pdf,'render',render)
    result=client.post(PREFIX+'/'+selected['envelope_id']+'/capture',headers=_bearer(admin))
    assert result.status_code==201,result.text
    draft=result.json()
    with db() as c:
        assert c.execute('SELECT language_tag FROM message_capture_drafts WHERE draft_id=%s',(draft['id'],)).fetchone()['language_tag']=='ar'
        c.execute("UPDATE user_preferences SET language_tag='en' WHERE user_id=1")
    path='/api/v1/record-drafts/'+str(draft['id'])
    assert client.patch(path,headers=_bearer(admin),json={'aggregation_id':aggregation['id'],'record_number':'AR-CAPTURE'}).status_code==200
    committed=client.post(path+'/commit',headers=_bearer(admin))
    assert committed.status_code==201,committed.text
    assert all(language=='ar' and direction=='rtl' for _,language,direction in rendered)
    original_html=next(html for html,_,_ in rendered if 'Authored body' in html)
    for name in ['مرسل','مستخدم','دور','وحدة','سرية']:
        assert name in original_html
    assert not any(name in original_html for name in ['English Sender','English Recipient','English Role','English Unit','English Security'])
    with db() as c:
        capture=c.execute('SELECT * FROM message_record_captures WHERE record_id=%s',(committed.json()['id'],)).fetchone()
        assert capture['captured_by_name']=='مرسل'
        components=c.execute('SELECT * FROM message_record_capture_components WHERE capture_id=%s ORDER BY component_order',(capture['id'],)).fetchall()
        preserved={}
        for component in components:
            data=configured_storage().read(c,component['digital_component_id'])
            preserved[component['digital_component_id']]=data
            pdf=tmp_path/(str(component['component_order'])+'.pdf');pdf.write_bytes(data)
            text=unicodedata.normalize('NFKC',subprocess.check_output(['pdftotext',str(pdf),'-'],text=True))
            if component['component_kind']=='provenance':
                assert 'مرسل' in text and 'AR-CAPTURE' in text
            elif not component['is_selected_message']:
                assert 'Authored subject' in text and 'Authored body' in text
                for name in ['مرسل','مستخدم','دور','وحدة','سرية']:assert name in text
        c.execute("SELECT set_config('app.change_reason','Verify committed capture names stay fixed',true)")
        c.execute('UPDATE users SET translations=%s WHERE id=1',(Jsonb({'ar':{'name':'اسم جديد'}}),))
        for identity,data in preserved.items():assert configured_storage().read(c,identity)==data
        assert c.execute('SELECT captured_by_name FROM message_record_captures WHERE id=%s',(capture['id'],)).fetchone()['captured_by_name']=='مرسل'


def test_capture_entity_names_fall_back_to_message_snapshots_and_base_language(client,monkeypatch):
    from psycopg.types.json import Jsonb
    from backend.services.api.messaging import capture
    from time import monotonic
    admin=client.cookies['erms_session']
    _,uid,role=account(client)
    with db() as c:
        unit=c.execute('SELECT org_unit_id FROM roles WHERE id=%s',(role,)).fetchone()['org_unit_id']
        c.execute("SELECT set_config('app.change_reason','Prepare capture fallback names',true)")
        for table,identity,name in [('users',1,'Original Sender'),('users',uid,'Original Recipient'),('roles',role,'Original Role'),('org_units',unit,'Original Unit')]:
            c.execute(f'UPDATE {table} SET name=%s,translations=%s WHERE id=%s',(name,Jsonb({}),identity))
    result=post(client,admin,payload(uid,selectors=[{'selector_kind':'user','target_id':uid,'recipient_type':'to'},
        {'selector_kind':'role','target_id':role,'recipient_type':'cc'},{'selector_kind':'org_unit','target_id':unit,'recipient_type':'cc'}]))
    assert result.status_code==200,result.text
    rendered=[]
    monkeypatch.setattr(capture.capture_pdf,'render',lambda title,html,*args,**kwargs:rendered.append(html) or b'renderer-input-only')
    with db() as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        c.execute("SELECT set_config('app.change_reason','Change live names after immutable send',true)")
        c.execute('UPDATE users SET name=%s,translations=%s WHERE id=1',('Changed Sender',Jsonb({'ar':{'description':'وصف'}})))
        rows=capture.sources(c,1,result.json()['envelope_id'],result.json()['envelope_id'])
        capture.message_pdf(c,rows[0],'ar','rtl',capture.labels(c,'ar'),monotonic()+600)
        for name in ['Original Sender','Original Recipient','Original Role','Original Unit']:assert name in rendered[-1]
        assert 'Changed Sender' not in rendered[-1]
        c.execute('UPDATE users SET translations=%s WHERE id=1',(Jsonb({'ar':{'name':'مرسل'}}),))
        capture.message_pdf(c,rows[0],'ar-OM','rtl',capture.labels(c,'ar'),monotonic()+600)
        assert 'مرسل' in rendered[-1] and 'Original Sender' not in rendered[-1]
        capture.message_pdf(c,rows[0],'en','ltr',capture.labels(c,'en'),monotonic()+600)
        assert 'Original Sender' in rendered[-1] and 'مرسل' not in rendered[-1]
