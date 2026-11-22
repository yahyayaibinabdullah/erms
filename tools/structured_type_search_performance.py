"""Large-dataset Phase 3 benchmark with independent, deterministic ID and sort oracles."""

import json
import time
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from tools.check_search_performance import AGGREGATIONS, RECORDS, PASSWORD


def seed(c):
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    role = c.execute("SELECT id FROM roles WHERE code='PERF'").fetchone()["id"]
    actor = c.execute(
        "SELECT id FROM users WHERE email='reader@performance.invalid'"
    ).fetchone()["id"]
    for kind in ("record", "aggregation"):
        types = {
            r["name"]: r["id"]
            for r in c.execute(
                "SELECT name,id FROM resource_types WHERE kind=%s", (kind,)
            )
        }
        a, b = types["General"], types["Restricted"]
        c.execute(
            """WITH extra AS (INSERT INTO resource_types(kind,name)
                   SELECT %s,'Catalogue '||lpad(n::text,3,'0') FROM generate_series(1,180) n RETURNING kind,id)
                   INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) SELECT kind,id,%s,false FROM extra""",
            (kind, role),
        )
        table = "records" if kind == "record" else "aggregations"
        # Bulk synthetic setup follows the standard runner. Keep half of the
        # former untyped population untyped; assign the rest across 180 types.
        extra = [
            r["id"]
            for r in c.execute(
                "SELECT id FROM resource_types WHERE kind=%s AND name LIKE 'Catalogue %%' ORDER BY name",
                (kind,),
            )
        ]
        c.execute("SET LOCAL session_replication_role='replica'")
        c.execute(
            f"UPDATE {table} SET type_id=(%s::bigint[])[(((id/6-1) %% 180)+1)::int] WHERE id %% 6=0",
            (extra,),
        )
        c.execute("SET LOCAL session_replication_role='origin'")
        assert (
            c.execute(f"SELECT count(DISTINCT type_id) AS n FROM {table}").fetchone()[
                "n"
            ]
            == 182
        )
        f = c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,data_type,display_order) VALUES
                   (%s,%s,'Reference','integer',0) RETURNING id""",
            (kind, a),
        ).fetchone()["id"]
        choice = c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,data_type,display_order) VALUES
                   (%s,%s,'Priority','single_choice',1) RETURNING id""",
            (kind, b),
        ).fetchone()["id"]
        c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,data_type,display_order)
                   SELECT %s,%s,'Detail '||n,'integer',n FROM generate_series(2,145) n""",
            (kind, a),
        )
        options = c.execute(
            """INSERT INTO resource_field_choices(field_id,name,display_order)
                   SELECT %s,'Choice '||n,151-n FROM generate_series(1,150) n RETURNING id,display_order""",
            (choice,),
        ).fetchall()
        ordered = [r["id"] for r in sorted(options, key=lambda r: r["display_order"])]
        table = "records" if kind == "record" else "aggregations"
        c.execute(
            f"""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                   SELECT %s,id,type_id,%s,'integer',0,ROW(NULL,id %% 101,NULL,NULL,NULL,NULL,NULL)::resource_field_literal
                   FROM {table} WHERE type_id=%s AND id %% 11=0""",
            (kind, f, a),
        )
        c.execute(
            f"""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                   SELECT %s,id,type_id,%s,'single_choice',0,ROW(NULL,NULL,NULL,NULL,NULL,NULL,(%s::bigint[])[(id %% 7)::int+1])::resource_field_literal
                   FROM {table} WHERE type_id=%s""",
            (kind, choice, ordered[:7], b),
        )
        definition = {
            "schema_version": 1,
            "resource_type": kind,
            "request": {
                "where": {"field": f"type.{a}.field.{f}", "operator": "is_null"},
                "sort": [{"field": "id", "direction": "asc"}],
                "limit": 25,
            },
        }
        c.execute(
            """INSERT INTO saved_searches(owner_user_id,name,resource_type,definition,audience_mode)
                  SELECT %s,'P3 '||%s::text||' '||lpad(n::text,3,'0'),%s,%s,'private'
                  FROM generate_series(1,160) n""",
            (actor, kind, kind, Jsonb(definition)),
        )
    c.commit()


def exercise(url, output, repeats, *, type_ui=False):
    from backend.services.api.main import app

    samples, plans, failures = [], {}, []

    def measured(label, call, status=200):
        start = time.perf_counter()
        response = call()
        elapsed = time.perf_counter() - start
        samples.append(
            {"case": label, "seconds": elapsed, "status": response.status_code}
        )
        if elapsed > 3:
            failures.append([label, elapsed])
        assert response.status_code == status, (
            label,
            response.status_code,
            response.text[:400],
        )
        return response.json()

    def check(page, expected, offset=0):
        ids = [r["id"] for r in page["items"]]
        assert ids == expected[offset : offset + 25], (
            samples[-1]["case"],
            ids,
            expected[offset : offset + 25],
        )
        assert page["total"] == min(1000, len(expected))
        assert page["truncated"] == (len(expected) > 1000)
        samples[-1].update(
            expected_uncapped=len(expected), total=page["total"], ids=ids
        )

    try:
        with psycopg.connect(url, row_factory=dict_row) as c, TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"email": "reader@performance.invalid", "password": PASSWORD},
            )
            login.raise_for_status()
            client.headers["X-CSRF-Token"] = client.cookies["erms_csrf"]
            owner = c.execute(
                "SELECT id FROM users WHERE email='reader@performance.invalid'"
            ).fetchone()["id"]
            plan_requests = []
            for kind, n in [("record", RECORDS), ("aggregation", AGGREGATIONS)]:
                path = f"/api/v1/{kind}s/advanced-search"
                catalogue = f"/api/v1/{kind}-types/options"
                fields = {
                    r["name"]: r
                    for r in c.execute(
                        """SELECT f.name,f.id,f.type_id FROM resource_type_fields f
                       WHERE kind=%s AND name IN ('Reference','Priority')""",
                        (kind,),
                    )
                }
                a, f = fields["Reference"]["type_id"], fields["Reference"]["id"]
                b, g = fields["Priority"]["type_id"], fields["Priority"]["id"]
                rank = f"type.{a}.field.{f}"
                priority = f"type.{b}.field.{g}"
                all_ids = list(range(1, n + 1))
                subset = [i for i in all_ids if i % 3 == 1 and i % 11 == 0]
                populated = set(subset)

                def leaf(key, op, value=None):
                    return dict(
                        field=key,
                        operator=op,
                        **({} if value is None else {"value": value}),
                    )

                extra = [
                    r["id"]
                    for r in c.execute(
                        "SELECT id FROM resource_types WHERE kind=%s AND name LIKE 'Catalogue %%' ORDER BY name",
                        (kind,),
                    )
                ]
                cases = [
                    (
                        "eighty_types",
                        leaf("type_id", "in", extra[:80]),
                        None,
                        [i for i in all_ids if i % 6 == 0 and (i // 6 - 1) % 180 < 80],
                    ),
                    (
                        "selective",
                        leaf(rank, "eq", 7),
                        None,
                        [i for i in subset if i % 101 == 7],
                    ),
                    (
                        "unset",
                        leaf(rank, "is_null"),
                        None,
                        [i for i in all_ids if i % 3 == 1 and i not in populated],
                    ),
                    (
                        "untyped",
                        leaf("type_id", "is_null"),
                        None,
                        [i for i in all_ids if i % 6 == 3],
                    ),
                    (
                        "mixed",
                        {
                            "or": [
                                leaf(rank, "gte", 90),
                                {
                                    "and": [
                                        {"not": leaf("type_id", "eq", a)},
                                        leaf("id", "lte", 2000),
                                    ]
                                },
                            ]
                        },
                        None,
                        [
                            i
                            for i in all_ids
                            if (i in populated and i % 101 >= 90)
                            or (i % 3 != 1 and i <= 2000)
                        ],
                    ),
                    (
                        "mostly_unset_sort",
                        None,
                        rank,
                        sorted(
                            all_ids,
                            key=lambda i: (
                                i not in populated,
                                -(i % 101) if i in populated else 0,
                                i,
                            ),
                        ),
                    ),
                    (
                        "choice_sort",
                        None,
                        priority,
                        sorted(
                            all_ids,
                            key=lambda i: (
                                i % 3 != 2,
                                -(i % 7) if i % 3 == 2 else 0,
                                i,
                            ),
                        ),
                    ),
                ]
                for label, where, sort, expected in cases:
                    body = {"limit": 25}
                    if where:
                        body["where"] = where
                    if sort:
                        body["sort"] = [{"field": sort, "direction": "desc"}]
                    for _ in range(repeats):
                        first = measured(
                            kind + "_" + label + "_without_tab",
                            lambda: client.post(path, json=body),
                        )
                        check(first, expected)
                        uncapped = measured(
                            kind + "_" + label + "_uncapped",
                            lambda: client.post(f"/api/v1/{kind}s/search", json=body),
                        )
                        actual = [r["id"] for r in uncapped["items"]]
                        assert (
                            uncapped["total"] == len(expected)
                            and actual == expected[:25]
                        )
                        samples[-1].update(
                            expected_uncapped=len(expected),
                            total=uncapped["total"],
                            ids=actual,
                        )
                        query = {**body, "tab_id": str(uuid4())}
                        page = measured(
                            kind + "_" + label, lambda: client.post(path, json=query)
                        )
                        check(page, expected)
                        if len(expected) > 25:
                            check(
                                measured(
                                    kind + "_" + label + "_page",
                                    lambda: client.post(
                                        path,
                                        json={
                                            **query,
                                            "offset": 25,
                                            "search_id": page["search_id"],
                                        },
                                    ),
                                ),
                                expected,
                                25,
                            )
                    if label in (
                        "selective",
                        "mixed",
                        "mostly_unset_sort",
                        "choice_sort",
                    ):
                        plan_requests.append(
                            (kind + "_" + label, path, {**body, "tab_id": str(uuid4())})
                        )
                    if label in ("selective", "choice_sort"):
                        plan_requests.append(
                            (kind + "_" + label + "_no_tab", path, body)
                        )
                saved_expected = next(
                    expected for label, _, _, expected in cases if label == "unset"
                )
                expected_saved = [
                    r["id"]
                    for r in c.execute(
                        "SELECT id FROM saved_searches WHERE resource_type=%s AND name LIKE 'P3 %%' ORDER BY date_updated DESC,id DESC",
                        (kind,),
                    )
                ]
                selector_pages = [
                    (
                        f"/{a}/fields",
                        [
                            r["id"]
                            for r in c.execute(
                                "SELECT id FROM resource_type_fields WHERE type_id=%s ORDER BY display_order,id",
                                (a,),
                            )
                        ],
                    ),
                    (
                        f"/{b}/fields/{g}/choices",
                        [
                            r["id"]
                            for r in c.execute(
                                "SELECT id FROM resource_field_choices WHERE field_id=%s ORDER BY display_order,id",
                                (g,),
                            )
                        ],
                    ),
                ]
                expected_options = [
                    r["id"]
                    for r in c.execute(
                        "SELECT id FROM resource_types WHERE kind=%s AND name LIKE 'Catalogue %%' ORDER BY name,id",
                        (kind,),
                    )
                ]
                for _ in range(repeats):
                    for offset in (0, 100):
                        listed = measured(
                            kind + "_saved_list",
                            lambda: client.get(
                                "/api/v1/saved-searches",
                                params={
                                    "resource_type": kind,
                                    "q": "P3",
                                    "limit": 100,
                                    "offset": offset,
                                },
                            ),
                        )
                        assert (
                            listed["total"] == 160
                            and [r["id"] for r in listed["items"]]
                            == expected_saved[offset : offset + 100]
                        )
                        assert all(r["capabilities"]["open"] for r in listed["items"])
                        options = measured(
                            kind + "_type_selector",
                            lambda: client.get(
                                catalogue,
                                params={
                                    "q": "Catalogue",
                                    "access": "see",
                                    "limit": 100,
                                    "offset": offset,
                                },
                            ),
                        )
                        assert [r["id"] for r in options] == expected_options[
                            offset : offset + 100
                        ]
                        for suffix, expected_ids in selector_pages:
                            values = measured(
                                kind + "_field_or_choice_selector",
                                lambda: client.get(
                                    catalogue + suffix,
                                    params={"limit": 100, "offset": offset},
                                ),
                            )
                            assert [r["id"] for r in values] == expected_ids[
                                offset : offset + 100
                            ]
                    saved_path = f"/api/v1/saved-searches/{expected_saved[0]}/execute"
                    tab = str(uuid4())
                    page = measured(
                        kind + "_saved",
                        lambda: client.post(saved_path, json={"tab_id": tab}),
                    )
                    check(page, saved_expected)
                    check(
                        measured(
                            kind + "_saved_page",
                            lambda: client.post(
                                saved_path,
                                json={
                                    "tab_id": tab,
                                    "search_id": page["search_id"],
                                    "offset": 25,
                                },
                            ),
                        ),
                        saved_expected,
                        25,
                    )
                # Restrict exactly one catalogue type. Test the general universe and explicit denial.
                c.execute(
                    "DELETE FROM resource_type_role_grants WHERE kind=%s AND type_id=%s",
                    (kind, b),
                )
                c.commit()
                expected = [i for i in all_ids if i % 3 != 2]
                for _ in range(repeats):
                    check(
                        measured(
                            kind + "_generic_restricted",
                            lambda: client.post(
                                path, json={"limit": 25, "tab_id": str(uuid4())}
                            ),
                        ),
                        expected,
                    )
                    measured(
                        kind + "_forbidden_sort",
                        lambda: client.post(path, json={"sort": [{"field": priority}]}),
                        403,
                    )
                c.execute(
                    """INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use)
                           SELECT %s,%s,id,false FROM roles WHERE code='PERF'""",
                    (kind, b),
                )
                c.commit()
            for label, path, query in plan_requests:
                captured = []
                original = psycopg.Connection.execute

                def capture(conn, statement, params=None, **kwargs):
                    rendered = (
                        statement.as_string(conn)
                        if hasattr(statement, "as_string")
                        else str(statement)
                    )
                    if "ranked AS MATERIALIZED" in rendered or (
                        label.endswith("_no_tab")
                        and "AS _fts_relevance FROM" in rendered
                    ):
                        captured.append((rendered, params))
                    return original(conn, statement, params, **kwargs)

                with patch.object(psycopg.Connection, "execute", capture):
                    client.post(path, json=query).raise_for_status()
                assert len(captured) == 1
                statement, params = captured[0]
                c.execute("SELECT set_config('app.user_id',%s,true)", (str(owner),))
                c.execute("SET LOCAL jit=off")
                plans[label] = {
                    "query": query,
                    "sql": statement,
                    "parameters": params,
                    "plan": c.execute(
                        "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement,
                        params,
                        prepare=False,
                    ).fetchone()["QUERY PLAN"],
                }
                c.commit()
            if type_ui:
                from tools.type_ui_performance import exercise as measure_ui_pages

                measure_ui_pages(c, client, output, repeats)
        assert not failures, failures
    finally:
        (output / "typed-search.json").write_text(
            json.dumps(
                {"samples": samples, "failures": failures, "plans": plans}, default=str
            )
        )
