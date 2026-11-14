"""Physical-storage variants for owned disposable search benchmarks only.

EXTERNAL disables TOAST compression without PLAIN's inability to store values
larger than a heap page. It can also change inline/out-of-line placement: report
heap and TOAST sizes rather than describing the experiment as CPU-only tuning.
No application schema, persistent database, text or scoring rule is changed.
"""
import hashlib

from psycopg import sql


VECTOR_TABLES = (
    ('aggregation_search_documents', 'aggregation_id'),
    ('record_search_documents', 'record_id'),
    ('digital_component_search_chunks', 'id'),
)


def configure(connection, mode):
    assert mode in ('current', 'uncompressed')
    database = connection.execute('SELECT current_database() AS name').fetchone()['name']
    assert database.startswith(('erms_large_text_', 'erms_search_perf_')), database
    for table, _ in VECTOR_TABLES:
        # Configure empty canonical tables before seeding. SET STORAGE alone
        # does not decompress existing datums; a populated test would need a
        # physical rewrite with a fresh, logically identical vector instead.
        assert connection.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(
            sql.Identifier(table))).fetchone()['n'] == 0, table
        if mode == 'uncompressed':
            connection.execute(sql.SQL('ALTER TABLE {} ALTER COLUMN search_vector SET STORAGE EXTERNAL').format(
                sql.Identifier(table)))


def inspect(connection, mode):
    """Verify actual compression and hash every binary vector in stable ID order.

    Hashing runs before the documented idle interval in BOTH arms. Exact API
    scores/ranking still have independent SQL-oracle checks. Compression policy
    alone is insufficient evidence: PostgreSQL can retain copied compression.
    """
    tables = {}
    for table, key in VECTOR_TABLES:
        properties = connection.execute('''SELECT a.attstorage,a.attcompression,
            pg_relation_size(c.oid) AS heap_bytes,pg_table_size(c.oid) AS table_bytes,
            pg_indexes_size(c.oid) AS index_bytes,
            pg_total_relation_size(c.reltoastrelid) AS toast_bytes,c.reloptions
            FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid
            WHERE c.oid=%s::regclass AND a.attname='search_vector' ''', (table,)).fetchone()
        compression = connection.execute(sql.SQL('''SELECT pg_column_compression(search_vector) AS compression,
            count(*) AS rows FROM {} GROUP BY 1 ORDER BY 1 NULLS FIRST''').format(sql.Identifier(table))).fetchall()
        if mode == 'uncompressed':
            assert properties['attstorage'] == 'e', (table, properties)
            assert all(row['compression'] is None for row in compression), (table, compression)
        digest = hashlib.sha256()
        count = 0
        with connection.cursor(name='storage_vector_fingerprint') as cursor:
            cursor.execute(sql.SQL('''SELECT {} AS id,text_search_config::text AS config,
                encode(sha256(tsvectorsend(search_vector)),'hex') AS digest
                FROM {} ORDER BY {}''').format(sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)))
            for row in cursor:
                digest.update(f"{row['id']}\t{row['config']}\t{row['digest']}\n".encode())
                count += 1
        tables[table] = {**properties, 'compression_counts': compression,
                         'vector_rows': count, 'logical_vectors_sha256': digest.hexdigest()}
    return {'mode': mode, 'tables': tables}
