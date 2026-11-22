"""Measure the type UI's HTTP requests on the standard structured search fixture."""

import json
from time import perf_counter


def exercise(db, client, output, repeats):
    samples = []
    db.execute(
        "SELECT set_config('app.event_source','seeding',true), set_config('app.change_reason','Synthetic UI role directory',true)"
    )
    db.execute("""INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id)
        SELECT 'UI-'||n,'Directory '||lpad(n::text,4,'0'),r.org_unit_id,r.profile_id,r.security_level_id
        FROM roles r CROSS JOIN generate_series(1,1200) n WHERE r.code='PERF'""")
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
    (output / "type-ui-pages.json").write_text(json.dumps(samples, indent=2))
    assert all(
        s["seconds"] <= 3 for s in samples
    ), "A type UI response exceeded three seconds"
