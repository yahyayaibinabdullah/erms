"""Exercise the bounded, authorized API reads and individual grant edits used by the WebUI."""

import os

import psycopg
import pytest

from .test_phase7_mutation_authorization import _grant_principal, _login_as_phase7
from .test_resource_type_access import catalogue, ok


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_add_grants_as_one_policy_edit(client, catalogue, kind):
    root = f"/api/v1/{kind}-types"
    owner = ok(client.post(root, json={"name": "Employee File"}), 201)
    url = f"{root}/{owner['id']}"
    _, role = _grant_principal(set())
    options = url + "/role-options"
    grants = url + "/role-grants"
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("""UPDATE roles SET code='HR-CASE_42',translations='{"ar":{"name":"مسؤول الموظفين"}}'
                     WHERE id=%s""", (role,))

    def matches(scope, query):
        page = ok(client.get(options, params={"scope": scope, "q": query, "limit": 1}))
        return page["total"], [r["id"] for r in page["items"]]

    for query in ("HR-CASE_42", "  r-cAsE_4  ", "Phase 7 role", "الموظفين"):
        assert matches("available", query) == (1, [role])
    assert matches("all", "case_4") == (1, [role])
    assert matches("granted", "case_4") == (0, [])
    assert matches("available", "case%42") == (0, [])
    headers = {"If-Match": str(owner["version"])}
    available = ok(client.get(options, params={"scope": "available"}))["items"]
    existing = next(r["id"] for r in available if r["id"] not in (role, "everyone"))
    version = ok(client.put(grants + f"/{existing}", headers=headers,
                            json={"can_see": True, "can_use": False}))["version"]
    headers = {"If-Match": str(version)}
    everyone = {"role_id": "everyone", "can_use": False}
    named = {"role_id": role, "can_use": True}
    for body, status in (([], 422), ([everyone, everyone], 422),
                         ([everyone, {"role_id": existing, "can_use": True}], 409),
                         ([everyone, {"role_id": 2**63-1, "can_use": False}], 409),
                         ([everyone, {"role_id": True, "can_use": False}], 422)):
        assert client.post(grants, headers=headers, json=body).status_code == status
    assert ok(client.get(url))["version"] == version
    assert ok(client.get(options, params={"scope": "granted"}))["total"] == 1
    assert client.post(grants, headers={"If-Match": str(version-1)}, json=[named, everyone]).status_code == 412
    assert client.post(f"{root}/-1/role-grants", headers=headers, json=[named]).status_code == 404
    assert ok(client.post(grants, headers=headers, json=[named, everyone]))["version"] == version+1
    assert matches("granted", "case_4") == (1, [role])
    assert matches("available", "case_4") == (0, [])
    members = ok(client.get(options, params={"scope": "granted"}))["items"]
    assert {r["id"]: r["can_use"] for r in members} == {existing: False, role: True, "everyone": False}
    assert all(r["can_see"] for r in members)
    _login_as_phase7(client)
    assert client.post(grants, headers={"If-Match": str(version+1)}, json=[everyone]).status_code == 403


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_catalogue_pages_and_role_policy(client, catalogue, kind):
    root = f"/api/v1/{kind}-types"
    owner = ok(client.post(root, json={"name": "Catalogue"}), 201)
    url = f"{root}/{owner['id']}"
    _, role = _grant_principal(set())
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute(
            """INSERT INTO resource_types(kind,name)
                       SELECT %s, 'Paged ' || lpad(i::text,3,'0') FROM generate_series(1,130) i""",
            (kind,),
        )
    params = {"q": "Paged", "paged": True, "offset": 125, "limit": 25}
    last = ok(client.get(root, params=params))
    assert last["total"] == 130 and [r["name"] for r in last["items"]] == [
        f"Paged {n:03}" for n in range(126, 131)
    ]

    def headers():
        return {"If-Match": str(ok(client.get(url))["version"])}

    for invalid_limit in (0, -1, 1.5, 2_147_483_648):
        assert client.post(url + "/fields", headers=headers(),
                           json={"name": "Invalid length", "data_type": "text",
                                 "max_length": invalid_limit}).status_code == 422

    field = ok(
        client.post(
            url + "/fields",
            headers=headers(),
            json={"name": "Grade", "data_type": "single_choice", "display_order": 1},
        ),
        201,
    )
    choices = url + f"/fields/{field['id']}/choices"
    choice = ok(
        client.post(
            choices,
            headers=headers(),
            json={
                "name": "High",
                "translations": {"ar": {"name": "عال"}},
                "display_order": 1,
            },
        ),
        201,
    )
    assert ok(client.get(choices, params={"paged": True, "q": "عال"}))["total"] == 1
    grant = url + f"/role-grants/{role}"
    stale = headers()
    assert (
        client.put(
            grant, json={"can_use": True, "can_see": False}, headers=stale
        ).status_code
        == 422
    )
    ok(client.put(grant, json={"can_see": True, "can_use": True}, headers=stale))
    assert client.put(
        grant, json={"can_see": False, "can_use": False}, headers=stale
    ).status_code in (409, 412)
    role_page = ok(
        client.get(url + "/role-options", params={"q": "Phase 7 role", "limit": 1})
    )
    assert role_page["total"] == 1 and role_page["items"][0]["can_use"]
    ok(client.put(grant, json={"can_see": True, "can_use": False}, headers=headers()))
    _login_as_phase7(client)
    assert client.get(url + "/role-options").status_code == 403
    assert (
        client.put(
            grant, json={"can_see": True, "can_use": True}, headers={"If-Match": "1"}
        ).status_code
        == 403
    )
    assert client.get(root, params={"paged": True}).status_code == 403
    opts = root + "/options"
    visible = ok(client.get(opts, params={"paged": True, "selected": owner["id"]}))
    assert [r["id"] for r in visible["items"]] == [owner["id"]]
    assert ok(client.get(opts, params={"access": "use", "paged": True})) == {
        "total": 0,
        "items": [],
    }
    selected = opts + f"/{owner['id']}"
    assert ok(client.get(selected))["id"] == owner["id"]
    assert client.get(selected, params={"access": "use"}).status_code == 404
    assert client.get(opts + f"/{last['items'][0]['id']}").status_code == 404
    fields = selected + "/fields"
    assert (
        ok(client.get(fields, params={"selected": field["id"]}))[0]["id"] == field["id"]
    )
    assert (
        ok(
            client.get(
                fields + f"/{field['id']}/choices", params={"selected": choice["id"]}
            )
        )[0]["id"]
        == choice["id"]
    )
    assert client.get(fields, params={"access": "use"}).status_code == 404
    assert client.get(opts + f"/{last['items'][0]['id']}/fields").status_code == 404


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_field_positions_are_scoped_atomic_and_versioned(client, catalogue, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    root = f"/api/v1/{kind}-types"
    owner = ok(client.post(root, json={"name": "Positions"}), 201)
    url = f"{root}/{owner['id']}"
    fields = url + "/fields"

    def headers():
        return {"If-Match": str(ok(client.get(url))["version"])}

    def create(name, **extra):
        return ok(client.post(fields, headers=headers(),
                              json={"name": name, "data_type": "integer", **extra}), 201)["id"]

    def ordered():
        rows = ok(client.get(fields, params={"sort": "display_order"}))
        assert [r["display_order"] for r in rows] == list(range(1, len(rows) + 1))
        return [r["id"] for r in rows]

    a, b, c = [create(name) for name in ("A", "B", "C")]
    d = create("D", display_order=2)
    assert ordered() == [a, d, b, c]
    ok(client.put(f"{fields}/{c}", headers=headers(),
                  json={"name": "C", "data_type": "integer", "display_order": 1}))
    assert ordered() == [c, a, d, b]
    # A rejected edit must roll back the adjacent shifts too.
    bad = client.put(f"{fields}/{b}", headers=headers(),
                     json={"name": "C", "data_type": "integer", "display_order": 1})
    assert bad.status_code in (400, 409, 422)
    assert ordered() == [c, a, d, b]
    ok(client.put(f"{fields}/{c}/position", headers=headers(), json={"position": 4}))
    assert ordered() == [a, d, b, c]
    ok(client.delete(f"{fields}/{d}", headers=headers()), 204)
    assert ordered() == [a, b, c]

    # Both requests are based on the same visible order. Exactly one may commit.
    version = headers()
    ready = Barrier(2)
    def move(field):
        ready.wait(timeout=10)
        return client.put(f"{fields}/{field}/position", json={"position": 1}, headers=version).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(move, [b, c])) == [200, 412]
    expected = ordered()
    assert expected in ([b, a, c], [c, a, b])

    other = ok(client.post(root, json={"name": "Other positions"}), 201)
    assert client.put(f"{root}/{other['id']}/fields/{a}/position",
                      headers={"If-Match": str(other["version"])}, json={"position": 1}).status_code == 404
    _grant_principal(set())
    version = headers()
    _login_as_phase7(client)
    assert client.put(f"{fields}/{a}/position", headers=version, json={"position": 1}).status_code == 403


@pytest.mark.parametrize("kind", ["aggregation", "record"])
def test_everyone_grant_combines_with_named_roles_and_revokes(client, catalogue, kind):
    root = f"/api/v1/{kind}-types"
    owner = ok(client.post(root, json={"name": "Shared type"}), 201)
    type_id = owner["id"]
    url = f"{root}/{type_id}"
    uid, role = _grant_principal(set())

    def grant(principal, see, use):
        return client.put(f"{url}/role-grants/{principal}",
                          headers={"If-Match": str(ok(client.get(url))["version"])},
                          json={"can_see": see, "can_use": use})

    def members(scope):
        return ok(client.get(url + "/role-options", params={"scope": scope, "limit": 100}))["items"]

    def access():
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            c.execute("SELECT set_config('app.user_id',%s,true)", (str(uid),))
            return c.execute("""SELECT user_has_type_grant(%s,%s,%s,false),
                                user_has_type_grant(%s,%s,%s,true),
                                coalesce((resource_type_history_access()->'types') ? %s, false),
                                user_has_type_grant(-1,%s,%s,false)""",
                             (uid,kind,type_id, uid,kind,type_id, f"{kind}/{type_id}", kind,type_id)).fetchone()

    assert members("granted") == [] and members("available")[0]["id"] == "everyone"
    assert grant("everyone", False, True).status_code == 422
    ok(grant("everyone", True, False))
    assert access() == (True, False, True, False)
    assert ok(client.get(url + "/role-grants")) == []
    ok(client.put(url + "/role-grants", headers={"If-Match": str(ok(client.get(url))["version"])},
                  json={"see_role_ids": [], "use_role_ids": []}))
    assert access() == (True, False, True, False)
    assert [r["id"] for r in members("granted")] == ["everyone"]
    assert not any(r["id"] == "everyone" for r in members("available"))
    ok(grant(role, True, True))
    assert access() == (True, True, True, False)
    ok(grant("everyone", False, False))
    assert [r["id"] for r in members("granted")] == [role]
    ok(grant(role, False, False))
    assert access() == (False, False, False, False)
    ok(grant("everyone", True, True))
    _login_as_phase7(client)
    assert ok(client.get(root + "/options", params={"access": "use"}))[0]["id"] == type_id
    assert client.put(url + "/role-grants/everyone", headers={"If-Match": "1"},
                      json={"can_see": False, "can_use": False}).status_code == 403
