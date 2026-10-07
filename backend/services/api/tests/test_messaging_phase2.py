import psycopg
import pytest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from .test_messaging import account, payload, post, db, PREFIX
from .test_global_privilege_enforcement import _bearer
from backend.services.api.messaging.models import Send, Amendment
from backend.services.api.messaging.service import send
from backend.services.api.messaging.transactions import run
from backend.services.api.messaging.actions import amend


def test_inbox_sent_date_range_boundaries(client):
    from datetime import timedelta
    sender, _, _ = account(client)
    recipient, rid, _ = account(client)
    result = post(client, sender, payload(rid)).json()
    with db() as c:
        sent_at = c.execute("SELECT sent_at FROM message_envelopes WHERE id=%s", (result['envelope_id'],)).fetchone()['sent_at']
    for bounds, expected in [
        ({'sent_from': sent_at.isoformat()}, True),
        ({'sent_before': sent_at.isoformat()}, False),
        ({'sent_from': (sent_at-timedelta(days=1)).isoformat(), 'sent_before': (sent_at+timedelta(days=1)).isoformat()}, True),
        ({'sent_from': (sent_at+timedelta(days=1)).isoformat()}, False),
    ]:
        response = client.get(PREFIX + '/inbox', headers=_bearer(recipient), params=bounds)
        assert response.status_code == 200
        assert bool(response.json()['items']) == expected


def test_inbox_sender_and_draft_recipient_filters(client):
    sender, sid, _ = account(client)
    other, oid, _ = account(client)
    recipient, rid, _ = account(client)
    first = post(client, sender, payload(rid)).json()
    post(client, other, payload(rid))
    response = client.get(PREFIX + '/inbox', headers=_bearer(recipient), params={'sender_user_id': sid})
    assert response.status_code == 200
    assert [item['envelope_id'] for item in response.json()['items']] == [first['envelope_id']]
    data = {k: v for k, v in payload(rid).items() if k != 'request_id'}
    created = client.post(PREFIX + '/drafts', headers=_bearer(sender), json=data)
    assert created.status_code == 200
    for target, expected in [(rid, True), (oid, False)]:
        response = client.get(PREFIX + '/drafts', headers=_bearer(sender), params={'recipient_kind': 'user', 'recipient_id': target})
        assert response.status_code == 200
        assert bool(response.json()['items']) == expected
    assert client.get(PREFIX + '/drafts', headers=_bearer(sender), params={'recipient_kind': 'user'}).status_code == 422


@pytest.mark.parametrize('kind', ['role', 'org_unit'])
def test_draft_filter_matches_selected_role_or_unit(client, kind):
    sender, _, _ = account(client)
    _, _, role_id = account(client)
    with db() as c:
        unit_id = c.execute('SELECT org_unit_id FROM roles WHERE id=%s', (role_id,)).fetchone()['org_unit_id']
    target = role_id if kind == 'role' else unit_id
    data = {k: v for k, v in payload().items() if k != 'request_id'}
    data['selectors'] = [dict(selector_kind=kind, target_id=target, recipient_type='to')]
    created = client.post(PREFIX + '/drafts', headers=_bearer(sender), json=data)
    assert created.status_code == 200
    response = client.get(PREFIX + '/drafts', headers=_bearer(sender), params={'recipient_kind': kind, 'recipient_id': target})
    assert response.status_code == 200
    assert [item['id'] for item in response.json()['items']] == [created.json()['id']]
    other_kind = 'org_unit' if kind == 'role' else 'role'
    response = client.get(PREFIX + '/drafts', headers=_bearer(sender), params={'recipient_kind': other_kind, 'recipient_id': unit_id if other_kind == 'org_unit' else role_id})
    assert response.status_code == 200 and response.json()['items'] == []


def test_relationship_access_completion_and_branches(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    outsider, oid, _ = account(client)
    original = post(client, sender, payload(rid, action_required=True)).json()
    did = original["deliveries"][0]["id"]
    eid = original["envelope_id"]
    response = post(
        client,
        recipient,
        payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=did,
            complete_action=True,
        ),
    )
    assert response.status_code == 200, response.text
    reply = response.json()
    assert (
        client.get(
            PREFIX + "/outbox/" + eid + "/recipients", headers=_bearer(sender)
        ).json()["items"][0]["action_status"]
        == "completed"
    )
    assert (
        post(
            client,
            recipient,
            payload(
                uid,
                relationship_kind="reply",
                related_delivery_id=did,
                complete_action=True,
            ),
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            outsider,
            payload(uid, relationship_kind="forward", related_delivery_id=did),
        ).status_code
        == 404
    )
    forward = post(
        client,
        sender,
        payload(oid, relationship_kind="forward", related_envelope_id=eid),
    )
    assert forward.status_code == 200, forward.text
    root = forward.json()["envelope_id"]
    linked = client.get(PREFIX + f"/linked/{root}/{eid}", headers=_bearer(outsider))
    assert linked.status_code == 200, linked.text
    assert (
        linked.json()["body_rich_text"] == "<p>Hello</p>"
        and "is_read" not in linked.json()
    )
    # Shared amendment history uses the same ancestry grant on every page.
    notice = client.post(
        PREFIX + f"/outbox/{eid}/amendments",
        headers=_bearer(sender),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "action_withdrawn",
            "reason": "No further action",
        },
    )
    assert notice.status_code == 200, notice.text
    history = client.get(
        PREFIX + f"/{eid}/amendments",
        headers=_bearer(outsider),
        params={"root_id": root, "limit": 1},
    )
    assert history.status_code == 200, history.text
    assert len(history.json()["items"]) == 1
    assert (
        client.get(PREFIX + f"/{eid}/amendments", headers=_bearer(outsider)).status_code
        == 404
    )
    assert (
        client.get(
            PREFIX + f'/{reply["envelope_id"]}/amendments',
            headers=_bearer(outsider),
            params={"root_id": root},
        ).status_code
        == 404
    )
    assert (
        client.get(
            PREFIX + f'/linked/{root}/{reply["envelope_id"]}', headers=_bearer(outsider)
        ).status_code
        == 404
    )
    assert (
        client.get(
            PREFIX + f"/linked/{root}/{eid}", headers=_bearer(recipient)
        ).status_code
        == 404
    )
    assert (
        post(
            client,
            sender,
            payload(oid, relationship_kind="follow_up", related_envelope_id=eid),
        ).status_code
        == 200
    )


def test_draft_privacy_version_and_atomic_send_retry(client):
    sender, uid, _ = account(client)
    other, rid, _ = account(client)
    draft = {k: v for k, v in payload(rid).items() if k != "request_id"}
    created = client.post(PREFIX + "/drafts", headers=_bearer(sender), json=draft)
    assert created.status_code == 200, created.text
    identity = created.json()["id"]
    version = created.json()["version"]
    assert (
        client.get(PREFIX + "/drafts/" + identity, headers=_bearer(other)).status_code
        == 404
    )
    changed = client.put(
        PREFIX + "/drafts/" + identity,
        headers={**_bearer(sender), "If-Match": str(version)},
        json={**draft, "subject": "Saved draft"},
    )
    assert changed.status_code == 200, changed.text
    assert (
        client.put(
            PREFIX + "/drafts/" + identity,
            headers={**_bearer(sender), "If-Match": str(version)},
            json=draft,
        ).status_code
        == 409
    )
    request = {"request_id": str(uuid4()), "version": changed.json()["version"]}
    sent = client.post(
        PREFIX + "/drafts/" + identity + "/send", headers=_bearer(sender), json=request
    )
    assert sent.status_code == 200, sent.text
    assert (
        client.post(
            PREFIX + "/drafts/" + identity + "/send",
            headers=_bearer(sender),
            json=request,
        ).json()
        == sent.json()
    )
    assert (
        client.get(PREFIX + "/drafts/" + identity, headers=_bearer(sender)).status_code
        == 404
    )
    second = client.post(PREFIX + "/drafts", headers=_bearer(sender), json={}).json()
    deleted = client.delete(
        PREFIX + "/drafts/" + second["id"],
        headers={**_bearer(sender), "If-Match": str(second["version"])},
    )
    assert deleted.status_code == 200, deleted.text
    restored = client.post(
        PREFIX + "/drafts/" + second["id"] + "/restore",
        headers={**_bearer(sender), "If-Match": str(deleted.json()["version"])},
    )
    assert restored.status_code == 200 and not restored.json()["is_deleted"]


def test_amendments_original_audience_withdrawal_and_idempotency(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(client, sender, payload(rid, action_required=True)).json()
    eid = original["envelope_id"]
    data = {
        "request_id": str(uuid4()),
        "amendment_kind": "due_date_added",
        "due_date": "2031-01-01",
        "reason": "New date",
    }
    response = client.post(
        PREFIX + "/outbox/" + eid + "/amendments", headers=_bearer(sender), json=data
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            PREFIX + "/outbox/" + eid + "/amendments",
            headers=_bearer(sender),
            json=data,
        ).json()
        == response.json()
    )
    assert (
        client.post(
            PREFIX + "/outbox/" + eid + "/amendments",
            headers=_bearer(sender),
            json={**data, "reason": "Different"},
        ).status_code
        == 409
    )
    notice = response.json()["deliveries"][0]["id"]
    assert (
        post(
            client,
            recipient,
            payload(uid, relationship_kind="reply", related_delivery_id=notice),
        ).status_code
        == 422
    )
    with db() as c:
        c.execute("DELETE FROM user_role_assignments WHERE user_id=%s", (rid,))
    withdrawal = client.post(
        PREFIX + "/outbox/" + eid + "/amendments",
        headers=_bearer(sender),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "action_withdrawn",
            "reason": "Cancelled",
        },
    )
    assert withdrawal.status_code == 200, withdrawal.text
    assert withdrawal.json()["expanded_recipient_count"] == 1
    receipts = client.get(
        PREFIX + "/outbox/" + eid + "/recipients", headers=_bearer(sender)
    ).json()
    assert receipts["items"][0]["action_status"] == "withdrawn"
    assert (
        client.post(
            PREFIX + "/outbox/" + eid + "/amendments",
            headers=_bearer(sender),
            json={**data, "request_id": str(uuid4())},
        ).status_code
        == 409
    )


def test_completion_is_independent_and_requires_original_sender_in_to(client):
    sender, uid, _ = account(client)
    first, rid, _ = account(client)
    second, sid, _ = account(client)
    result = post(client, sender, payload(rid, sid, action_required=True)).json()
    did = next(d["id"] for d in result["deliveries"] if d["recipient_user_id"] == rid)
    reply = payload(
        sid, relationship_kind="reply", related_delivery_id=did, complete_action=True
    )
    assert post(client, first, reply).status_code == 422
    reply["selectors"].append(
        {"selector_kind": "user", "target_id": uid, "recipient_type": "cc"}
    )
    assert post(client, first, reply).status_code == 422
    reply["selectors"][-1]["recipient_type"] = "to"
    assert post(client, first, reply).status_code == 200
    rows = client.get(
        PREFIX + "/outbox/" + result["envelope_id"] + "/recipients",
        headers=_bearer(sender),
    ).json()["items"]
    assert {r["recipient_user_id"]: r["action_status"] for r in rows} == {
        rid: "completed",
        sid: "outstanding",
    }
    assert all("read_at" not in row for row in rows)
    assert next(r for r in rows if r["recipient_user_id"] == rid)[
        "completion_reply_delivery_id"
    ]
    # A normal later reply is still possible and does not overwrite completion.
    assert (
        post(
            client,
            first,
            payload(uid, relationship_kind="reply", related_delivery_id=did),
        ).status_code
        == 200
    )


def test_draft_empty_send_and_failed_send_preserve_version_and_children(client):
    sender, uid, _ = account(client)
    recipient, rid, role = account(client)
    empty = client.post(PREFIX + "/drafts", headers=_bearer(sender), json={}).json()
    response = client.post(
        PREFIX + "/drafts/" + empty["id"] + "/send",
        headers=_bearer(sender),
        json={"request_id": str(uuid4()), "version": empty["version"]},
    )
    assert response.status_code == 422, response.text
    data = {k: v for k, v in payload(rid).items() if k != "request_id"}
    draft = client.post(PREFIX + "/drafts", headers=_bearer(sender), json=data).json()
    with db() as c:
        c.execute("DELETE FROM user_role_assignments WHERE user_id=%s", (rid,))
    response = client.post(
        PREFIX + "/drafts/" + draft["id"] + "/send",
        headers=_bearer(sender),
        json={"request_id": str(uuid4()), "version": draft["version"]},
    )
    assert response.status_code == 422, response.text
    current = client.get(
        PREFIX + "/drafts/" + draft["id"], headers=_bearer(sender)
    ).json()
    assert (
        current["version"] == draft["version"]
        and current["selectors"] == draft["selectors"]
    )
    assert client.get(PREFIX + "/outbox", headers=_bearer(sender)).json()["items"] == []


def test_concurrent_draft_updates_have_one_winner(client):
    from backend.services.api.messaging.drafts import save
    from backend.services.api.messaging.models import Draft
    from fastapi import HTTPException

    sender, uid, _ = account(client)
    draft = client.post(PREFIX + "/drafts", headers=_bearer(sender), json={}).json()

    def edit(subject):
        try:
            return run(
                uid,
                lambda c: save(
                    c, uid, Draft(subject=subject), draft["id"], draft["version"]
                ),
            )
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(edit, ["A", "B"]))
    assert sum(isinstance(r, dict) for r in results) == 1 and 409 in results


def test_concurrent_amendments_are_ordered_and_retries_emit_one_notice(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(
        client, sender, payload(rid, action_required=True, action_due_date="2030-01-01")
    ).json()
    eid = original["envelope_id"]
    same = Amendment(
        request_id=uuid4(),
        amendment_kind="due_date_changed",
        due_date="2031-01-01",
        reason="Updated",
    )
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: run(uid, lambda c: amend(c, uid, eid, same)), range(2)
            )
        )
    assert results[0] == results[1]
    amendments = [
        Amendment(
            request_id=uuid4(),
            amendment_kind="due_date_changed",
            due_date=d,
            reason="Rescheduled",
        )
        for d in ("2032-01-01", "2033-01-01")
    ]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda data: run(uid, lambda c: amend(c, uid, eid, data)), amendments
            )
        )
    with db() as c:
        rows = c.execute(
            "SELECT sequence,previous_due_date,new_due_date FROM message_action_amendments WHERE original_envelope_id=%s ORDER BY sequence",
            (eid,),
        ).fetchall()
        assert [r["sequence"] for r in rows] == [1, 2, 3]
        assert rows[2]["previous_due_date"] == rows[1]["new_due_date"]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_envelopes WHERE message_kind='action_amendment_notice'"
            ).fetchone()["n"]
            == 3
        )


def test_completion_withdrawal_race_never_commits_completion_after_withdrawal(client):
    from fastapi import HTTPException

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(client, sender, payload(rid, action_required=True)).json()
    eid = original["envelope_id"]
    did = original["deliveries"][0]["id"]
    reply = Send(
        **payload(
            uid,
            relationship_kind="reply",
            related_delivery_id=did,
            complete_action=True,
        )
    )
    change = Amendment(
        request_id=uuid4(), amendment_kind="action_withdrawn", reason="Cancelled"
    )

    def complete():
        try:
            return run(rid, lambda c: send(c, rid, reply))
        except HTTPException as e:
            assert e.status_code == 409
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(complete)
        second = workers.submit(lambda: run(uid, lambda c: amend(c, uid, eid, change)))
        completion, withdrawal = first.result(), second.result()
    with db() as c:
        completed = c.execute(
            "SELECT completed_at FROM message_action_completions WHERE original_delivery_id=%s",
            (did,),
        ).fetchone()
        withdrawn = c.execute(
            "SELECT created_at FROM message_action_amendments WHERE id=%s",
            (withdrawal["amendment_id"],),
        ).fetchone()
        if completion:
            assert completed["completed_at"] <= withdrawn["created_at"]
        else:
            assert completed is None


def test_effective_filters_and_due_date_validation(client):
    from datetime import date, timedelta

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(client, sender, payload(rid, action_required=True)).json()
    eid = original["envelope_id"]
    url = PREFIX + "/outbox/" + eid + "/amendments"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert (
        client.post(
            url,
            headers=_bearer(sender),
            json={
                "request_id": str(uuid4()),
                "amendment_kind": "due_date_added",
                "due_date": yesterday,
                "reason": "Invalid past date",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            headers=_bearer(sender),
            json={
                "request_id": str(uuid4()),
                "amendment_kind": "due_date_removed",
                "reason": "No existing date",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            headers=_bearer(sender),
            json={
                "request_id": str(uuid4()),
                "amendment_kind": "action_withdrawn",
                "reason": "  ",
            },
        ).status_code
        == 422
    )
    assert (
        len(
            client.get(
                PREFIX + "/outbox?action_state=outstanding", headers=_bearer(sender)
            ).json()["items"]
        )
        == 1
    )
    assert (
        client.post(
            url,
            headers=_bearer(sender),
            json={
                "request_id": str(uuid4()),
                "amendment_kind": "action_withdrawn",
                "reason": "Cancelled",
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            PREFIX + "/outbox?action_state=outstanding", headers=_bearer(sender)
        ).json()["items"]
        == []
    )
    assert (
        client.get(
            PREFIX + "/outbox?action_required=true", headers=_bearer(sender)
        ).json()["items"]
        == []
    )
    assert (
        len(
            client.get(
                PREFIX + "/outbox?action_required=false", headers=_bearer(sender)
            ).json()["items"]
        )
        == 1
    )


def test_status_boundaries_and_fair_extension():
    from datetime import datetime, timedelta, timezone
    from backend.services.api.messaging.actions import status

    boundary = datetime(2030, 1, 2, tzinfo=timezone.utc)
    state = {"action_required": True, "due_at": boundary}
    assert status(True, state, None, boundary) == "outstanding"
    assert status(True, state, None, boundary + timedelta(microseconds=1)) == "late"
    completed = boundary + timedelta(seconds=1)
    assert status(True, state, completed, completed) == "completed_late"
    assert (
        status(True, {"action_required": True, "due_at": None}, completed, completed)
        == "completed"
    )
    assert (
        status(
            True,
            {"action_required": False, "due_at": None},
            completed,
            completed,
            boundary,
        )
        == "completed_late"
    )
    assert (
        status(
            True, {"action_required": False, "due_at": None}, None, completed, boundary
        )
        == "withdrawn"
    )


def test_phase2_routes_deny_exchange_loss_and_foreign_objects(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    outsider, oid, _ = account(client, privileges=())
    original = post(client, sender, payload(rid, action_required=True)).json()
    eid = original["envelope_id"]
    change = {
        "request_id": str(uuid4()),
        "amendment_kind": "action_withdrawn",
        "reason": "No authority",
    }
    assert (
        client.post(
            PREFIX + "/outbox/" + eid + "/amendments",
            headers=_bearer(recipient),
            json=change,
        ).status_code
        == 404
    )
    assert (
        client.get(
            PREFIX + "/" + eid + "/amendments", headers=_bearer(outsider)
        ).status_code
        == 404
    )
    for method, path, data in [
        ("GET", "/drafts", None),
        ("POST", "/drafts", {}),
        ("GET", "/outbox", None),
        ("POST", "/outbox/" + eid + "/amendments", change),
    ]:
        response = client.request(
            method,
            PREFIX + path,
            headers=_bearer(outsider),
            **({"json": data} if data is not None else {}),
        )
        assert response.status_code == 403, response.text


def test_late_completion_corrected_by_removal_without_changing_original(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(
        client, sender, payload(rid, action_required=True, action_due_date="2030-01-01")
    ).json()
    eid = original["envelope_id"]
    did = original["deliveries"][0]["id"]
    # Age this disposable fixture to exercise reads across the boundary without
    # sleeps or changing the production clock. Re-enable its immutable guard.
    with db() as c:
        c.execute(
            "ALTER TABLE message_envelopes DISABLE TRIGGER message_envelopes_immutable"
        )
        c.execute(
            "UPDATE message_envelopes SET action_due_date='2020-01-01',action_due_timezone='UTC',action_due_at='2020-01-02T00:00:00Z' WHERE id=%s",
            (eid,),
        )
        c.execute(
            "ALTER TABLE message_envelopes ENABLE TRIGGER message_envelopes_immutable"
        )
    assert (
        len(
            client.get(
                PREFIX + "/outbox?action_state=late", headers=_bearer(sender)
            ).json()["items"]
        )
        == 1
    )
    assert (
        post(
            client,
            recipient,
            payload(
                uid,
                relationship_kind="reply",
                related_delivery_id=did,
                complete_action=True,
            ),
        ).status_code
        == 200
    )

    def state():
        return client.get(
            PREFIX + "/outbox/" + eid + "/recipients", headers=_bearer(sender)
        ).json()["items"][0]["action_status"]

    assert state() == "completed_late"
    removed = client.post(
        PREFIX + "/outbox/" + eid + "/amendments",
        headers=_bearer(sender),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "due_date_removed",
            "reason": "Deadline removed",
        },
    )
    assert removed.status_code == 200, removed.text
    assert state() == "completed"
    detail = client.get(PREFIX + "/outbox/" + eid, headers=_bearer(sender)).json()
    assert (
        detail["action_due_date"] == "2020-01-01"
        and detail["effective_action"]["due_date"] is None
    )
    withdrawn = client.post(
        PREFIX + "/outbox/" + eid + "/amendments",
        headers=_bearer(sender),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "action_withdrawn",
            "reason": "Action withdrawn",
        },
    )
    assert withdrawn.status_code == 200 and state() == "completed"


def test_relationship_security_floor_and_draft_clearance_loss(client):
    sender, uid, srole = account(client)
    recipient, rid, rrole = account(client)
    with db() as c:
        high = c.execute("SELECT id FROM security_levels WHERE code='S'").fetchone()[
            "id"
        ]
        low = c.execute("SELECT id FROM security_levels WHERE code='G'").fetchone()[
            "id"
        ]
        c.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=ANY(%s)",
            (high, [srole, rrole]),
        )
    original = post(client, sender, payload(rid, security_level_id=high)).json()
    assert (
        post(
            client,
            recipient,
            payload(
                uid,
                security_level_id=low,
                relationship_kind="reply",
                related_delivery_id=original["deliveries"][0]["id"],
            ),
        ).status_code
        == 422
    )
    draft = client.post(
        PREFIX + "/drafts",
        headers=_bearer(sender),
        json={"subject": "Secret draft", "security_level_id": high},
    ).json()
    with db() as c:
        c.execute("UPDATE roles SET security_level_id=%s WHERE id=%s", (low, srole))
    assert (
        client.get(
            PREFIX + "/drafts/" + draft["id"], headers=_bearer(sender)
        ).status_code
        == 403
    )
    rows = client.get(PREFIX + "/drafts", headers=_bearer(sender)).json()["items"]
    assert rows[0]["availability"] == "restricted" and rows[0]["subject"] is None


def test_amendment_failure_rolls_back_all_history_and_delivery(client, monkeypatch):
    from backend.services.api.messaging import actions
    import pytest

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    original = post(client, sender, payload(rid, action_required=True)).json()
    eid = original["envelope_id"]

    def fail(*args):
        raise RuntimeError("Injected notice failure")

    monkeypatch.setattr(actions, "fan_out", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        run(
            uid,
            lambda c: amend(
                c,
                uid,
                eid,
                Amendment(
                    request_id=uuid4(),
                    amendment_kind="action_withdrawn",
                    reason="Rollback test",
                ),
            ),
        )
    with db() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM message_action_amendments").fetchone()[
                "n"
            ]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_envelopes WHERE message_kind='action_amendment_notice'"
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_request_receipts WHERE operation_kind='amendment'"
            ).fetchone()["n"]
            == 0
        )


def test_messaging_translation_artifact_valid_and_curated_items_preserved(client):
    import json, hashlib, subprocess
    from pathlib import Path
    from backend.services.api.localization import _translation_import_plan

    root = Path(__file__).resolve().parents[4]
    en = root / "frontend/webui/i18n/messages.en.json"
    ar = root / "frontend/webui/i18n/messages.ar.generated.json"
    artifact = json.loads(ar.read_text())
    definitions = json.loads(en.read_text())
    assert artifact["catalogue_sha256"] == hashlib.sha256(en.read_bytes()).hexdigest()
    assert [x["message_key"] for x in artifact["items"]] == [
        x["message_key"] for x in definitions
    ]
    baseline = json.loads(
        subprocess.check_output(
            ["git", "show", "HEAD:frontend/webui/i18n/messages.ar.generated.json"],
            cwd=root,
            text=True,
        )
    )
    current = {x["message_key"]: x for x in artifact["items"]}
    for row in baseline["items"]:
        assert current[row["message_key"]] == row
    with db() as c:
        _, _, summary = _translation_import_plan(c, "ar", artifact)
        assert summary["complete"], summary
    # Curated baseline rows were compared exactly above. Older approved exports
    # need not carry the generation-only review_required field; new generated
    # messaging candidates must still be explicitly marked for review.
    baseline_keys = {row["message_key"] for row in baseline["items"]}
    assert all(
        row.get("provenance", {}).get("review_required")
        for row in artifact["items"]
        if row["message_key"].startswith("messaging.")
        and row["message_key"] not in baseline_keys
    )


def test_amendment_notice_freezes_published_localization_and_original_reason(client):
    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    with db() as c:
        c.execute(
            "SELECT set_config('app.change_reason','Disposable localization fixture',true)"
        )
        c.execute(
            "UPDATE ui_message_translations SET translated_text='تعديل الإجراء',published_text='تعديل الإجراء',status='published',origin='manual',needs_review=false WHERE language_tag='ar' AND message_key='messaging.notice.action_amended'"
        )
        c.execute(
            "INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES (%s,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'",
            (rid,),
        )
    original = post(client, sender, payload(rid, action_required=True)).json()
    response = client.post(
        PREFIX + "/outbox/" + original["envelope_id"] + "/amendments",
        headers=_bearer(sender),
        json={
            "request_id": str(uuid4()),
            "amendment_kind": "action_withdrawn",
            "reason": "Reason <unchanged>",
        },
    )
    assert response.status_code == 200, response.text
    did = response.json()["deliveries"][0]["id"]
    notice = client.get(PREFIX + "/inbox/" + did, headers=_bearer(recipient)).json()
    assert notice["subject"] == "تعديل الإجراء" and notice["direction"] == "rtl"
    assert "Reason &lt;unchanged&gt;" in notice["body_rich_text"]
    with db() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM message_envelope_localizations WHERE envelope_id=%s",
                (response.json()["envelope_id"],),
            ).fetchone()["n"]
            == c.execute(
                "SELECT count(*) AS n FROM supported_languages WHERE is_enabled"
            ).fetchone()["n"]
        )
        c.execute(
            "SELECT set_config('app.change_reason','Change disposable catalogue after send',true)"
        )
        c.execute(
            "UPDATE ui_message_translations SET translated_text='New draft wording',status='draft' WHERE language_tag='ar' AND message_key='messaging.notice.action_amended'"
        )
    assert (
        client.get(PREFIX + "/inbox/" + did, headers=_bearer(recipient)).json()[
            "subject"
        ]
        == "تعديل الإجراء"
    )


def test_concurrent_draft_send_retries_create_one_envelope(client):
    from backend.services.api.messaging.drafts import send_draft
    from backend.services.api.messaging.models import DraftSend

    sender, uid, _ = account(client)
    recipient, rid, _ = account(client)
    data = {k: v for k, v in payload(rid).items() if k != "request_id"}
    draft = client.post(PREFIX + "/drafts", headers=_bearer(sender), json=data).json()
    request = DraftSend(request_id=uuid4(), version=draft["version"])
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(
            workers.map(
                lambda _: run(uid, lambda c: send_draft(c, uid, draft["id"], request)),
                range(2),
            )
        )
    assert outcomes[0] == outcomes[1]
    with db() as c:
        assert (
            c.execute("SELECT count(*) AS n FROM message_envelopes").fetchone()["n"]
            == 1
        )
        assert (
            c.execute("SELECT count(*) AS n FROM message_drafts").fetchone()["n"] == 0
        )


def test_recipient_search_matches_multilingual_names_descriptions_and_email(client):
    from psycopg.types.json import Jsonb
    sender, uid, _ = account(client)
    _, rid, role = account(client)
    with db() as c:
        unit = c.execute('SELECT org_unit_id FROM roles WHERE id=%s', (role,)).fetchone()['org_unit_id']
        c.execute("SELECT set_config('app.change_reason','Test multilingual recipient search',true)")
        c.execute("INSERT INTO supported_languages(language_tag,english_name,native_name,direction,is_enabled) VALUES('fr','French','Français','ltr',true) ON CONFLICT(language_tag) DO NOTHING")
        for table, identity in [('users', rid), ('roles', role), ('org_units', unit)]:
            c.execute(f'UPDATE {table} SET name=%s, description=%s, translations=%s WHERE id=%s', (
                'Cobalt '+table, 'Archive stewardship '+table,
                Jsonb({'ar': {'name': 'الاسم '+table, 'description': 'وصف تجريبي'}, 'fr': {'name':'Équipe '+table,'description':'Patrimoine documentaire'}}), identity))
        c.execute("UPDATE users SET external_id='STAFF-CODE-219' WHERE id=%s", (rid,))
        c.execute("UPDATE roles SET code='ROLE-CODE-219' WHERE id=%s", (role,))
        c.execute("UPDATE org_units SET code='UNIT-CODE-219' WHERE id=%s", (unit,))
        email = c.execute('SELECT email FROM users WHERE id=%s',(rid,)).fetchone()['email']
    for kind, identity in [('user',rid),('role',role),('org_unit',unit)]:
        for query in ['COBALT','stewardship','الاسم','تجريبي','Équipe','documentaire','code-219'] + ([email] if kind=='user' else []):
            result = client.get(PREFIX+'/recipients/'+kind, headers=_bearer(sender), params={'q':query,'limit':1})
            assert result.status_code == 200, result.text
            assert result.json()['items'][0]['id'] == identity, (kind,query,result.json())
            assert result.json()['items'][0]['eligible']
            assert result.json()['items'][0]['email'] == (email if kind == 'user' else None)
    with db() as c:
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(%s,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'",(uid,))
    result = client.get(PREFIX+'/recipients/user', headers=_bearer(sender), params={'target_id':rid}).json()
    assert result['items'][0]['name'] == 'الاسم users'
    assert result['items'][0]['email'] == email
    with db() as c:
        c.execute('UPDATE users SET date_suspended=CURRENT_TIMESTAMP WHERE id=%s',(rid,))
    assert client.get(PREFIX+'/recipients/user',headers=_bearer(sender),params={'q':email}).json()['items']==[]


def test_component_targets_and_internal_urls_are_rejected_for_send_and_drafts(client):
    sender, _, _ = account(client)
    _, recipient, _ = account(client)
    token = str(uuid4())
    body = '<p><span data-wathiq-link="' + token + '">Component</span></p>'
    link = {'link_token': token, 'resource_kind': 'digital_component', 'target_id': 1}
    response = post(client, sender, payload(recipient, body_rich_text=body, resource_links=[link]))
    assert response.status_code == 422, response.text
    response = client.post(PREFIX + '/drafts', headers=_bearer(sender),
                           json={'body_rich_text': body, 'resource_links': [link]})
    assert response.status_code == 422, response.text
    assert client.get(PREFIX + '/resources/digital_component', headers=_bearer(sender)).status_code == 422
    for url in ['/digital-components/1', 'https://wathiq.example/api/v1/digital-components/1',
                'https://wathiq.example/#/digital-components/1', '/%64igital-components/1']:
        body = '<p><a href="' + url + '">Component</a></p>'
        assert post(client, sender, payload(recipient, body_rich_text=body)).status_code == 422
        assert client.post(PREFIX + '/drafts', headers=_bearer(sender),
                           json={'body_rich_text': body}).status_code == 422
    with db() as c:
        columns = c.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_name IN ('message_resource_links','message_draft_resource_links') AND column_name='digital_component_id'").fetchall()
        assert not columns
        assert c.execute("SELECT 1 FROM information_schema.columns WHERE table_name='message_record_capture_components' AND column_name='digital_component_id'").fetchone()


def test_cc_is_informational_and_cannot_complete_or_keep_action_outstanding(client):
    sender, uid, _ = account(client)
    to_token, to_id, _ = account(client)
    cc_token, cc_id, _ = account(client)
    selectors = [dict(selector_kind='user', target_id=to_id, recipient_type='to'),
                 dict(selector_kind='user', target_id=cc_id, recipient_type='cc')]
    response = post(client, sender, payload(action_required=True, selectors=selectors))
    assert response.status_code == 200, response.text
    result = response.json()
    deliveries = {d['recipient_user_id']: d['id'] for d in result['deliveries']}
    cc = client.get(PREFIX + '/inbox/' + deliveries[cc_id], headers=_bearer(cc_token)).json()
    assert cc['recipient_type'] == 'cc' and cc['action_status'] is None
    assert client.get(PREFIX + '/inbox', headers=_bearer(cc_token)).json()['items'][0]['action_status'] is None
    attempted = post(client, cc_token, payload(uid, relationship_kind='reply', related_delivery_id=deliveries[cc_id], complete_action=True))
    assert attempted.status_code == 422, attempted.text
    assert attempted.json()['detail']['code'] == 'message_completion_unavailable'
    # Cc can send an ordinary reply.
    ordinary = post(client, cc_token, payload(uid, relationship_kind='reply', related_delivery_id=deliveries[cc_id]))
    assert ordinary.status_code == 200
    with pytest.raises(psycopg.errors.CheckViolation, match='message_completion_invalid'):
        with db() as c:
            c.execute("SELECT set_config('app.user_id',%s,true)", (str(cc_id),))
            c.execute('INSERT INTO message_action_completions(original_delivery_id,reply_envelope_id,completed_by_user_id) VALUES (%s,%s,%s)', (deliveries[cc_id], ordinary.json()['envelope_id'], cc_id))
    assert post(client, to_token, payload(uid, relationship_kind='reply', related_delivery_id=deliveries[to_id], complete_action=True)).status_code == 200
    receipts = client.get(PREFIX + '/outbox/' + result['envelope_id'] + '/recipients', headers=_bearer(sender)).json()['items']
    assert {r['recipient_user_id']: r['action_status'] for r in receipts} == {to_id: 'completed', cc_id: None}
    outstanding = client.get(PREFIX + '/outbox', params={'action_state': 'outstanding'}, headers=_bearer(sender)).json()['items']
    assert all(row['id'] != result['envelope_id'] for row in outstanding)


@pytest.mark.parametrize('kind', ['user', 'role', 'org_unit'])
def test_inbox_and_outbox_recipient_selector_filter(client, kind):
    sender, uid, _ = account(client)
    recipient, rid, role = account(client)
    with db() as c:
        org = c.execute('SELECT org_unit_id FROM roles WHERE id=%s', (role,)).fetchone()['org_unit_id']
    target = {'user': rid, 'role': role, 'org_unit': org}[kind]
    if kind == 'user':
        own_option = client.get(PREFIX + '/recipients/user', params={'purpose': 'filter', 'target_id': rid}, headers=_bearer(recipient))
        assert [row['id'] for row in own_option.json()['items']] == [rid]
        assert client.get(PREFIX + '/recipients/user', params={'target_id': rid}, headers=_bearer(recipient)).json()['items'] == []
    matched = post(client, sender, payload(selectors=[dict(selector_kind=kind, target_id=target, recipient_type='to')]))
    assert matched.status_code == 200, matched.text
    if kind != 'user':
        assert post(client, sender, payload(rid)).status_code == 200
    for mailbox, token in (('inbox', recipient), ('outbox', sender)):
        url = PREFIX + '/' + mailbox
        filtered = client.get(url, params={'recipient_kind': kind, 'recipient_id': target}, headers=_bearer(token))
        assert filtered.status_code == 200, filtered.text
        assert len(filtered.json()['items']) == 1
        assert client.get(url, params={'recipient_kind': kind}, headers=_bearer(token)).status_code == 422
        assert client.get(url, params={'recipient_kind': kind, 'recipient_id': target + 1000000}, headers=_bearer(token)).json()['items'] == []
