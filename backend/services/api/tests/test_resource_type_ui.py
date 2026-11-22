"""Exercise the bounded, authorized API reads and individual grant edits used by the WebUI."""

import os

import psycopg
import pytest

from .test_phase7_mutation_authorization import _grant_principal, _login_as_phase7
from .test_resource_type_access import catalogue, ok


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
