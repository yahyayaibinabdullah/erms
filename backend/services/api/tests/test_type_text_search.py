"""Use the same header-search and advanced-search APIs as the WebUI."""

from uuid import uuid4

from .test_disposition_destruction import guarded_fixture
from .test_type_search import catalogue, corpus, ok


def test_own_metadata_index_and_freshness(client, corpus):
    kind, old, new, fields, _, _, ids = corpus
    resource = f"/api/v1/{kind}s/{ids[0]}"
    field = str(fields["text"])

    def patch(update):
        return ok(
            client.patch(
                resource,
                json=update,
                headers={"If-Match": str(ok(client.get(resource))["version"])},
            )
        )

    def hits(query):
        leaf = {"full_text": {"query": query}}
        response = ok(
            client.post(
                "/api/v1/full-text-search",
                json={
                    "result_types": ["records", "aggregations"],
                    "record_where": leaf,
                    "aggregation_where": leaf,
                    "limit": 25,
                    "tab_id": str(uuid4()),
                },
            )
        )
        return {(hit["type"], hit[hit["type"]]["id"]): hit for hit in response["items"]}

    if kind == "aggregation":
        ok(
            client.post(
                "/api/v1/records",
                json={
                    "aggregation_id": ids[0],
                    "record_number": "P4-CHILD",
                    "title": "Child",
                },
            ),
            201,
        )
    key = kind, ids[0]
    patch({"field_values": {field: "محفوظات phasefour dossier"}})
    result = hits('"phasefour dossier" محفوظات -absent')
    assert set(result) == {key}
    if kind == "aggregation":
        assert "⟦phasefour⟧" in result[key]["snippet"]
    else:
        assert (
            result[key]["matched_record_metadata"]
            and not result[key]["matching_components"]
        )
    advanced = ok(
        client.post(
            f"/api/v1/{kind}s/advanced-search",
            json={
                "where": {"full_text": {"query": "محفوظات", "sources": ["metadata"]}}
            },
        )
    )
    assert [item["id"] for item in advanced["items"]] == [ids[0]]
    # None of these occur in the resource's descriptive text.
    for excluded in ("urgent", "false", "2024-01-02", "1.0000000000000000001"):
        assert key not in hits(excluded)
    assert key not in hits('"dossier phasefour"')
    patch({"title": "Renamed primary"})
    assert set(hits("phasefour")) == {key}
    patch({"field_values": {field: "replacementtoken"}})
    assert not hits("phasefour") and set(hits("replacementtoken")) == {key}
    patch({"field_values": {field: None}})
    assert not hits("replacementtoken")
    patch({"field_values": {field: "removeonreassign"}})
    patch({"type_id": new, "confirm_type_change": True})
    assert not hits("removeonreassign")
    patch(
        {
            "type_id": old,
            "field_values": {field: "removeondetach"},
            "confirm_type_change": True,
        }
    )
    patch({"type_id": None, "confirm_type_change": True})
    assert not hits("removeondetach")


def seed_text(c, kind, rid, *, pre_upgrade=False):
    """Assign a type and save one literal through the partitioned value table."""
    type_id = c.execute(
        "INSERT INTO resource_types(kind,name) VALUES(%s,%s) RETURNING id",
        (kind, "Index proof"),
    ).fetchone()["id"]
    c.execute(
        "INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use) VALUES(%s,%s,1,true)",
        (kind, type_id),
    )
    fid = c.execute(
        """INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
                       VALUES(%s,%s,'Text',1,'text',60) RETURNING id""",
        (kind, type_id),
    ).fetchone()["id"]
    c.execute(f"UPDATE {kind}s SET type_id=%s WHERE id=%s", (type_id, rid))
    c.execute(
        """INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                 VALUES(%s,%s,%s,%s,'text',60,resource_field_decode('text','"uniquetypeproof"'))""",
        (kind, rid, type_id, fid),
    )
    assert indexed(c, kind, rid, "uniquetypeproof") is (not pre_upgrade)
    return fid


def indexed(c, kind, rid, phrase):
    return c.execute(
        f"""SELECT search_vector @@ plainto_tsquery(text_search_config,%s) AS matched
                        FROM {kind}_search_documents WHERE {kind}_id=%s""",
        (phrase, rid),
    ).fetchone()["matched"]


def test_destruction_removes_both_kinds_of_text(client, catalogue, monkeypatch):
    from .test_disposition_destruction import prepared, request
    from .test_disposition_membership import db
    from backend.services.api.disposition import destruction

    owners = {}

    def before_close(c, root, record):
        owners.update(aggregation=root, record=record)
        for kind, rid in owners.items():
            seed_text(c, kind, rid)

    with db() as c:
        job, root, manager = prepared(c, monkeypatch, before_close=before_close)
        request(c, job, manager)
    assert destruction.process_one(db)
    with db() as c:
        for kind, rid in owners.items():
            assert c.execute(
                "SELECT 1 FROM disposition_retained_records WHERE resource_kind=%s AND resource_id=%s",
                (kind, rid),
            ).fetchone()
            assert not indexed(c, kind, rid, "uniquetypeproof")
            assert not c.execute(
                "SELECT 1 FROM resource_type_values WHERE kind=%s AND resource_id=%s",
                (kind, rid),
            ).fetchone()


def test_two_writers_refresh_the_committed_text(client, corpus):
    from .test_disposition_membership import db
    from concurrent.futures import ThreadPoolExecutor
    import time

    kind, owner, _, fields, _, _, ids = corpus
    fid, rid = fields["text"], ids[0]
    with db() as c:
        second = c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,data_type,display_order,max_length)
                              SELECT %s,%s,'Second text','text',coalesce(max(display_order),0)+1,100
                              FROM resource_type_fields WHERE type_id=%s AND kind=%s RETURNING id""",
            (kind, owner, owner, kind),
        ).fetchone()["id"]
    with ThreadPoolExecutor(max_workers=1) as pool, db() as a, db() as b:
        # Different field rows have no row-lock conflict of their own. The owner
        # lock serializes recomputation even when one write targets the partition.
        a.execute(
            """UPDATE resource_type_values SET value=resource_field_decode('text','"firstwriter"')
                     WHERE kind=%s AND resource_id=%s AND field_id=%s""",
            (kind, rid, fid),
        )

        def insert():
            b.execute(
                f"""INSERT INTO {kind}_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                          VALUES(%s,%s,%s,%s,'text',100,resource_field_decode('text','"secondwriter"'))""",
                (kind, rid, owner, second),
            )
            b.commit()

        future = pool.submit(insert)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if a.execute(
                "SELECT %s=ANY(pg_blocking_pids(%s)) AS blocked",
                (a.info.backend_pid, b.info.backend_pid),
            ).fetchone()["blocked"]:
                break
            time.sleep(0.02)
        else:
            a.rollback()
            raise AssertionError("Second writer did not wait for the owner")
        a.commit()
        future.result(timeout=10)
        assert indexed(a, kind, rid, "firstwriter secondwriter")
        a.execute(
            f"DELETE FROM {kind}_type_values WHERE resource_id=%s AND field_id=%s",
            (rid, second),
        )
        assert not indexed(a, kind, rid, "secondwriter")
        a.rollback()
        assert indexed(a, kind, rid, "secondwriter")
