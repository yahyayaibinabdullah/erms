"""Exercise the Phase 2 resource type gates through the public API and SQL."""

import os

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.dashboard_visibility import visibility_ctes
from .test_phase7_mutation_authorization import (
    _grant_principal,
    _login_as_phase7,
    _set_record_acl,
    _set_aggregation_acl,
)


@pytest.fixture
def catalogue():
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("TRUNCATE resource_types CASCADE")


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.mark.parametrize("kind", ["record", "aggregation"])
def test_admin_operations_assignment_and_versions(
    client, record, aggregation, catalogue, kind
):
    base = "/api/v1/" + kind + "-types"
    row = record if kind == "record" else aggregation
    path = f"/api/v1/{kind}s/{row['id']}"
    t = ok(
        client.post(
            base, json={"name": "Inspection", "translations": {"ar": {"name": "تفتيش"}}}
        ),
        201,
    )
    url = f"{base}/{t['id']}"

    def headers():
        return {"If-Match": str(ok(client.get(url))["version"])}

    f = ok(
        client.post(
            url + "/fields",
            headers=headers(),
            json={
                "name": "Priority",
                "display_order": 0,
                "data_type": "single_choice",
                "required": False,
            },
        ),
        201,
    )
    fu = f"{url}/fields/{f['id']}"
    label = {
        "name": "Urgent",
        "translations": {"ar": {"name": "عاجل"}},
        "display_order": 1,
    }
    ch = ok(client.post(fu + "/choices", headers=headers(), json=label), 201)
    cu = f"{fu}/choices/{ch['id']}"
    ok(client.put(cu, headers=headers(), json={**label, "name": "High"}))
    assert ok(client.get(fu + "/choices", params={"limit": 1}))[0]["name"] == "High"
    definition = {
        "name": "Priority",
        "display_order": 1,
        "required": True,
        "data_type": "single_choice",
        "default": ch["id"],
    }
    ok(client.put(fu, headers=headers(), json=definition))
    assert client.put(fu, headers={"If-Match": "1"}, json=definition).status_code == 412
    assert ok(client.get(url + "/fields"))[0]["default"] == ch["id"]
    ok(client.put(url, headers=headers(), json={"name": "Inspections"}))
    assert ok(client.get(base, params={"q": "Inspections"}))[0]["id"] == t["id"]
    assert (
        ok(client.get(base + "/options", params={"access": "use"}))[0]["id"] == t["id"]
    )
    assert (
        client.put(
            url + "/role-grants",
            headers=headers(),
            json={"see_role_ids": [], "use_role_ids": [1]},
        ).status_code
        == 422
    )
    ok(
        client.put(
            url + "/role-grants",
            headers=headers(),
            json={"see_role_ids": [1], "use_role_ids": []},
        )
    )
    assert ok(client.get(url + "/role-grants")) == [{"role_id": 1, "can_use": False}]

    def patch(body, version=None):
        return client.patch(
            path,
            headers={"If-Match": str(version or ok(client.get(path))["version"])},
            json=body,
        )

    assigned = ok(patch({"type_id": t["id"]}))
    assert assigned["field_values"] == {str(f["id"]): ch["id"]}
    for body, expected in [
        ({"type_id": None}, 409),
        ({"field_values": {str(f["id"]): None}}, 422),
    ]:
        assert patch(body).status_code == expected
        assert ok(client.get(path))["field_values"] == assigned["field_values"]
    assert (
        patch(
            {"type_id": None, "confirm_type_change": True}, row["version"]
        ).status_code
        == 412
    )
    assert (
        ok(patch({"type_id": None, "confirm_type_change": True}))["field_values"] == {}
    )
    assert client.delete(cu, headers=headers()).status_code == 409
    ok(client.put(fu, headers=headers(), json={**definition, "default": None}))
    ok(client.delete(cu, headers=headers()), 204)
    ok(client.delete(fu, headers=headers()), 204)
    ok(client.delete(url, headers=headers()), 204)


def test_type_gates_are_independent_from_acl_privilege_and_clearance(
    client, record, aggregation, catalogue
):
    uid, role = _grant_principal(
        {"record.view", "record.modify", "record.component.view", "aggregation.view"}
    )
    _set_record_acl(record["id"], role, {"record.view", "record.modify_metadata"})
    _set_aggregation_acl(aggregation["id"], role, {"aggregation.view"})
    t = ok(client.post("/api/v1/record-types", json={"name": "Restricted"}), 201)
    path = f"/api/v1/records/{record['id']}"

    def patch(body):
        return client.patch(
            path, headers={"If-Match": str(ok(client.get(path))["version"])}, json=body
        )

    assigned = ok(patch({"type_id": t["id"]}))
    explain = {
        "resource_type": "record",
        "resource_id": record["id"],
        "operation": "record.view",
    }
    denied = ok(
        client.post("/api/v1/authorization/explain", json={**explain, "user_id": uid})
    )
    assert (
        not denied["allowed"] and denied["decision_code"] == "insufficient_type_access"
    )
    assert [g["gate"] for g in denied["gates"]] == [
        "authentication",
        "effective_roles",
        "resource_type",
    ]
    _login_as_phase7(client)
    assert client.get(path).status_code == 404
    assert ok(client.get("/api/v1/records")) == []
    assert ok(client.get("/api/v1/record-types/options")) == []
    assert client.get("/api/v1/record-types").status_code == 403
    assert (
        client.post("/api/v1/record-types", json={"name": "Secret"}).status_code == 403
    )
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        c.execute("SELECT set_config('app.user_id',%s,false)", (str(uid),))

        def decisions(expected):
            assert (
                c.execute(
                    "SELECT current_user_can_view_record(%s) AS allowed",
                    (record["id"],),
                ).fetchone()["allowed"]
                is expected
            )
            assert (
                bool(
                    c.execute(
                        f"WITH RECURSIVE {visibility_ctes()} SELECT id FROM authorized_records WHERE id=%s",
                        (record["id"],),
                    ).fetchone()
                )
                is expected
            )

        decisions(False)
        c.execute(
            "INSERT INTO resource_type_role_grants VALUES ('record',%s,%s,false)",
            (t["id"], role),
        )
        c.commit()
        decisions(True)
        view = ok(client.post("/api/v1/authorization/explain", json=explain))
        assert view["allowed"] and view["contributors"]["type_role_ids"] == [role]
        edit = ok(
            client.post(
                "/api/v1/authorization/explain",
                json={**explain, "operation": "record.modify_metadata"},
            )
        )
        assert not edit["allowed"] and edit["required_type_access"] == "use"
        assert ok(client.get(path))["type_id"] == t["id"]
        assert ok(client.get("/api/v1/record-types/options"))[0]["id"] == t["id"]
        assert ok(client.get("/api/v1/record-types/options?access=use")) == []
        assert (
            client.patch(
                path,
                headers={"If-Match": str(assigned["version"])},
                json={"title": "Hidden edit"},
            ).status_code
            == 403
        )
        c.execute(
            "UPDATE resource_type_role_grants SET can_use=true WHERE role_id=%s",
            (role,),
        )
        c.commit()
        ok(
            client.patch(
                path,
                headers={"If-Match": str(assigned["version"])},
                json={"title": "Allowed"},
            )
        )
        c.execute("DELETE FROM resource_type_role_grants WHERE role_id=%s", (role,))
        c.commit()
        decisions(False)
        assert client.get(path).status_code == 404


def test_decimal_creation_reassignment_and_history(client, aggregation, catalogue):
    path = "/api/v1/record-types"
    first, second = [
        ok(client.post(path, json={"name": name}), 201)
        for name in ("Legacy", "Replacement")
    ]

    def decimal_field(t):
        return ok(
            client.post(
                f"{path}/{t['id']}/fields",
                headers={"If-Match": str(t["version"])},
                json={
                    "name": "Amount",
                    "data_type": "decimal",
                    "display_order": 1,
                    "default": "0.00",
                },
            ),
            201,
        )["id"]

    f1, f2 = decimal_field(first), decimal_field(second)
    body = {
        "title": "Typed record",
        "aggregation_id": aggregation["id"],
        "record_number": "TYPE-1",
        "type_id": first["id"],
    }
    import json

    digits = "12345678901234567890.01234567890123456789"
    content = json.dumps({**body, "field_values": {str(f1): "VALUE"}}).replace(
        '"VALUE"', digits
    )
    row = ok(
        client.post(
            "/api/v1/records",
            content=content,
            headers={"Content-Type": "application/json"},
        ),
        201,
    )
    assert row["field_values"] == {str(f1): digits}
    url = f"/api/v1/records/{row['id']}"

    def reassign(**extra):
        return client.patch(
            url,
            json={"type_id": second["id"], **extra},
            headers={"If-Match": str(row["version"])},
        )

    assert reassign().status_code == 409
    assert (
        reassign(confirm_type_change=True, field_values={str(f1): 1}).status_code == 422
    )
    assert ok(client.get(url))["field_values"] == row["field_values"]
    assert ok(reassign(confirm_type_change=True))["field_values"] == {str(f2): "0.00"}
    history = ok(client.get(url + "/history"))
    assert any(
        e["operation"] == "TYPE_METADATA_CHANGED"
        and e["metadata"].get("before", {}).get("field_values") == row["field_values"]
        for e in history
    )
    assert (
        ok(client.get(f"/api/v1/aggregations/{aggregation['id']}"))["type_id"] is None
    )


def test_governance_has_to_supply_its_own_clearance(client, record, catalogue):
    # A high-clearance ordinary role cannot lend clearance to a lower governor.
    uid, role_id = _grant_principal({"record.view"}, clearance_code="TS")
    _set_record_acl(record["id"], role_id, {"record.view"})
    t = ok(client.post("/api/v1/record-types", json={"name": "Governance check"}), 201)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        c.execute(
            "UPDATE aggregations SET security_level_id=4 WHERE id=%s",
            (record["aggregation_id"],),
        )
        c.execute(
            "UPDATE records SET type_id=%s,security_level_id=4 WHERE id=%s",
            (t["id"], record["id"]),
        )
        gov = c.execute(
            """INSERT INTO roles(org_unit_id,code,name,is_information_governance,security_level_id)
                 VALUES(1,'low-governor','Low governor',true,1) RETURNING id"""
        ).fetchone()["id"]
        c.execute(
            "INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)",
            (uid, gov),
        )
        c.commit()
        _login_as_phase7(client)
        url = f"/api/v1/records/{record['id']}"
        assert client.get(url).status_code == 404
        assert ok(client.get("/api/v1/record-types/options"))[0]["id"] == t["id"]
        c.execute("UPDATE roles SET security_level_id=4 WHERE id=%s", (gov,))
        c.commit()
        ok(client.get(url))
        event = c.execute(
            """SELECT metadata FROM event_history WHERE entity_id=%s AND actor_user_id=%s
               AND operation='INFORMATION_GOVERNANCE_BYPASS_USED' ORDER BY id DESC LIMIT 1""",
            (record["id"], uid),
        ).fetchone()
        assert event["metadata"]["resource_type_bypass"]
        assert [r["id"] for r in event["metadata"]["qualifying_roles"]] == [gov]
        c.execute(
            "UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s", (gov,)
        )
        c.commit()
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(("kind", "other"), [("aggregation", "record"), ("record", "aggregation")])
def test_delegated_catalogue_permission_is_kind_specific(client, catalogue, kind, other):
    _grant_principal({f"{kind}_types.administer"})
    _login_as_phase7(client)
    root = f"/api/v1/{kind}-types"
    other_root = f"/api/v1/{other}-types"
    t = ok(client.post(root, json={"name": "Delegated"}), 201)
    assert ok(client.get(f"{root}/options")) == []
    assert client.get(f"{root}/options/{t['id']}/fields").status_code == 404
    assert client.get(other_root).status_code == 403
    assert client.post(other_root, json={"name": "Forbidden"}).status_code == 403
    assert client.put(f"{root}/{t['id']}", json={"name": "Changed"}).status_code == 428


def test_role_revoke_while_writer_waits(client, record, catalogue):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from backend.services.api.continuity_lock import (
        acquire_continuity_lock,
        CONTINUITY_LOCK_NAMESPACE,
    )

    uid, role = _grant_principal({"record.view", "record.modify"})
    _set_record_acl(record["id"], role, {"record.view", "record.modify_metadata"})
    url = f"/api/v1/records/{record['id']}"
    t = ok(client.post("/api/v1/record-types", json={"name": "Atomic"}), 201)
    row = ok(
        client.patch(
            url,
            json={"type_id": t["id"]},
            headers={"If-Match": str(ok(client.get(url))["version"])},
        )
    )
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        c.execute(
            "INSERT INTO resource_type_role_grants VALUES ('record',%s,%s,true)",
            (t["id"], role),
        )
        c.commit()
        _login_as_phase7(client)
        with ThreadPoolExecutor(max_workers=1) as pool:
            acquire_continuity_lock(c)
            try:
                call = pool.submit(
                    client.patch,
                    url,
                    json={"title": "Revoked writer"},
                    headers={"If-Match": str(row["version"])},
                )
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    if c.execute(
                        """SELECT 1 FROM pg_locks WHERE locktype='advisory' AND classid=%s
                                         AND objid=1 AND NOT granted AND pid<>pg_backend_pid()""",
                        (CONTINUITY_LOCK_NAMESPACE,),
                    ).fetchone():
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Writer did not wait for the policy transaction")
                c.execute(
                    "UPDATE resource_type_role_grants SET can_use=false WHERE role_id=%s",
                    (role,),
                )
                c.commit()
            finally:
                c.rollback()
            assert call.result(timeout=10).status_code == 403
        assert ok(client.get(url))["title"] == record["title"]


def test_no_qualified_custodian_rejects_assignment_and_policy_change(
    client, record, catalogue
):
    t = ok(client.post("/api/v1/record-types", json={"name": "Protected"}), 201)
    url = f"/api/v1/records/{record['id']}"
    assigned = ok(
        client.patch(
            url, json={"type_id": t["id"]}, headers={"If-Match": str(record["version"])}
        )
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        # Keep all administrator privileges and explicit view/use but remove
        # the only effective governance appointment.
        c.execute(
            "INSERT INTO resource_type_role_grants VALUES ('record',%s,1,true)",
            (t["id"],),
        )
        c.execute("UPDATE roles SET is_information_governance=false WHERE id=1")
    _set_record_acl(record["id"], 1, {"record.view", "record.modify_metadata"})
    assigned = ok(client.get(url))
    response = client.patch(
        url, json={"type_id": None}, headers={"If-Match": str(assigned["version"])}
    )
    assert response.status_code == 409, response.text
    scope = f"/api/v1/record-types/{t['id']}"
    response = client.put(
        scope + "/role-grants",
        json={"see_role_ids": [], "use_role_ids": []},
        headers={"If-Match": str(t["version"])},
    )
    assert response.status_code == 409, response.text
    assert ok(client.get(url))["type_id"] == t["id"]
    assert ok(client.get(scope + "/role-grants")) == [{"role_id": 1, "can_use": True}]


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_history_keeps_transition_and_redacts_each_side(
    client, record, aggregation, catalogue, kind
):
    endpoint = f"/api/v1/{kind}-types"
    types = [
        ok(client.post(endpoint, json={"name": name}), 201)
        for name in ("Investigation", "Correspondence")
    ]
    fields = [
        ok(
            client.post(
                f"{endpoint}/{t['id']}/fields",
                json={
                    "name": "Subject",
                    "data_type": "text",
                    "max_length": 80,
                    "display_order": 1,
                },
                headers={"If-Match": str(t["version"])},
            ),
            201,
        )["id"]
        for t in types
    ]
    old_definition = f"{endpoint}/{types[0]['id']}"

    def old_version():
        return {"If-Match": str(ok(client.get(old_definition))["version"])}

    risk = ok(
        client.post(
            old_definition + "/fields",
            headers=old_version(),
            json={
                "name": "Investigation finding",
                "display_order": 2,
                "data_type": "single_choice",
            },
        ),
        201,
    )
    finding = ok(
        client.post(
            f"{old_definition}/fields/{risk['id']}/choices",
            headers=old_version(),
            json={
                "name": "Evidence confirmed",
                "display_order": 1,
            },
        ),
        201,
    )
    old_values = {
        str(fields[0]): "Former private subject",
        str(risk["id"]): finding["id"],
    }
    row = record if kind == "record" else aggregation
    path = f"/api/v1/{kind}s/{row['id']}"
    uid, role = _grant_principal({f"{kind}.view", "audit.view"})
    acl = _set_record_acl if kind == "record" else _set_aggregation_acl
    acl(row["id"], role, {f"{kind}.view", f"{kind}.history.view"})
    for t, f, value in zip(
        types, fields, ("Former private subject", "Current subject")
    ):
        response = client.patch(
            path,
            json={
                "type_id": t["id"],
                "field_values": old_values if t == types[0] else {str(f): value},
                "confirm_type_change": True,
            },
            headers={"If-Match": str(ok(client.get(path))["version"])},
        )
        ok(response)
    # A later catalogue rename cannot change the names recorded at reassignment.
    ok(
        client.put(
            old_definition, headers=old_version(), json={"name": "Investigation files"}
        )
    )
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:

        def grant(t):
            c.execute(
                "INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) VALUES (%s,%s,%s,false)",
                (kind, t["id"], role),
            )
            c.commit()

        grant(types[1])
        _login_as_phase7(client)

        def check(allowed):
            history = ok(client.get(path + "/history"))
            event = next(
                e
                for e in history
                if e["operation"] == "TYPE_METADATA_CHANGED"
                and e["metadata"]["after"]["type_id"] == types[1]["id"]
            )
            assert event["metadata"]["before"]["type_name"] == "Investigation"
            assert event["metadata"]["after"]["type_name"] == "Correspondence"
            assert event["metadata"]["after"]["field_values"] == {
                str(fields[1]): "Current subject"
            }
            before = event["metadata"]["before"]
            if allowed:
                assert before["field_values"] == old_values
            else:
                assert before == {
                    "type_id": types[0]["id"],
                    "type_name": "Investigation",
                    "values_withheld": True,
                }
                assert "Former private subject" not in str(history)
                ordinary = next(
                    e
                    for e in history
                    if e["operation"] == "UPDATE"
                    and (e["after_state"] or {}).get("type_id") == types[1]["id"]
                )
                assert ordinary["before_state"] == before
            assert (
                ok(client.get(f"/api/v1/event-history/{event['id']}"))["metadata"]
                == event["metadata"]
            )
            search = ok(
                client.post(
                    "/api/v1/event-history/search",
                    json={
                        "where": {
                            "field": "id",
                            "operator": "eq",
                            "value": event["id"],
                        },
                        "limit": 1,
                    },
                )
            )
            assert search["items"][0]["metadata"] == event["metadata"]
            return event["id"]

        check(False)
        grant(types[0])
        check(True)
        c.execute(
            "DELETE FROM resource_type_role_grants WHERE kind=%s AND type_id=%s AND role_id=%s",
            (kind, types[0]["id"], role),
        )
        c.commit()
        check(False)
        c.execute(
            "UPDATE roles SET is_information_governance=true WHERE id=%s", (role,)
        )
        c.commit()
        check(True)
        c.execute(
            "UPDATE roles SET is_information_governance=false WHERE id=%s", (role,)
        )
        c.commit()
        event_id = check(False)
        acl(row["id"], role, {f"{kind}.view"})
        assert client.get(path + "/history").status_code in (403, 404)
        envelope = ok(client.get(f"/api/v1/event-history/{event_id}"))
        assert envelope["metadata"] == {
            "redacted": True,
            "reason": "resource_access_denied",
        }
        assert envelope["before_state"] is None and envelope["after_state"] is None
        c.execute("DELETE FROM resource_type_role_grants WHERE role_id=%s", (role,))
        c.commit()
        assert client.get(path + "/history").status_code == 404


@pytest.mark.parametrize("kind", ["record", "aggregation"])
def test_older_transition_checks_both_sides_when_current_type_is_third(
    client, record, aggregation, catalogue, kind
):
    resource = record if kind == "record" else aggregation
    path = f"/api/v1/{kind}s/{resource['id']}"
    types_url = f"/api/v1/{kind}-types"
    type_ids = []
    field_ids = []
    for name in ("Investigation", "Correspondence", "Archive"):
        definition = ok(client.post(types_url, json={"name": name}), 201)
        type_ids.append(definition["id"])
        field = ok(
            client.post(
                f"{types_url}/{definition['id']}/fields",
                json={"name": "Subject", "data_type": "text", "max_length": 80,
                      "display_order": 1},
                headers={"If-Match": str(definition["version"])},
            ),
            201,
        )
        field_ids.append(str(field["id"]))
        ok(client.patch(
            path,
            json={"type_id": definition["id"], "confirm_type_change": True,
                  "field_values": {str(field["id"]): name + " subject"}},
            headers={"If-Match": str(ok(client.get(path))["version"])},
        ))

    _, role = _grant_principal({f"{kind}.view", "audit.view"})
    acl = _set_record_acl if kind == "record" else _set_aggregation_acl
    acl(resource["id"], role, {f"{kind}.view", f"{kind}.history.view"})
    _login_as_phase7(client)

    def older_transition():
        return next(
            event["metadata"] for event in ok(client.get(path + "/history"))
            if event["operation"] == "TYPE_METADATA_CHANGED"
            and event["metadata"]["after"]["type_id"] == type_ids[1]
        )

    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        # See on the current Archive type lets this viewer read the timeline.
        for type_id in (type_ids[0], type_ids[2]):
            c.execute(
                "INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) VALUES (%s,%s,%s,false)",
                (kind, type_id, role),
            )
        c.commit()
        transition = older_transition()
        assert transition["before"]["field_values"] == {field_ids[0]: "Investigation subject"}
        assert transition["after"] == {
            "type_id": type_ids[1], "type_name": "Correspondence", "values_withheld": True
        }
        c.execute(
            "DELETE FROM resource_type_role_grants WHERE kind=%s AND type_id=%s AND role_id=%s",
            (kind, type_ids[0], role),
        )
        c.commit()
        hidden = older_transition()
        assert hidden["before"] == {
            "type_id": type_ids[0], "type_name": "Investigation", "values_withheld": True
        }
        assert hidden["after"] == transition["after"]


def test_bulk_drop_and_draft_apply_type_before_writing(client, aggregation, catalogue):
    import json
    from .test_aggregation_file_drop import drop

    definition = ok(client.post("/api/v1/record-types", json={"name": "Intake"}), 201)
    t = definition["id"]
    field = ok(
        client.post(
            f"/api/v1/record-types/{t}/fields",
            headers={"If-Match": "1"},
            json={
                "name": "Sequence",
                "data_type": "integer",
                "required": True,
                "display_order": 1,
            },
        ),
        201,
    )["id"]
    assert drop(client, aggregation, data={"type_id": str(t)}).status_code == 422
    assert ok(client.get("/api/v1/records")) == []
    assert (
        ok(
            drop(
                client,
                aggregation,
                data={"type_id": str(t), "field_values": json.dumps({str(field): 0})},
            ),
            201,
        )["count"]
        == 2
    )
    rows = ok(client.get("/api/v1/records"))
    assert all(r["type_id"] == t and r["field_values"] == {str(field): 0} for r in rows)
    draft = ok(
        client.post(
            "/api/v1/record-drafts",
            json={
                "aggregation_id": aggregation["id"],
                "title": "Draft",
                "medium": "digital",
                "record_number": "DRAFT-TYPE",
            },
        ),
        201,
    )
    url = f"/api/v1/record-drafts/{draft['id']}/commit"
    assert client.post(url, json={"type_id": t}).status_code == 422
    created = ok(
        client.post(url, json={"type_id": t, "field_values": {str(field): 5}}), 201
    )
    assert ok(client.get(f"/api/v1/records/{created['id']}"))["field_values"] == {
        str(field): 5
    }

    _, role = _grant_principal({"aggregation.view", "record.create", "record.view"})
    _set_aggregation_acl(
        aggregation["id"], role, {"aggregation.view", "aggregation.add_record"}
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute(
            "INSERT INTO resource_type_role_grants VALUES ('record',%s,%s,false)",
            (t, role),
        )
        c.commit()
        _login_as_phase7(client)
        counts = "SELECT (SELECT count(*) FROM records),(SELECT count(*) FROM digital_components)"
        before = c.execute(counts).fetchone()
        denied = drop(
            client,
            aggregation,
            data={"type_id": str(t), "field_values": json.dumps({str(field): 8})},
        )
        assert (
            denied.status_code == 403
            and denied.json()["detail"]["code"] == "insufficient_type_access"
        )
        assert c.execute(counts).fetchone() == before


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_reassignment_requires_use_on_both_types_from_any_effective_roles(
    client, record, aggregation, catalogue, kind
):
    row = record if kind == "record" else aggregation
    endpoint = f"/api/v1/{kind}-types"
    old, new = [
        ok(client.post(endpoint, json={"name": name}), 201)["id"] for name in ("A", "B")
    ]
    url = f"/api/v1/{kind}s/{row['id']}"
    current = ok(
        client.patch(
            url, headers={"If-Match": str(row["version"])}, json={"type_id": old}
        )
    )
    uid, owner_role = _grant_principal({f"{kind}.view", f"{kind}.modify"})
    acl = _set_record_acl if kind == "record" else _set_aggregation_acl
    acl(row["id"], owner_role, {f"{kind}.view", f"{kind}.modify_metadata"})
    _login_as_phase7(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        second_role = connection.execute(
            """
            INSERT INTO roles(org_unit_id,code,name,security_level_id)
            SELECT org_unit_id,'type-grant','Type grant',security_level_id FROM roles WHERE id=%s RETURNING id
        """,
            (owner_role,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)",
            (uid, second_role),
        )
        connection.execute(
            "INSERT INTO resource_type_role_grants VALUES (%s,%s,%s,true),(%s,%s,%s,false)",
            (kind, old, owner_role, kind, new, second_role),
        )
        connection.commit()

        def move():
            return client.patch(
                url,
                headers={"If-Match": str(ok(client.get(url))["version"])},
                json={"type_id": new, "confirm_type_change": True},
            )

        assert move().status_code == 403
        connection.execute(
            "UPDATE resource_type_role_grants SET can_use=(type_id=%s) WHERE kind=%s",
            (new, kind),
        )
        connection.commit()
        assert move().status_code == 403
        connection.execute(
            "UPDATE resource_type_role_grants SET can_use=true WHERE kind=%s", (kind,)
        )
        connection.execute(
            """UPDATE user_role_assignments SET valid_from=CURRENT_TIMESTAMP-INTERVAL '2 days',
                           valid_until=CURRENT_TIMESTAMP-INTERVAL '1 day' WHERE role_id=%s""",
            (second_role,),
        )
        connection.commit()
        assert move().status_code == 403
        assert ok(client.get(url))["type_id"] == current["type_id"]
        connection.execute(
            "UPDATE user_role_assignments SET valid_until=NULL WHERE role_id=%s",
            (second_role,),
        )
        connection.commit()
        assert ok(move())["type_id"] == new


def test_component_list_and_upload_follow_owning_records_type(
    client, record, catalogue
):
    r = record["id"]
    t = ok(
        client.post(
            "/api/v1/record-types", json={"name": "Restricted component parent"}
        ),
        201,
    )
    ok(
        client.patch(
            f"/api/v1/records/{r}",
            headers={"If-Match": str(record["version"])},
            json={"type_id": t["id"]},
        )
    )

    def upload(position):
        return client.post(
            f"/api/v1/records/{r}/digital-components/upload",
            files={"file": ("attachment.txt", b"content", "text/plain")},
            data={"component_order": position},
        )

    existing = ok(upload(1), 201)
    _, role = _grant_principal(
        {"record.view", "record.component.add", "record.component.list"}
    )
    _set_record_acl(
        r, role, {"record.view", "record.component.list", "record.component.add"}
    )
    _login_as_phase7(client)

    def assert_listing(ids):
        rows = ok(client.get("/api/v1/digital-components", params={"record_id": r}))
        assert [item["id"] for item in rows] == ids
        result = ok(
            client.post(
                "/api/v1/digital-components/search",
                json={"where": {"field": "record_id", "operator": "eq", "value": r}},
            )
        )
        assert [item["id"] for item in result["items"]] == ids and result[
            "total"
        ] == len(ids)

    assert_listing([])
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute(
            "INSERT INTO resource_type_role_grants VALUES ('record',%s,%s,false)",
            (t["id"], role),
        )
        c.commit()
        assert_listing([existing["id"]])
        assert upload(2).status_code == 403
        c.execute(
            "UPDATE resource_type_role_grants SET can_use=true WHERE role_id=%s",
            (role,),
        )
        c.commit()
        added = ok(upload(2), 201)
        assert_listing([existing["id"], added["id"]])
