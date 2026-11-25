"""Phase 4 fixture, exact score checks, and current-access paging on both corpora."""

import json
import time
from uuid import uuid4

from psycopg import sql

from tools.check_search_performance import PASSWORD, oracle


def seed_type_text(c, output):
    """Model already populated values, then measure the migration's real refresh."""
    timing = {}
    for kind in ("record", "aggregation"):
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        field = c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,data_type,max_length,display_order)
            SELECT kind,id,'Searchable description','text',12000,1 FROM resource_types
            WHERE kind=%s AND name='General' RETURNING id,type_id""",
            (kind,),
        ).fetchone()
        c.execute("SET LOCAL session_replication_role='replica'")
        rows = c.execute(
            sql.SQL(
                """INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
            SELECT %s,id,type_id,%s,'text',12000,resource_field_decode('text',to_jsonb(
                'typeregister' || CASE WHEN id<=61 THEN ' '||repeat('folio ',1500)||'typetailtoken محفوظات' ELSE '' END))
            FROM {} WHERE type_id=%s AND id<=15001"""
            ).format(sql.Identifier(kind + "s")),
            (kind, field["id"], field["type_id"]),
        ).rowcount
        assert rows == 5001
        c.commit()
        start = time.perf_counter()
        c.execute(
            """SELECT refresh_type_metadata_documents(kind,array_agg(DISTINCT resource_id ORDER BY resource_id))
            FROM resource_type_values WHERE kind=%s AND data_type='text'
            GROUP BY kind,resource_id / 10000 ORDER BY kind,resource_id / 10000""",
            (kind,),
        )
        c.commit()
        timing[kind] = {
            "rows": rows,
            "refresh_and_commit_seconds": time.perf_counter() - start,
        }
    (output / "type-text-backfill.json").write_text(json.dumps(timing))
    c.autocommit = True
    c.execute("VACUUM ANALYZE")
    c.autocommit = False


def exercise(client, c, output, repeats, *, rich_sets=None):
    from backend.services.api import search
    from backend.services.api.schemas import GlobalSearchRequest
    from backend.services.api.search_execution import (
        global_ranking_io,
        search_sql_execution,
    )

    broad = set(range(1, 15002, 3))
    rare = set(range(1, 62, 3))
    body = set(rich_sets["rare"]) if rich_sets else set(range(1, 74))
    body_term = "needleunique" if rich_sets else "contentprobe"
    cases = [
        ("broad_type", "typeregister", "metadata", broad, broad),
        ("primary_and_type", "common typetailtoken", "metadata", rare, rare),
        ("long_literal_phrase", '"typetailtoken محفوظات"', "metadata", rare, rare),
        ("type_or_body", "typetailtoken OR " + body_term, None, rare | body, rare),
    ]
    samples, plans, expected, failures = [], {}, {}, []

    def login(identity):
        client.cookies.clear()
        client.headers.pop("X-CSRF-Token", None)
        client.post(
            "/api/v1/auth/login",
            json={"email": identity + "@performance.invalid", "password": PASSWORD},
        ).raise_for_status()
        client.headers["X-CSRF-Token"] = client.cookies["erms_csrf"]

    def query(label, request, *, endpoint="/api/v1/full-text-search", kind=None):
        start = time.perf_counter()
        response = client.post(endpoint, json=request)
        seconds = time.perf_counter() - start
        row = {"case": label, "seconds": seconds, "status": response.status_code}
        samples.append(row)
        if seconds > 3:
            failures.append(row)
        response.raise_for_status()
        page = response.json()
        row["hits"] = [
            (
                {"id": i["id"], "type": kind, "score": i["_search"]["relevance"]}
                if kind
                else {"id": i[i["type"]]["id"], "type": i["type"], "score": i["score"]}
            )
            for i in page["items"]
        ]
        return page

    try:
        for identity in ("reader", "denied"):
            login(identity)
            for label, phrase, sources, records, aggregations in cases:
                leaf = {"full_text": {"query": phrase}}
                if sources:
                    leaf["full_text"]["sources"] = [sources]
                request = {
                    "result_types": ["records", "aggregations"],
                    "record_where": leaf,
                    "aggregation_where": {
                        "full_text": {"query": phrase, "sources": ["metadata"]}
                    },
                    "include_totals": True,
                    "limit": 100,
                }
                if identity == "reader":
                    ranked = oracle(c, phrase, sources)[:1000]
                    count = len(records) + len(aggregations)
                    assert ranked[0]["total"] == count
                    hits = [{k: r[k] for k in ("id", "score", "type")} for r in ranked]
                    assert all(
                        r["id"] in (records if r["type"] == "record" else aggregations)
                        for r in hits
                    )
                    expected[label] = {
                        "request": request,
                        "uncapped": count,
                        "hits": hits,
                    }
                    parsed = GlobalSearchRequest(**request)
                    for table, where in (
                        ("records", parsed.record_where),
                        ("aggregations", parsed.aggregation_where),
                    ):
                        with c.transaction():
                            c.execute(
                                "SELECT set_config('app.user_id',(SELECT id::text FROM users WHERE email='reader@performance.invalid'),true)"
                            )
                            statement, params = search._global_ranking_statement(
                                c, table, where, 1001
                            )
                            with search_sql_execution(c), global_ranking_io(c):
                                plans[label + "_" + table] = c.execute(
                                    sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ")
                                    + statement,
                                    params,
                                ).fetchone()["QUERY PLAN"]
                else:
                    hits, count = [], 0
                for _ in range(repeats):
                    params = {**request, "tab_id": str(uuid4())}
                    seen = []
                    while True:
                        page = query(identity + "_" + label, params)
                        if not seen:
                            assert sum(page["totals"].values()) == len(hits) and page[
                                "truncated"
                            ] == (count > 1000)
                        seen.extend(samples[-1]["hits"])
                        if not page["next_cursor"]:
                            break
                        params.update(cursor=page["next_cursor"], include_totals=False)
                    assert seen == hits

            for kind in ("record", "aggregation"):
                definition = {
                    "where": {
                        "and": [
                            {"field": "medium", "operator": "eq", "value": "digital"},
                            {
                                "full_text": {
                                    "query": "typeregister",
                                    "sources": ["metadata"],
                                }
                            },
                        ]
                    },
                    "include": ["full_text_matches"],
                    "limit": 100,
                    "sort": [{"field": "id", "direction": "asc"}],
                }
                rows = (
                    oracle(c, "typeregister", "metadata", kind=kind, order_by_id=True)[
                        :1000
                    ]
                    if identity == "reader"
                    else []
                )
                hits = [
                    {"type": kind, "id": r["id"], "score": r["score"]} for r in rows
                ]
                assert [h["id"] for h in hits] == (
                    sorted(broad)[:1000] if identity == "reader" else []
                )
                saved = client.post(
                    "/api/v1/saved-searches",
                    json={
                        "name": f"Type text {kind} {identity}",
                        "definition": {"resource_type": kind, "request": definition},
                    },
                )
                saved.raise_for_status()
                for mode, endpoint, criteria in [
                    ("advanced", f"/api/v1/{kind}s/advanced-search", definition),
                    (
                        "saved",
                        f"/api/v1/saved-searches/{saved.json()['id']}/execute",
                        {"limit": 100},
                    ),
                ]:
                    label = f"{identity}_{kind}_{mode}"
                    expected[label] = {
                        "request": definition,
                        "uncapped": len(broad) if identity == "reader" else 0,
                        "hits": hits,
                    }
                    for _ in range(repeats):
                        params = {**criteria, "tab_id": str(uuid4())}
                        for offset in range(0, max(1, len(hits)), 100):
                            page = query(label, params, endpoint=endpoint, kind=kind)
                            assert (
                                page["total"] == len(hits)
                                and samples[-1]["hits"] == hits[offset : offset + 100]
                            )
                            if offset:
                                assert page["search_id"] == params["search_id"]
                            params.update(
                                search_id=page["search_id"], offset=offset + 100
                            )
        login("reader")
        request = {
            "result_types": ["records"],
            "record_where": {
                "full_text": {"query": "typetailtoken", "sources": ["metadata"]}
            },
            "tab_id": str(uuid4()),
            "limit": 1,
        }
        first = query("before_edit", request)
        assert first["items"][0]["record"]["id"] == 1
        c.commit()
        old_text = c.execute(
            "SELECT (value).text_value FROM record_type_values WHERE resource_id=4 AND data_type='text'"
        ).fetchone()["text_value"]
        start = time.perf_counter()
        c.execute(
            """UPDATE record_type_values SET value=resource_field_decode('text','"revisionmarker"')
                     WHERE resource_id=4 AND data_type='text'"""
        )
        c.commit()
        samples.append(
            {"case": "edit_and_commit", "seconds": time.perf_counter() - start}
        )
        second = query("page_after_edit", {**request, "cursor": first["next_cursor"]})
        assert second["items"][0]["record"]["id"] == 7
        fresh = query(
            "fresh_term",
            {
                **request,
                "tab_id": str(uuid4()),
                "record_where": {"full_text": {"query": "revisionmarker"}},
            },
        )
        assert [i["record"]["id"] for i in fresh["items"]] == [4]
        removed = c.execute(
            """DELETE FROM resource_type_role_grants WHERE kind='record' AND type_id=
                     (SELECT type_id FROM records WHERE id=1) RETURNING kind,type_id,role_id,can_use"""
        ).fetchall()
        c.commit()
        assert not query(
            "page_after_revocation", {**request, "cursor": second["next_cursor"]}
        )["items"]
        assert not query("fresh_after_revocation", {**request, "tab_id": str(uuid4())})[
            "items"
        ]
        # Later diagnostics use the original fixture and authority.
        for grant in removed:
            c.execute(
                """INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use)
                         VALUES(%(kind)s,%(type_id)s,%(role_id)s,%(can_use)s)""",
                grant,
            )
        c.execute(
            """UPDATE record_type_values SET value=resource_field_decode('text',to_jsonb(%s::text))
                     WHERE resource_id=4 AND data_type='text'""",
            (old_text,),
        )
        c.commit()
    finally:
        (output / "type-text.json").write_text(
            json.dumps(
                {
                    "samples": samples,
                    "plans": plans,
                    "expected": expected,
                    "failures": failures,
                },
                default=str,
            )
        )
    assert not failures, f"{len(failures)} type-text responses exceeded 3 s"
