"""Verify migration 121 on populated Phase 3 data, through the disposable upgrade runner."""

import os
from pathlib import Path

import pytest

from .test_disposition_membership import db
from .test_type_text_search import indexed, seed_text


@pytest.mark.skipif(
    not os.environ.get("ERMS_TEST_DEFERRED_MIGRATIONS"),
    reason="requires populated upgrade runner",
)
def test_populated_type_text_upgrade(client, aggregation, record):
    migration = Path(os.environ["ERMS_TEST_DEFERRED_MIGRATIONS"])
    assert migration.name == "121_type_text_search.sql"
    with db() as c:
        before = {}
        untouched = c.execute(
            """INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,'UNT','Untyped proof')
                                 RETURNING id""",
            (aggregation["id"],),
        ).fetchone()["id"]

        def doc(kind, rid):
            return c.execute(
                f"""SELECT search_vector::text, text_search_config::text,indexed_at,index_config_version,
                       ts_rank_cd(search_vector,plainto_tsquery(text_search_config,'proof')) AS score
                       FROM {kind}_search_documents WHERE {kind}_id=%s""",
                (rid,),
            ).fetchone()

        untyped = doc("record", untouched)
        owners = {"record": record["id"], "aggregation": aggregation["id"]}
        for kind, rid in owners.items():
            c.execute(f"UPDATE {kind}s SET title='Primary proof' WHERE id=%s", (rid,))
            seed_text(c, kind, rid, pre_upgrade=True)
            if kind == "record":
                # A populated installation can carry an alternate per-document
                # configuration. The backfill must preserve its stemming rules.
                c.execute(
                    """UPDATE record_search_documents d SET text_search_config='english',
                              search_vector=setweight(to_tsvector('english',r.record_number),'A') ||
                               setweight(to_tsvector('english',r.title),'A') ||
                               setweight(to_tsvector('english',coalesce(r.description,'')),'B')
                              FROM records r WHERE r.id=d.record_id AND r.id=%s""",
                    (rid,),
                )
            before[kind] = doc(kind, rid)
        c.commit()
        c.execute(migration.read_text(), prepare=False)
        assert doc("record", untouched) == untyped
        for kind, rid in owners.items():
            assert indexed(c, kind, rid, "uniquetypeproof")
            after = doc(kind, rid)
            for key in ("text_search_config", "index_config_version", "score"):
                assert after[key] == before[kind][key]
            c.execute(
                "DELETE FROM resource_type_values WHERE kind=%s AND resource_id=%s",
                (kind, rid),
            )
            assert doc(kind, rid)["search_vector"] == before[kind]["search_vector"]
        assert c.execute(
            "SELECT 1 FROM schema_migrations WHERE version='121_type_text_search'"
        ).fetchone()
