"""Measure the type UI's HTTP requests on the standard structured search fixture."""

import json
from time import perf_counter
from unittest.mock import patch

import psycopg


def role_page_plan(client, path, params):
    """Explain the selector's own SQL and parameters outside timed requests."""
    plans = []
    execute = psycopg.Connection.execute

    def capture(connection, statement, values=None, **kwargs):
        if isinstance(statement, str) and "FROM roles r LEFT JOIN resource_type_role_grants" in statement:
            plan = execute(connection, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, values)
            plans.append(plan.fetchone()["QUERY PLAN"])
        return execute(connection, statement, values, **kwargs)

    with patch.object(psycopg.Connection, "execute", capture):
        client.get(path, params=params).raise_for_status()
    plan, = plans
    return {"route": path, "params": params, "plan": plan}


def exercise(db, client, output, repeats):
    samples = []
    role_plans = []
    db.execute(
        "SELECT set_config('app.event_source','seeding',true), set_config('app.change_reason','Synthetic UI role directory',true)"
    )
    db.execute("""INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id)
        SELECT 'UI-ROLE-'||n,'Directory '||lpad(n::text,4,'0'),r.org_unit_id,r.profile_id,r.security_level_id
        FROM roles r CROSS JOIN generate_series(1,1200) n WHERE r.code='PERF'""")
    # A policy edit on a populated type requires a qualified custodian.
    # Keep the ordinary reader who performs the measured requests separate.
    db.execute("""WITH custodian_role AS (
        INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id,is_information_governance)
        SELECT 'UI-CUSTODIAN','Type policy custodian',org_unit_id,profile_id,
            (SELECT id FROM security_levels ORDER BY level_number DESC LIMIT 1),true
        FROM roles WHERE code='PERF' RETURNING id
    ), custodian AS (
        INSERT INTO users(name,email) VALUES ('Type policy custodian','custodian@performance.invalid') RETURNING id
    ) INSERT INTO user_role_assignments(user_id,role_id)
        SELECT custodian.id,custodian_role.id FROM custodian CROSS JOIN custodian_role""")
    db.commit()
    for kind in ("aggregation", "record"):
        root = f"/api/v1/{kind}-types"
        fields = db.execute(
            """SELECT id,type_id,name FROM resource_type_fields
            WHERE kind=%s AND name IN ('Reference','Priority') ORDER BY name""",
            (kind,),
        ).fetchall()
        choice, reference = fields

        def ids(query, args):
            return [row["id"] for row in db.execute(query, args)]

        types = ids(
            "SELECT id FROM resource_types WHERE kind=%s ORDER BY name,id", (kind,)
        )
        allowed = ids(
            """SELECT DISTINCT t.name, t.id FROM resource_types t JOIN resource_type_role_grants g
            ON (g.kind,g.type_id)=(t.kind,t.id) JOIN roles r ON r.id=g.role_id AND r.code='PERF'
            WHERE t.kind=%s ORDER BY t.name,t.id""",
            (kind,),
        )
        roles = ids(
            "SELECT id FROM roles WHERE name LIKE 'Directory %%' ORDER BY name,id",
            (),
        )
        field_ids = ids(
            "SELECT id FROM resource_type_fields WHERE kind=%s AND type_id=%s ORDER BY display_order,id",
            (kind, reference["type_id"]),
        )
        choices = ids(
            "SELECT id FROM resource_field_choices WHERE field_id=%s ORDER BY display_order,id",
            (choice["id"],),
        )
        for route, query, expected, order in [
            (root, "", types, "name"),
            (root + "/options", "", allowed, "name"),
            (root + f"/{reference['type_id']}/fields", "", field_ids, "display_order"),
            (
                root + f"/{choice['type_id']}/fields/{choice['id']}/choices",
                "",
                choices,
                "display_order",
            ),
            (
                root + f"/{reference['type_id']}/role-options",
                "Directory",
                roles,
                "name",
            ),
            (
                root + f"/options/{reference['type_id']}/fields",
                "",
                field_ids,
                "display_order",
            ),
            (
                root + f"/options/{choice['type_id']}/fields/{choice['id']}/choices",
                "",
                choices,
                "display_order",
            ),
        ]:
            for round_no in range(repeats):
                for offset in sorted({0, 25, max(0, ((len(expected) - 1) // 25) * 25)}):
                    params = {
                        "paged": True,
                        "q": query,
                        "limit": 25,
                        "offset": offset,
                        "sort": order,
                        "descending": False,
                    }
                    start = perf_counter()
                    response = client.get(route, params=params)
                    duration = perf_counter() - start
                    response.raise_for_status()
                    page = response.json()
                    assert page["total"] == len(expected)
                    received = [r["id"] for r in page["items"]]
                    assert received == expected[offset : offset + 25]
                    samples.append(
                        dict(
                            route=route,
                            params=params,
                            round=round_no + 1,
                            seconds=duration,
                            total=page["total"],
                            ids=received,
                        )
                    )
        for round_no in range(repeats):
            for route, params, expected in [
                (root + "/options", {"access": "use", "paged": True, "limit": 25}, []),
                (
                    root + f"/options/{reference['type_id']}/fields",
                    {"access": "see", "selected": reference["id"], "limit": 1},
                    [reference["id"]],
                ),
                (
                    root
                    + f"/options/{choice['type_id']}/fields/{choice['id']}/choices",
                    {"access": "see", "selected": choices[-1], "limit": 1},
                    [choices[-1]],
                ),
            ]:
                start = perf_counter()
                response = client.get(route, params=params)
                duration = perf_counter() - start
                response.raise_for_status()
                result = response.json()
                items = result["items"] if params.get("paged") else result
                received = [r["id"] for r in items]
                assert received == expected
                samples.append(
                    dict(
                        route=route,
                        params=params,
                        round=round_no + 1,
                        seconds=duration,
                        ids=received,
                        total=len(received),
                    )
                )
        grant_path = root + f"/{reference['type_id']}/role-options"
        db.execute("SELECT set_config('app.event_source','seeding',true)")
        db.execute("""INSERT INTO resource_type_role_grants(kind,type_id,role_id)
                      SELECT %s,%s,id FROM unnest(%s::bigint[]) AS role(id)""",
                   (kind, reference["type_id"], roles[::2]))
        db.commit()
        for scope, expected in (("granted", roles[::2]), ("available", roles[1::2])):
            for n in range(repeats):
                queries = [
                    (term, offset, expected) for term in ("Directory", "i-RoLe-")
                    for offset in (0, len(expected) - 25)
                ]
                queries.append(("role-1200", 0, [roles[-1]] if scope == "available" else []))
                for term, offset, matches in queries:
                    params = dict(scope=scope, q=term, limit=25, offset=offset)
                    start = perf_counter()
                    response = client.get(grant_path, params=params)
                    elapsed = perf_counter() - start
                    response.raise_for_status()
                    body = response.json()
                    received = [r["id"] for r in body["items"]]
                    assert body["total"] == len(matches) and received == matches[offset:offset+25]
                    samples.append(dict(route=grant_path, params=params, round=n + 1, seconds=elapsed,
                                        total=body["total"], ids=received))
            for term in ("i-RoLe-", "role-1200"):
                role_plans.append(role_page_plan(client, grant_path, dict(scope=scope, q=term, limit=25)))
        owner = root + f"/{reference['type_id']}"
        version_response = client.get(owner)
        version_response.raise_for_status()
        version = version_response.json()["version"]
        available = roles[1::2]
        for n in range(min(repeats, len(available))):
            batch = available[n::repeats]
            payload = [{"role_id": role_id, "can_use": i % 2 == 0} for i, role_id in enumerate(batch)]
            start = perf_counter()
            response = client.post(owner + "/role-grants", headers={"If-Match": str(version)}, json=payload)
            elapsed = perf_counter() - start
            assert response.is_success, response.text
            assert response.json()["version"] == version + 1
            version += 1
            granted = db.execute("""SELECT role_id,can_use FROM resource_type_role_grants
                WHERE kind=%s AND type_id=%s AND role_id=ANY(%s) ORDER BY role_id""",
                (kind, reference["type_id"], batch)).fetchall()
            assert {r["role_id"]: r["can_use"] for r in granted} == {r["role_id"]: r["can_use"] for r in payload}
            samples.append(dict(route=owner + "/role-grants", round=n+1, seconds=elapsed, ids=batch, total=len(batch)))
        route = owner + f"/fields/{field_ids[-1]}/position"
        for round_no in range(repeats):
            for position in (1, len(field_ids)):
                start = perf_counter()
                response = client.put(route, headers={"If-Match": str(version)}, json={"position": position})
                duration = perf_counter() - start
                response.raise_for_status()
                version = response.json()["type_version"]
                observed = db.execute(
                    """SELECT id, display_order FROM resource_type_fields WHERE kind=%s AND type_id=%s
                       ORDER BY display_order""", (kind, reference["type_id"]),
                ).fetchall()
                expected = [field_ids[-1], *field_ids[:-1]] if position == 1 else field_ids
                assert [(r["id"], r["display_order"]) for r in observed] == list(zip(expected, range(1, len(expected)+1)))
                samples.append(dict(route=route, position=position, round=round_no+1, seconds=duration,
                                    ids=expected, total=len(expected)))
    (output / "type-ui-pages.json").write_text(json.dumps(samples, indent=2))
    (output / "type-role-filter-plans.json").write_text(json.dumps(role_plans, indent=2))
    assert all(
        s["seconds"] <= 3 for s in samples
    ), "A type UI response exceeded three seconds"
