"""Index upgrade parity and uncommon configuration matching; disposable runner only."""
import os
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from .test_full_text_search_phase3 import _grant_phase3_privileges, _publish_component, _upload


def test_search_index_upgrade_preserves_data_and_matches_canonical_schema(client, record):
    names = ['digital_components_filename_vector_gin', 'component_search_other_config_idx',
             'record_search_other_config_idx', 'aggregation_search_other_config_idx']
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        before = c.execute('SELECT indexname,indexdef FROM pg_indexes WHERE indexname=ANY(%s) ORDER BY indexname', (names,)).fetchall()
        assert len(before) == len(names)
        document = c.execute('SELECT * FROM record_search_documents WHERE record_id=%s', (record['id'],)).fetchone()
        for name in names:
            c.execute(sql.SQL('DROP INDEX {}').format(sql.Identifier(name)))
        c.execute("DELETE FROM schema_migrations WHERE version='109_search_candidate_indexes'")
        c.commit()
        migration = Path(__file__).resolve().parents[4] / 'database/migrations/109_search_candidate_indexes.sql'
        c.execute(migration.read_text(), prepare=False)
        after = c.execute('SELECT indexname,indexdef FROM pg_indexes WHERE indexname=ANY(%s) ORDER BY indexname', (names,)).fetchall()
        assert before == after
        assert c.execute('SELECT * FROM record_search_documents WHERE record_id=%s', (record['id'],)).fetchone() == document


@pytest.mark.parametrize('configuration,text,query', [
    ('pg_catalog.english', 'approvals', 'approval'),
    ('pg_catalog.arabic', 'وثيقة', 'وثيقة'),
    ('pg_catalog.french', 'archives', 'archives'),
])
def test_metadata_fallback_keeps_each_installed_configuration(client, record, configuration, text, query):
    from .test_application_settings import save
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED': True}).status_code == 200
    _grant_phase3_privileges()
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute('UPDATE record_search_documents SET text_search_config=%s::regconfig,search_vector=to_tsvector(%s::regconfig,%s) WHERE record_id=%s',
                  (configuration, configuration, text, record['id']))
    response = client.post('/api/v1/full-text-search', json={
        'result_types': ['records'], 'record_where': {'full_text': {'query': query, 'sources': ['metadata']}}})
    assert response.status_code == 200, response.text
    assert [item['record']['id'] for item in response.json()['items']] == [record['id']]


def test_metadata_hit_keeps_rank_from_nonmatching_component_chunk(client, record):
    # Cover-density ranking can be positive for a chunk that fails a negated
    # query. Scoring only GIN-matching chunks would silently change the ranking.
    from .test_application_settings import save
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED': True}).status_code == 200
    _grant_phase3_privileges()
    component = _upload(client, record)
    _publish_component(component, 'cat dog', configuration='pg_catalog.simple')
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("UPDATE records SET title='cat' WHERE id=%s", (record['id'],))
        expected, chunk_matches = c.execute("""
            SELECT (ts_rank_cd(metadata.search_vector, q.value) +
                    ts_rank_cd(chunk.search_vector, q.value))::float8,
                   chunk.search_vector @@ q.value
            FROM record_search_documents metadata
            JOIN digital_component_search_chunks chunk ON chunk.digital_component_id=%s
            CROSS JOIN (SELECT websearch_to_tsquery('simple','cat -dog') AS value) q
            WHERE metadata.record_id=%s
        """, (component['id'], record['id'])).fetchone()
        assert not chunk_matches
    response = client.post('/api/v1/full-text-search', json={
        'result_types': ['records'], 'record_where': {'full_text': {'query': 'cat -dog'}}})
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['score'] == expected
