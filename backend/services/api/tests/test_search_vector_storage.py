"""Physical vector rewrites must preserve the existing full-text values exactly."""
import hashlib
import os
from pathlib import Path

import psycopg

from .test_full_text_search_phase3 import _grant_phase3_privileges, _publish_component, _upload


def test_storage_upgrade_rewrites_existing_compression_without_changing_vectors(client, record):
    _grant_phase3_privileges()
    component = _upload(client, record)
    _publish_component(component, 'storageprobe', configuration='pg_catalog.simple')
    # Mostly distinct lexemes give a large value, unlike a long repeated word.
    # The largest case cannot fit a heap page even with LZ4: MAIN must retain
    # PostgreSQL's overflow support, rather than truncate or reject that vector.
    words = ['storageterm' + hashlib.sha256(str(i).encode()).hexdigest()[:20] for i in range(600)]
    text = ' '.join(words)
    query = words[0] + ' OR ' + words[-1]
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        canonical = c.execute("""SELECT attstorage,attcompression FROM pg_attribute
            WHERE attrelid='digital_component_search_chunks'::regclass
            AND attname='search_vector'""").fetchone()
        assert canonical == ('m', 'l')
        c.execute('''ALTER TABLE digital_component_search_chunks
            ALTER COLUMN search_vector SET STORAGE EXTENDED,
            ALTER COLUMN search_vector SET COMPRESSION pglz''')
        c.execute('''UPDATE digital_component_search_chunks
            SET search_vector='alpha:1A,10B omega:16383C stripped'::tsvector
            WHERE digital_component_id=%s''', (component['id'],))
        c.execute('''INSERT INTO digital_component_search_chunks
            (digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
            VALUES (%s,1,%s,setweight(to_tsvector('simple',%s),'A'),'simple')''',
            (component['id'], text, text))
        assert c.execute('''SELECT pg_column_compression(search_vector)
            FROM digital_component_search_chunks WHERE digital_component_id=%s AND chunk_no=1''',
            (component['id'],)).fetchone() == ('pglz',)
        snapshot = '''SELECT id,digital_component_id,chunk_no,page_from,page_to,
            extracted_text,tsvectorsend(search_vector),text_search_config::text,
            search_vector @@ websearch_to_tsquery('simple',%s),
            ts_rank_cd(search_vector,websearch_to_tsquery('simple',%s))
            FROM digital_component_search_chunks ORDER BY id'''
        before = c.execute(snapshot, (query, query)).fetchall()
        indexes = c.execute("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='digital_component_search_chunks' ORDER BY indexname").fetchall()
        old_file = c.execute("SELECT pg_relation_filenode('digital_component_search_chunks')").fetchone()
        c.execute("DELETE FROM schema_migrations WHERE version='112_search_vector_storage'")
        c.commit()
        migration = Path(__file__).resolve().parents[4] / 'database/migrations/112_search_vector_storage.sql'
        c.execute(migration.read_text(), prepare=False)
        assert c.execute(snapshot, (query, query)).fetchall() == before
        assert c.execute("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='digital_component_search_chunks' ORDER BY indexname").fetchall() == indexes
        assert c.execute("SELECT pg_relation_filenode('digital_component_search_chunks')").fetchone() != old_file
        assert c.execute('''SELECT pg_column_compression(search_vector)
            FROM digital_component_search_chunks WHERE digital_component_id=%s AND chunk_no=1''',
            (component['id'],)).fetchone() == ('lz4',)
        assert c.execute('''SELECT pg_column_size(search_vector) > 8192
            FROM digital_component_search_chunks WHERE digital_component_id=%s AND chunk_no=1''',
            (component['id'],)).fetchone() == (True,)
        assert c.execute("""SELECT attstorage,attcompression FROM pg_attribute
            WHERE attrelid='digital_component_search_chunks'::regclass
            AND attname='search_vector'""").fetchone() == canonical
