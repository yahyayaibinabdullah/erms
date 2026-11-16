"""Mailbox criteria run on the authorized server-side result set before paging."""

from uuid import uuid4

from .test_full_text_search_phase3 import _publish_component, _upload
from .test_messaging import EXCHANGE, PREFIX, _bearer, account, db, payload, post


def fetch(client, token, folder, **params):
    response = client.get(f"{PREFIX}/{folder}", headers=_bearer(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def save_draft(client, token, message):
    fields = {key: value for key, value in message.items() if key != "request_id"}
    response = client.post(f"{PREFIX}/drafts", headers=_bearer(token), json=fields)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_mailbox_subject_and_visible_body_filters_page_all_matches(client):
    sender, _, _ = account(client)
    recipient, recipient_id, _ = account(client)
    buckets = {"inbox": [], "outbox": [], "drafts": []}
    for i in range(4):
        message = payload(
            recipient_id, subject="Budget correspondence",
            body_rich_text='<p>Rev<strong>iew</strong> &amp; approve.</p><p>Next line</p>'
                           '<a href="https://example.test/hidden-attribute">Read more</a>',
        )
        delivered = post(client, sender, message)
        assert delivered.status_code == 200, delivered.text
        buckets["inbox"].append(delivered.json()["deliveries"][0]["id"])
        buckets["outbox"].append(delivered.json()["envelope_id"])
        buckets["drafts"].append(save_draft(client, sender, message))
        if i == 1:
            unrelated = payload(recipient_id, subject="Budget miscellaneous", body_rich_text="<p>Other body</p>")
            assert post(client, sender, unrelated).status_code == 200
            save_draft(client, sender, unrelated)

    for folder, expected in buckets.items():
        token = recipient if folder == "inbox" else sender
        first = fetch(client, token, folder, q="BUDGET", body_q="review & approve. Next", limit=2)
        assert first["has_more"]
        last = fetch(client, token, folder, q="BUDGET", body_q="review & approve. Next", limit=2,
                     cursor=first["next_cursor"])
        assert not last["has_more"]
        assert [row["id"] for row in first["items"] + last["items"]] == expected[::-1]
        assert not fetch(client, token, folder, body_q="hidden-attribute")["items"]
        assert not fetch(client, token, folder, body_q="%")["items"]
        assert not fetch(client, token, folder, q="missing", body_q="review")["items"]
        assert client.get(f"{PREFIX}/{folder}", headers=_bearer(token),
                          params={"body_q": "x" * 256}).status_code == 422

    stranger, _, _ = account(client, ())
    assert not fetch(client, stranger, "inbox", q="Budget")["items"]
    for folder in ("outbox", "drafts"):
        assert client.get(f"{PREFIX}/{folder}", params={"q": "Budget"},
                          headers=_bearer(stranger)).status_code == 403


def test_content_filters_do_not_confirm_restricted_message_text(client):
    sender, _, sender_role = account(client)
    recipient, recipient_id, recipient_role = account(client)
    with db() as connection:
        high = connection.execute("SELECT id FROM security_levels WHERE code='S'").fetchone()["id"]
        connection.execute("UPDATE roles SET security_level_id=%s WHERE id=ANY(%s)",
                           (high, [sender_role, recipient_role]))
    message = payload(recipient_id, subject="Restricted clue", body_rich_text="<p>Unseen clue</p>",
                      security_level_id=high)
    assert post(client, sender, message).status_code == 200
    save_draft(client, sender, message)
    with db() as connection:
        connection.execute("UPDATE roles SET security_level_id=(SELECT id FROM security_levels WHERE code='G') "
                           "WHERE id=ANY(%s)", ([sender_role, recipient_role],))
    for folder, acting in (("inbox", recipient), ("outbox", sender), ("drafts", sender)):
        assert fetch(client, acting, folder)["items"][0]["availability"] == "restricted"
        assert not fetch(client, acting, folder, q="Restricted clue")["items"]
        assert not fetch(client, acting, folder, body_q="Unseen clue")["items"]


def test_linked_text_uses_active_index_and_current_component_authorization(client, aggregation):
    with db() as connection:
        connection.execute("""UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='ALL_PRIVS')
                               WHERE code='system-administrator'""")
    sender = client.cookies["erms_session"]
    setting = next(item for item in client.get("/api/v1/application-settings").json()["items"]
                   if item["key"] == "FULL_TEXT_SEARCH_ENABLED")
    response = client.get(f"{PREFIX}/outbox", params={"linked_q": "orchid"})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "full_text_search_disabled"
    response = client.put("/api/v1/application-settings", json={"changes": [
        {"key": "FULL_TEXT_SEARCH_ENABLED", "expected_version": setting["version"], "value": True},
    ]}, headers={"X-Change-Reason": "Enable linked-content search in this disposable test"})
    assert response.status_code == 200, response.text
    response = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "LINKED", "title": "Linked test record",
        "medium": "digital",
    })
    assert response.status_code == 201, response.text
    record = response.json()
    component = _upload(client, record, "filename-only.txt")
    _publish_component(component, "The register contains restricted orchid evidence.")
    recipient, recipient_id, role = account(
        client, privileges=(EXCHANGE, "aggregation.view", "record.view", "record.component.view"),
    )
    with db() as connection:
        connection.execute("""INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
                              SELECT %s,'role',%s,id FROM permissions WHERE code='aggregation.view'""",
                           (aggregation["id"], role))
        connection.execute("""INSERT INTO aggregation_child_record_acl_defaults
                                  (aggregation_id,principal_type,role_id,permission_id)
                              SELECT %s,'role',%s,id FROM permissions
                              WHERE code IN ('record.view','record.component.list','record.component.view')""",
                           (aggregation["id"], role))
    expected = {"inbox": [], "outbox": [], "drafts": []}
    for kind, target in (("record", record), ("aggregation", aggregation)):
        token = str(uuid4())
        message = payload(recipient_id, subject=f"Accessible {kind}", body_rich_text=(
            f'<p>Message with a link</p><span data-wathiq-link="{token}"></span>'
        ), resource_links=[{"link_token": token, "resource_kind": kind, "target_id": target["id"]}])
        response = post(client, sender, message)
        assert response.status_code == 200, response.text
        expected["inbox"].append(response.json()["deliveries"][0]["id"])
        expected["outbox"].append(response.json()["envelope_id"])
        expected["drafts"].append(save_draft(client, sender, message))
    for folder, ids in expected.items():
        acting = recipient if folder == "inbox" else sender
        file_matches = fetch(client, acting, folder, linked_q='"orchid evidence"')["items"]
        metadata_matches = fetch(client, acting, folder, linked_q='"root aggregation"')["items"]
        assert [row["id"] for row in file_matches] == [ids[0]]
        assert [row["id"] for row in metadata_matches] == [ids[1]]
        assert not fetch(client, acting, folder, linked_q="filename-only")["items"]
        assert not fetch(client, acting, folder, linked_q="orchid", q="unmatched")["items"]
    with db() as connection:
        connection.execute("""DELETE FROM profile_privileges
            WHERE profile_id=(SELECT profile_id FROM roles WHERE id=%s)
              AND privilege_id=(SELECT id FROM privileges WHERE code='record.component.view')""", (role,))
    assert len(fetch(client, recipient, "inbox")["items"]) == 2
    assert not fetch(client, recipient, "inbox", linked_q="orchid")["items"]
    assert [row["id"] for row in fetch(client, recipient, "inbox", linked_q="root")["items"]] == [expected["inbox"][1]]
    with db() as connection:
        connection.execute("UPDATE digital_component_search_documents SET status='stale' WHERE digital_component_id=%s",
                           (component["id"],))
    assert not fetch(client, sender, "outbox", linked_q="orchid")["items"]
    assert not fetch(client, sender, "drafts", linked_q="orchid")["items"]
