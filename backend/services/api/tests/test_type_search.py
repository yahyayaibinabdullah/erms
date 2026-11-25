"""Phase 3 structured search and saved-definition disclosure through the public API."""

import os
import json
from uuid import uuid4

import psycopg
import pytest

from .test_resource_type_access import catalogue, ok
from .test_application_settings import save
from .test_full_text_search_phase3 import _grant_phase3_privileges
from .test_phase7_mutation_authorization import _grant_principal, _login_as_phase7
from .test_saved_searches import _payload


@pytest.fixture(params=["record", "aggregation"])
def corpus(client, aggregation, catalogue, request):
    _grant_phase3_privileges()
    ok(save(client, {"FULL_TEXT_SEARCH_ENABLED": True}))
    kind = request.param
    base = f"/api/v1/{kind}-types"

    def create(name):
        return ok(client.post(base, json={"name": name}), 201)["id"]

    a, b = create("Invoice"), create("Contract")

    def field(t, name, dtype):
        url = f"{base}/{t}"
        version = ok(client.get(url))["version"]
        body = dict(name=name, data_type=dtype, display_order=1)
        if dtype == "text":
            body["max_length"] = 100
        return ok(
            client.post(url + "/fields", headers={"If-Match": str(version)}, json=body),
            201,
        )["id"]

    fields = {
        dt: field(a, dt, dt)
        for dt in (
            "text",
            "integer",
            "decimal",
            "boolean",
            "date",
            "datetime",
            "single_choice",
        )
    }
    other = field(b, "integer", "integer")
    choice_url = f"{base}/{a}/fields/{fields['single_choice']}/choices"
    options = []
    for label, pos in [("Alpha urgent", 9), ("Zulu low", 1)]:
        options.append(
            ok(
                client.post(
                    choice_url,
                    json=dict(name=label, display_order=pos),
                    headers={"If-Match": str(ok(client.get(f"{base}/{a}"))["version"])},
                ),
                201,
            )["id"]
        )
    fieldsets = [
        {
            "text": "50% Blue",
            "integer": 0,
            "decimal": "1.0000000000000000001",
            "boolean": False,
            "date": "2024-01-02",
            "datetime": "2024-01-01T02:00:00+02:00",
            "single_choice": options[0],
        },
        {
            "text": "Blue Box",
            "integer": 10,
            "decimal": "1.0000000000000000002",
            "boolean": True,
            "date": "2024-01-03",
            "datetime": "2024-01-01T01:00:00Z",
            "single_choice": options[1],
        },
        {},
        {},
        {},
    ]
    ids = []
    for i, (type_id, values) in enumerate(zip((a, a, a, b, None), fieldsets)):
        body = {
            "title": f"Phase3 {i}",
            kind + "_number": f"P3-{i}",
            "type_id": type_id,
            "field_values": {str(fields[k]): v for k, v in values.items()},
        }
        if type_id == b:
            body["field_values"] = {str(other): 10}
        if kind == "record":
            body["aggregation_id"] = aggregation["id"]
        else:
            body["classification_id"] = 1
        ids.append(ok(client.post(f"/api/v1/{kind}s", json=body), 201)["id"])
    return kind, a, b, fields, other, options, ids


def condition(field, operator, value=None):
    return {
        "field": field,
        "operator": operator,
        **({"value": value} if value is not None else {}),
    }


def test_structured_filter_sort_paging_and_choice_order(client, corpus):
    kind, a, b, fields, other, choices, ids = corpus
    path = f"/api/v1/{kind}s/advanced-search"
    names = {k: f"type.{a}.field.{fid}" for k, fid in fields.items()}

    def search(clause=None, sort=None, **kw):
        where = condition("id", "in", ids)
        if clause:
            where = {"and": [where, clause]}
        return client.post(path, json={"where": where, "sort": sort or [], **kw})

    def item_ids(resp):
        return [i["id"] for i in ok(resp)["items"]]

    url = f"/api/v1/{kind}-types/{a}"
    # An administrator setting a default later cannot populate an older search row.
    ok(
        client.put(
            f"{url}/fields/{fields['integer']}",
            json={
                "name": "integer",
                "data_type": "integer",
                "display_order": 1,
                "default": 99,
            },
            headers={"If-Match": str(ok(client.get(url))["version"])},
        )
    )
    cases = [
        (condition("type_id", "eq", a), ids[:3]),
        (condition("type_id", "is_null"), ids[-1:]),
        (condition("type_id", "in", [a, b]), ids[:-1]),
        (condition(names["integer"], "is_null"), [ids[2]]),
        (condition(names["integer"], "is_not_null"), ids[:2]),
        (condition(names["integer"], "gt", 0), [ids[1]]),
        (condition(names["integer"], "ne", 10), ids[:1]),
        (condition(names["integer"], "not_in", [0]), ids[1:2]),
        (
            condition(names["decimal"], "between", ["1.0000000000000000002", "2"]),
            ids[1:2],
        ),
        (condition(names["boolean"], "eq", False), ids[:1]),
        (condition(names["date"], "lte", "2024-01-02"), ids[:1]),
        (condition(names["datetime"], "gte", "2024-01-01T01:00:00Z"), ids[1:2]),
        (condition(names["text"], "contains_ci", "%"), ids[:1]),
        (condition(names["text"], "starts_with_ci", "blue"), ids[1:2]),
        (condition(names["text"], "ends_with_ci", "BOX"), ids[1:2]),
        (condition(names["text"], "matches_ci", "*bl?e*"), ids[:2]),
        (condition(names["single_choice"], "in", choices), ids[:2]),
        ({"not": condition(names["integer"], "eq", 0)}, ids[1:]),
        (
            {
                "or": [
                    condition(names["integer"], "lt", 10),
                    condition(f"type.{b}.field.{other}", "eq", 10),
                ]
            },
            [ids[0], ids[3]],
        ),
    ]
    # The wire number has more significant digits than a binary float can retain.

    exact = {"where": condition(names["decimal"], "eq", "DECIMAL_LITERAL")}
    raw = json.dumps(exact).replace('"DECIMAL_LITERAL"', "1.0000000000000000002")
    assert (
        item_ids(
            client.post(path, content=raw, headers={"Content-Type": "application/json"})
        )
        == ids[1:2]
    )
    overflow = raw.replace("1.0000000000000000002", "1e999999999999999999999999")
    assert (
        client.post(
            path, content=overflow, headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    saved_decimal = _payload(
        name="Exact decimal",
        definition={
            "schema_version": 1,
            "resource_type": kind,
            "request": {**exact, "limit": 25},
        },
    )
    saved = ok(
        client.post(
            "/api/v1/saved-searches",
            content=json.dumps(saved_decimal).replace(
                '"DECIMAL_LITERAL"', "1.0000000000000000002"
            ),
            headers={"Content-Type": "application/json"},
        ),
        201,
    )
    assert saved["definition"]["request"]["where"]["value"] == "1.0000000000000000002"
    assert (
        item_ids(client.post(f"/api/v1/saved-searches/{saved['id']}/execute", json={}))
        == ids[1:2]
    )
    for clause, expected in cases:
        assert item_ids(search(clause)) == expected, clause
    mixed_text = {
        "and": [
            {"full_text": {"query": "Phase3", "sources": ["metadata"]}},
            {"not": condition(names["integer"], "is_null")},
        ]
    }
    choice_sort = [{"field": names["single_choice"], "direction": "asc"}]
    for runtime in ({}, {"tab_id": str(uuid4())}):
        assert item_ids(search(mixed_text, sort=choice_sort, **runtime)) == [
            ids[1],
            ids[0],
            ids[3],
            ids[4],
        ]
    for dtype in fields:
        asc = [ids[1], ids[0]] if dtype == "single_choice" else ids[:2]
        for direction, order in [("asc", asc), ("desc", asc[::-1])]:
            keys = [
                {"field": names[dtype], "direction": direction},
                {"field": "id", "direction": "desc"},
            ]
            expected = order + ids[2:][::-1]
            assert item_ids(search(sort=keys)) == expected
            tab = str(uuid4())
            first = ok(search(sort=keys, tab_id=tab, limit=2))
            pages = [r["id"] for r in first["items"]]
            for offset in (2, 4):
                pages += item_ids(
                    search(
                        sort=keys,
                        tab_id=tab,
                        limit=2,
                        offset=offset,
                        search_id=first["search_id"],
                    )
                )
            assert pages == expected
    url = f"/api/v1/{kind}-types/{a}"
    tab = str(uuid4())
    keys = [{"field": names["single_choice"], "direction": "asc"}]
    ok(
        client.put(
            f"{url}/fields/{fields['single_choice']}/choices/{choices[0]}",
            headers={"If-Match": str(ok(client.get(url))["version"])},
            json={
                "name": "Aardvark",
                "display_order": 9,
                "translations": {"ar": {"name": "عاجل"}},
            },
        )
    )
    assert item_ids(search(sort=keys)) == [ids[1], ids[0], *ids[2:]]
    first = ok(search(sort=keys, tab_id=tab, limit=1))
    ok(
        client.put(
            f"{url}/fields/{fields['single_choice']}/choices/{choices[0]}",
            headers={"If-Match": str(ok(client.get(url))["version"])},
            json={
                "name": "Highest",
                "translations": {"ar": {"name": "عاجل"}},
                "display_order": 0,
            },
        )
    )
    page = ok(
        search(sort=keys, tab_id=tab, limit=1, offset=1, search_id=first["search_id"])
    )
    assert page["search_id"] != first["search_id"] and page["items"][0]["id"] == ids[1]
    assert (
        item_ids(search(condition(names["single_choice"], "eq", choices[0]))) == ids[:1]
    )
    for clause in (
        condition(names["single_choice"], "eq", "Highest"),
        condition(names["boolean"], "gt", False),
        condition(names["decimal"], "eq", "NaN"),
        condition(names["date"], "eq", "2024-02-30"),
        condition(names["datetime"], "eq", "2024-01-01"),
        condition(names["datetime"], "eq", 1234567),
        condition(names["integer"], "in", []),
        condition(names["integer"], "between", [1]),
        condition(names["integer"], "eq", 2**63),
        condition("type_id", "in", [a] * 101),
        condition("type_id", "eq", 0),
        condition("type_id", "eq", 2**63),
        {"or": [condition(names["boolean"], "eq", True)] * 51},
        condition(f"type.{b}.field.{fields['integer']}", "eq", 0),
        condition("type_id", "gte", a),
        condition(names["integer"] + "; SELECT", "eq", 1),
        condition(names["single_choice"], "eq", 999999),
    ):
        assert search(clause).status_code == 422, clause


def test_saved_definition_disclosure_and_execution(client, corpus):
    kind, a, b, fields, other, choices, ids = corpus
    _, role = _grant_principal({f"{kind}.view"})
    base = "/api/v1/saved-searches"

    def definition(sort_only):
        query = {
            "where": {
                "or": [
                    condition("title", "contains_ci", "Phase3"),
                    {"not": condition("type_id", "eq", b)},
                ]
            },
            "sort": [
                {
                    "field": f"type.{a}.field.{fields['single_choice']}",
                    "direction": "desc",
                }
            ],
            "limit": 25,
        }
        if sort_only:
            query["where"] = condition("title", "contains_ci", "Phase3")
        return {"schema_version": 1, "resource_type": kind, "request": query}

    saved = [
        ok(
            client.post(
                base,
                json=_payload(
                    name=f"Scope {i}",
                    definition=definition(i),
                    audience_mode="shared",
                    role_ids=[role],
                ),
            ),
            201,
        )
        for i in (False, True)
    ]
    _login_as_phase7(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:

        def grant(t):
            c.execute(
                "INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) VALUES (%s,%s,%s,false)",
                (kind, t, role),
            )
            c.commit()

        def check(row, allowed):
            url = f"{base}/{row['id']}"
            entry = next(
                v for v in ok(client.get(base))["items"] if v["id"] == row["id"]
            )
            assert (
                entry["capabilities"]["open"] is allowed
                and entry["capabilities"]["execute"] is allowed
            )
            assert ("definition" in entry) is allowed
            assert client.get(url).status_code == (200 if allowed else 403)
            assert client.post(
                url + "/execute", json={"tab_id": str(uuid4())}
            ).status_code == (200 if allowed else 403)
            if not allowed:
                assert (
                    entry["capability_reasons"]["open"] == "saved_search_type_forbidden"
                )

        for row in saved:
            check(row, False)
        grant(a)
        check(saved[0], False)
        check(saved[1], True)
        grant(b)
        check(saved[0], True)
        # A previously issued list ID cannot bypass revocation.
        tab = str(uuid4())
        url = f"{base}/{saved[0]['id']}"
        token = ok(client.post(url + "/execute", json={"tab_id": tab}))["search_id"]
        c.execute("DELETE FROM resource_type_role_grants WHERE role_id=%s", (role,))
        c.commit()
        assert (
            client.post(
                url + "/execute", json={"tab_id": tab, "search_id": token}
            ).status_code
            == 403
        )
        c.execute(
            """INSERT INTO profile_privileges(profile_id,privilege_id) SELECT r.profile_id,p.id FROM roles r CROSS JOIN privileges p
               WHERE r.id=%s AND p.code='search.saved_search.administer'""",
            (role,),
        )
        c.commit()
        assert (
            ok(client.get(url + "?inspection=true"))["definition"]
            == saved[0]["definition"]
        )
        check(saved[0], False)
        # Administration can relabel an existing definition without acquiring
        # access to author or execute explicit restricted criteria.
        inspected = ok(client.get(url + "?inspection=true"))
        edit = _payload(
            name="Reviewed search",
            definition=inspected["definition"],
            audience_mode="shared",
            role_ids=[role],
        )
        updated = ok(
            client.put(
                url,
                json=edit,
                headers={
                    "If-Match": str(inspected["version"]),
                    "X-Change-Reason": "Update catalogue wording",
                },
            )
        )
        assert "definition" not in updated
        assert (
            ok(client.get(url + "?inspection=true"))["definition"]
            == inspected["definition"]
        )
        edit["definition"]["request"]["sort"][0]["direction"] = "asc"
        assert (
            client.put(
                url,
                json=edit,
                headers={
                    "If-Match": str(updated["version"]),
                    "X-Change-Reason": "Change sort",
                },
            ).status_code
            == 403
        )
        c.execute(
            "UPDATE roles SET is_information_governance=true WHERE id=%s", (role,)
        )
        c.commit()
        check(saved[0], True)


def test_saved_owner_loses_see_and_removed_definition(client, corpus):
    kind, a, b, fields, _, _, _ = corpus
    endpoint = "/api/v1/saved-searches"
    type_url = f"/api/v1/{kind}-types/{a}"
    field = ok(
        client.post(
            type_url + "/fields",
            headers={"If-Match": str(ok(client.get(type_url))["version"])},
            json={"name": "Unused", "data_type": "integer", "display_order": 8},
        ),
        201,
    )
    query = {
        "sort": [{"field": f"type.{a}.field.{field['id']}", "direction": "desc"}],
        "limit": 25,
    }
    saved = ok(
        client.post(
            endpoint,
            json=_payload(
                definition={
                    "schema_version": 1,
                    "resource_type": kind,
                    "request": query,
                }
            ),
        ),
        201,
    )
    url = f"{endpoint}/{saved['id']}"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute(
            "UPDATE roles SET is_information_governance=false WHERE code='system-administrator'"
        )
        c.commit()
        row = next(
            r
            for r in ok(client.get(endpoint, params={"scope": "owned"}))["items"]
            if r["id"] == saved["id"]
        )
        assert "definition" not in row and not row["capabilities"]["open"]
        assert client.post(url + "/execute", json={}).status_code == 403
        c.execute(
            "UPDATE roles SET is_information_governance=true WHERE code='system-administrator'"
        )
        c.commit()
    assert ok(client.get(url))["capabilities"]["open"]
    assert (
        client.delete(
            type_url + f"/fields/{field['id']}",
            headers={"If-Match": str(ok(client.get(type_url))["version"])},
        ).status_code
        == 204
    )
    assert client.post(url + "/execute", json={}).status_code == 422
    row = next(r for r in ok(client.get(endpoint))["items"] if r["id"] == saved["id"])
    assert row["capability_reasons"]["open"] == "search_type_reference_unavailable"


@pytest.mark.parametrize("everyone", [False, True], ids=["named-role", "everyone"])
def test_shared_typed_search_tracks_grant_changes_end_to_end(client, corpus, everyone):
    """The same recipient and cached page follow the administrator's live grant."""
    from fastapi.testclient import TestClient
    from .test_phase7_mutation_authorization import _set_aggregation_acl, _set_record_acl

    kind, owner, _, fields, _, choices, ids = corpus
    _, role = _grant_principal({f"{kind}.view"})
    set_acl = _set_record_acl if kind == "record" else _set_aggregation_acl
    set_acl(ids[0], role, {f"{kind}.view"})
    type_url = f"/api/v1/{kind}-types/{owner}"

    def allow(see):
        version = ok(client.get(type_url))["version"]
        principal = "everyone" if everyone else role
        ok(client.put(f"{type_url}/role-grants/{principal}", headers={"If-Match": str(version)},
                      json={"can_see": see, "can_use": False}))

    query = {
        "where": {"and": [condition("title", "contains_ci", "Phase3"),
                          condition(f"type.{owner}.field.{fields['single_choice']}", "eq", choices[0])]},
        "sort": [{"field": f"type.{owner}.field.{fields['decimal']}", "direction": "desc"}],
        "limit": 25,
    }
    search = f"/api/v1/{kind}s/advanced-search"
    assert [row["id"] for row in ok(client.post(search, json=query))["items"]] == ids[:1]
    shared = ok(client.post("/api/v1/saved-searches", json=_payload(
        name="Shared typed lookup", audience_mode="shared", role_ids=[role],
        definition={"schema_version": 1, "resource_type": kind, "request": query})), 201)
    detail = f"/api/v1/saved-searches/{shared['id']}"
    resource = f"/api/v1/{kind}s/{ids[0]}"
    allow(True)
    # The existing fixture owns the application lifespan. Use separate cookies
    # so revocation and restoration are observed in the original recipient session.
    recipient = TestClient(client.app)
    try:
        _login_as_phase7(recipient)
        tab = {"tab_id": str(uuid4())}
        def global_hits():
            body = ok(recipient.post("/api/v1/full-text-search", json={
                "result_types": [kind + "s"], kind + "_where": {
                    "full_text": {"query": "Phase3", "sources": ["metadata"]}},
                "tab_id": str(uuid4())}))
            return [hit[kind]["id"] for hit in body["items"]]

        assert ids[0] in global_hits()
        page = ok(recipient.post(detail + "/execute", json=tab))
        assert [row["id"] for row in page["items"]] == ids[:1]
        assert ok(recipient.get(resource))["id"] == ids[0]
        allow(False)
        summary = next(r for r in ok(recipient.get("/api/v1/saved-searches"))["items"] if r["id"] == shared["id"])
        assert "definition" not in summary
        assert summary["capability_reasons"]["open"] == "saved_search_type_forbidden"
        assert ids[0] not in global_hits()
        assert recipient.get(resource).status_code == 404
        assert recipient.get(detail).status_code == 403
        assert recipient.post(detail + "/execute", json={**tab, "search_id": page["search_id"]}).status_code == 403
        assert recipient.post(search, json=query).status_code == 403
        assert ok(client.get(resource))["id"] == ids[0]  # Governance retains access.
        allow(True)
        assert ok(recipient.get(detail))["definition"] == shared["definition"]
        assert [r["id"] for r in ok(recipient.post(detail + "/execute", json=tab))["items"]] == ids[:1]
    finally:
        recipient.close()
