"""Type restriction and governance checks over the standard search fixture."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import time
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row

from tools.check_search_performance import PASSWORD, AGGREGATIONS, RECORDS


def exercise(url, output, repeats):
    from backend.services.api.main import app

    samples = []
    failures = []

    def measured(label, operation):
        start = time.perf_counter()
        response = operation()
        seconds = time.perf_counter() - start
        sample = {"case": label, "seconds": seconds, "status": response.status_code}
        samples.append(sample)
        if seconds > 3 and label not in {"policy_change", "reassignment"}:
            failures.append(sample)
        assert response.is_success, (label, response.status_code, response.text[:300])
        body = response.json()
        if isinstance(body, list):
            items = body
        else:
            sample.update({k: body[k] for k in ("total", "truncated") if k in body})
            items = body.get(
                "items", body.get("records", []) + body.get("aggregations", [])
            )
        if items and isinstance(items[0], dict):
            sample["returned_ids"] = [
                item.get("resource_id", item.get("id")) for item in items
            ]
        return body

    try:
        with (
            psycopg.connect(url, row_factory=dict_row) as c,
            TestClient(app) as reader,
            closing(TestClient(app)) as governor,
        ):
            role = c.execute("SELECT id FROM roles WHERE code='PERF'").fetchone()["id"]
            c.execute(
                "UPDATE roles SET is_information_governance=true WHERE code='DENIED'"
            )
            c.commit()
            for client, name in [(reader, "reader"), (governor, "denied")]:
                response = client.post(
                    "/api/v1/auth/login",
                    json={"email": name + "@performance.invalid", "password": PASSWORD},
                )
                response.raise_for_status()
                client.headers["X-CSRF-Token"] = client.cookies["erms_csrf"]
            owner = c.execute(
                "SELECT id FROM users WHERE email='reader@performance.invalid'"
            ).fetchone()["id"]
            now = datetime.now(timezone.utc)
            hold = governor.post(
                "/api/v1/holds",
                json={
                    "code": "VERIFY-TYPES",
                    "name": "Visibility fixture",
                    "description": "Type access checks",
                    "owner_user_id": owner,
                    "preserve_resource_state": False,
                    "valid_from": (now - timedelta(hours=1)).isoformat(),
                    "valid_to": (now + timedelta(days=1)).isoformat(),
                },
            )
            hold.raise_for_status()
            hold_url = f"/api/v1/holds/{hold.json()['id']}"
            for kind, count in [("record", RECORDS), ("aggregation", AGGREGATIONS)]:
                table = kind + "s"
                data = c.execute(
                    "SELECT id,version FROM resource_types WHERE kind=%s AND name='Restricted'",
                    (kind,),
                ).fetchone()
                catalogue = f"/api/v1/{kind}-types/{data['id']}"
                c.execute(
                    f"""INSERT INTO user_favourite_{table}(user_id,{kind}_id)
                    SELECT u.id,n FROM users u CROSS JOIN generate_series(1,30) n
                    WHERE u.email IN ('reader@performance.invalid','denied@performance.invalid')"""
                )
                if kind == "aggregation":
                    c.execute(
                        """INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id)
                        SELECT a.id,'role',%s,p.id FROM aggregations a CROSS JOIN permissions p
                        WHERE p.code='aggregation.add_record'""",
                        (role,),
                    )
                c.commit()
                leaf = {"field": "id", "operator": "gte", "value": 1}
                # Save a list before taking See away. On subsequent pages every
                # returned hit must still belong to the reader's current scope.
                query = {
                    "where": leaf,
                    "limit": 25,
                    "sort": [{"field": "id", "direction": "asc"}],
                    "tab_id": str(uuid4()),
                }
                path = f"/api/v1/{table}/advanced-search"
                for item in (901, 902):
                    added = governor.post(
                        hold_url + "/held-items",
                        json={"resource_type": kind, "resource_id": item},
                        headers={
                            "X-Change-Reason": "Fixture for visible held-item counts"
                        },
                    )
                    added.raise_for_status()
                cached = measured(
                    kind + "_before_revocation", lambda: reader.post(path, json=query)
                )
                measured(
                    "policy_change",
                    lambda: governor.put(
                        catalogue + "/role-grants",
                        headers={"If-Match": str(data["version"])},
                        json={"see_role_ids": [], "use_role_ids": []},
                    ),
                )
                page = measured(
                    kind + "_after_revocation",
                    lambda: reader.post(
                        path,
                        json={**query, "offset": 25, "search_id": cached["search_id"]},
                    ),
                )
                assert all(row["id"] % 3 != 2 for row in page["items"])
                # Entire population is known from fixture IDs, independently
                # of ACL, type functions, search SQL and query projections.
                for client, identity in [
                    (reader, "restricted"),
                    (governor, "governance"),
                ]:
                    expected = [
                        i
                        for i in range(1, count + 1)
                        if identity == "governance" or i % 3 != 2
                    ]
                    for _ in range(repeats):
                        rows = measured(
                            f"{kind}_{identity}_list",
                            lambda: client.get(f"/api/v1/{table}?limit=25"),
                        )
                        assert [row["id"] for row in rows] == expected[:25]
                        body = measured(
                            f"{kind}_{identity}_search",
                            lambda: client.post(
                                f"/api/v1/{table}/search",
                                json={
                                    "where": leaf,
                                    "limit": 25,
                                    "sort": query["sort"],
                                },
                            ),
                        )
                        assert (
                            body["total"] == len(expected)
                            and [r["id"] for r in body["items"]] == expected[:25]
                        )
                        held = measured(
                            f"{kind}_{identity}_held_items",
                            lambda: client.get(
                                hold_url + "/held-items",
                                params={"resource_type": kind, "sort": "number"},
                            ),
                        )
                        assigned = [901] if identity == "restricted" else [901, 902]
                        assert (
                            held["total"] == len(assigned)
                            and [r["resource_id"] for r in held["items"]] == assigned
                        )
                        selectable = measured(
                            f"{kind}_{identity}_hold_candidates",
                            lambda: client.get(
                                hold_url + "/held-item-candidates",
                                params={"resource_type": kind, "limit": 25},
                            ),
                        )
                        assert selectable["total"] == len(expected) - len(assigned)
                        eligible_hold_ids = sorted(
                            (i for i in expected if i not in assigned),
                            key=lambda i: f"perf-{i}",
                        )
                        assert [
                            row["resource_id"] for row in selectable["items"]
                        ] == eligible_hold_ids[:25]
                        favourites = measured(
                            f"{kind}_{identity}_favourites",
                            lambda: client.get(
                                "/api/v1/favourites", params={"kind": kind, "limit": 50}
                            ),
                        )
                        fav_ids = [i for i in expected if i <= 30]
                        assert favourites["total"] == len(fav_ids)
                        assert sorted(row["id"] for row in favourites[table]) == fav_ids
                        targets = measured(
                            f"{kind}_{identity}_relationship_targets",
                            lambda: client.get(
                                f"/api/v1/relationships/{kind}/1/targets",
                                params={"q": "common", "limit": 25},
                            ),
                        )
                        target_ids = sorted(
                            (i for i in expected if i != 1), key=lambda i: f"PERF-{i}"
                        )[:25]
                        assert [r["id"] for r in targets["items"]] == target_ids
                        if kind == "record":
                            components = measured(
                                f"{identity}_component_search",
                                lambda: client.post(
                                    "/api/v1/digital-components/search",
                                    json={"limit": 25, "sort": query["sort"]},
                                ),
                            )
                            assert components["total"] == len(expected)
                            assert [
                                r["record_id"] for r in components["items"]
                            ] == expected[:25]
                        section = "records" if kind == "record" else "children"
                        children = measured(
                            f"{kind}_{identity}_browse",
                            lambda: client.get(
                                f"/api/v1/browse/aggregations/1/{section}",
                                params={"limit": 25},
                            ),
                        )
                        branch = range(1, 1101) if kind == "record" else range(2, 1102)
                        visible_branch = [
                            i for i in branch if identity == "governance" or i % 3 != 2
                        ]
                        assert children["total"] == len(visible_branch)
                        assert [r["id"] for r in children["items"]] == sorted(
                            visible_branch, key=lambda i: f"PERF-{i}"
                        )[:25]
                        if kind == "aggregation":
                            destinations = measured(
                                f"{identity}_record_destinations",
                                lambda: client.post(
                                    "/api/v1/aggregations/search?record_creation=true",
                                    json={"limit": 25, "sort": query["sort"]},
                                ),
                            )
                            eligible = (
                                expected
                                if identity == "governance"
                                else [i for i in expected if i % 3 == 0]
                            )
                            assert destinations["total"] == len(eligible)
                            assert [r["id"] for r in destinations["items"]] == eligible[
                                :25
                            ]
                        ranked = measured(
                            f"{kind}_{identity}_capped",
                            lambda: client.post(
                                path, json={**query, "tab_id": str(uuid4())}
                            ),
                        )
                        assert ranked["total"] == 1000 and ranked["truncated"]
                        assert [r["id"] for r in ranked["items"]] == expected[:25]
                source = governor.get(f"/api/v1/{table}/3").json()
                assigned = measured(
                    "reassignment",
                    lambda: governor.patch(
                        f"/api/v1/{table}/3",
                        headers={"If-Match": str(source["version"])},
                        json={"type_id": data["id"]},
                    ),
                )
                assert (
                    assigned["type_id"] == data["id"]
                    and reader.get(f"/api/v1/{table}/3").status_code == 404
                )
                version = governor.get(catalogue).json()["version"]
                response = governor.put(
                    catalogue + "/role-grants",
                    headers={"If-Match": str(version)},
                    json={"see_role_ids": [role], "use_role_ids": []},
                )
                response.raise_for_status()
                assert reader.get(f"/api/v1/{table}/3").is_success
            # Recover the actual statements after all response timers. Keep
            # current type access restricted for these independent captures.
            c.execute(
                "DELETE FROM resource_type_role_grants g USING resource_types t WHERE "
                "g.kind=t.kind AND g.type_id=t.id AND t.name='Restricted' AND g.role_id=%s",
                (role,),
            )
            c.commit()
            plans = {}
            probes = {
                "record_search": lambda: reader.post(
                    "/api/v1/records/search", json={"where": leaf, "limit": 25}
                ),
                "record_destinations": lambda: reader.post(
                    "/api/v1/aggregations/search?record_creation=true",
                    json={"limit": 25},
                ),
                "component_search": lambda: reader.post(
                    "/api/v1/digital-components/search", json={"limit": 25}
                ),
                "browse_records": lambda: reader.get(
                    "/api/v1/browse/aggregations/1/records?limit=25"
                ),
                "hold_candidates": lambda: reader.get(
                    hold_url + "/held-item-candidates?resource_type=record&limit=25"
                ),
                "favourites": lambda: reader.get(
                    "/api/v1/favourites?kind=record&limit=25"
                ),
                "relationship_targets": lambda: reader.get(
                    "/api/v1/relationships/record/1/targets?q=common"
                ),
            }
            execute = psycopg.Connection.execute
            for label, probe in probes.items():
                captured = {}

                def capture(conn, statement, params=None, **kwargs):
                    rendered = (
                        statement
                        if isinstance(statement, str)
                        else statement.as_string(conn)
                    )
                    if (
                        "accessible_types AS MATERIALIZED" in rendered
                        and rendered.lstrip().upper().startswith(("SELECT", "WITH"))
                    ):
                        captured.setdefault(rendered, params)
                    return execute(conn, statement, params, **kwargs)

                with patch.object(psycopg.Connection, "execute", capture):
                    response = probe()
                    response.raise_for_status()
                assert captured, label
                c.execute("SELECT set_config('app.user_id',%s,true)", (str(owner),))
                c.execute("SET LOCAL jit=off")
                plans[label] = [
                    {
                        "sql": stmt,
                        "parameters": params,
                        "plan": c.execute(
                            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + stmt,
                            params,
                            prepare=False,
                        ).fetchone()["QUERY PLAN"],
                    }
                    for stmt, params in captured.items()
                ]
                c.commit()
            (output / "type-visibility-plans.json").write_text(
                json.dumps(plans, default=str)
            )
        assert not failures, failures
    finally:
        (output / "type-visibility.json").write_text(
            json.dumps({"samples": samples, "failures": failures}, indent=2)
        )
