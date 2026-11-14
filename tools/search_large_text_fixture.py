"""Deterministic richer-text corpus; current chunk-local matching semantics only.

Keep this distribution and vocabulary stable so optimization runs compare the
same workload. It contains 99% single-chunk files and 10/100-chunk outliers.
Original binary documents are not generated: sizes describe extracted text.
"""
from uuid import uuid4
from tools.check_search_performance import seed, PASSWORD, AGGREGATIONS, RECORDS

CASES = [
    ('broad_combined', 'common OR universal', None),
    ('broad_metadata', 'common', 'metadata'),
    ('broad_word', 'universal', 'components'),
    ('rare_word', 'needleunique', 'components'),
    ('rare_or', 'needleunique OR absentunique', 'components'),
    ('broad_and', 'universal evidence', 'components'),
    ('rare_and', 'needleunique witnessunique', 'components'),
    ('rare_and_combined', 'needleunique witnessunique', None),
    ('broad_not', 'universal -restricted', 'components'),
    ('broad_phrase', '"document evidence"', 'components'),
    ('rare_phrase', '"needleunique witnessunique"', 'components'),
    ('empty_and', 'absentalpha absentbeta', 'components'),
    ('cross_and', 'crossalpha crossbeta', 'components'),
    ('cross_not', 'notalpha -notbeta', 'components'),
    ('boundary_phrase', '"boundaryalpha boundarybeta"', 'components'),
    ('far_phrase', '"crossalpha crossbeta"', 'components'),
    ('negative_phrase', 'universal -"boundaryalpha boundarybeta"', 'components'),
]


def count_chunks(i):return 100 if i%1000==0 else 10 if 1<=i%1000<=9 else 1


def fixture(c):
    """Replace the old two-chunk fixture with realistic bounded text lengths.

    Temporary seeding relations do not change the canonical schema.
    Tokens/probes are deterministic. No full-document vector is used as a phrase
    oracle for large files, since its positions would themselves be clipped.
    """
    seed(c, include_chunks=False)
    singles=[i for i in range(1,RECORDS+1) if count_chunks(i)==1]
    multi=[i for i in range(1,RECORDS+1) if count_chunks(i)>1]
    sets={
        'rare':set(singles[:1200]),'cross_single':set(singles[1200:1400]),
        'not_single':set(singles[1400:2000]),'phrase_single':set(singles[2000:2200]),
        'cross_multi':set(multi[:400]),'phrase_multi':set(multi[400:700]),
        'gap_multi':set(multi[700:900]),
    }
    c.execute("SET LOCAL session_replication_role='replica'")
    c.execute('TRUNCATE digital_component_search_chunks RESTART IDENTITY')
    c.execute('CREATE TEMP TABLE ab_seed_templates(id int PRIMARY KEY,body text,config regconfig,vector tsvector) ON COMMIT DROP')
    c.execute('CREATE TEMP TABLE ab_seed_map(component_id bigint,chunk_no int,template_id int) ON COMMIT DROP')
    vocab=' '.join(f'vocab{i:03}' for i in range(256))
    base='universal document evidence annual review preservation information '+vocab+' '
    small=(base*3)[:4000].rsplit(' ',1)[0]
    large=(base*9)[:16000].rsplit(' ',1)[0]
    templates={};mapping=[]
    for i in range(1,RECORDS+1):
        n=count_chunks(i)
        for j in range(n):
            start=[];end=[]
            if i%2==0:start.append('restricted')
            if i in sets['rare']:start.append('needleunique witnessunique')
            if i in sets['cross_single']:start.append('crossalpha crossbeta')
            if i in sets['not_single']:start.append('notalpha')
            if i in sets['phrase_single']:start.append('boundaryalpha boundarybeta')
            if i in sets['cross_multi']:
                if j==0:start.append('crossalpha notalpha')
                if j==n-1:end.append('crossbeta notbeta')
            if i in sets['phrase_multi'] or i in sets['gap_multi']:
                if j==0:end.append('boundaryalpha')
                if j==1:start.insert(0,'boundarybeta' if i in sets['phrase_multi'] else 'intervening boundarybeta')
            config=('pg_catalog.simple','pg_catalog.english','pg_catalog.arabic')[i%3]
            key=(n==1,tuple(start),tuple(end),config)
            if key not in templates:templates[key]=len(templates)+1
            mapping.append((i,j,templates[key]))
    with c.cursor().copy('COPY ab_seed_templates(id,body,config) FROM STDIN') as cp:
        for (single,start,end,config),identifier in templates.items():
            text=' '.join([*start,small if single else large,*end])
            assert len(text)<=20000
            cp.write_row((identifier,text,config))
    c.execute('UPDATE ab_seed_templates SET vector=to_tsvector(config,body)')
    with c.cursor().copy('COPY ab_seed_map FROM STDIN') as cp:
        for row in mapping:cp.write_row(row)
    c.execute('''INSERT INTO digital_component_search_chunks
        (digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
        -- Produce a fresh, identical vector as the indexer's to_tsvector does.
        -- Copying a compressed template datum preserves ITS compression even
        -- when the target column requests another method. An empty-vector
        -- concatenation preserves all lexemes/weights/positions while allowing
        -- the destination column's storage/compression policy to take effect.
        SELECT m.component_id,m.chunk_no,t.body,t.vector || ''::tsvector,t.config
        FROM ab_seed_map m JOIN ab_seed_templates t ON t.id=m.template_id ORDER BY m.component_id,m.chunk_no''')
    c.execute('''WITH sizes AS (SELECT digital_component_id,sum(octet_length(extracted_text)) bytes
        FROM digital_component_search_chunks GROUP BY digital_component_id)
        UPDATE digital_components c SET size_in_bytes=s.bytes FROM sizes s WHERE s.digital_component_id=c.id''')
    c.execute('UPDATE digital_component_content_sets s SET size_in_bytes=c.size_in_bytes FROM digital_components c WHERE c.active_content_set_id=s.id')
    c.commit();c.autocommit=True;c.execute('VACUUM ANALYZE');c.autocommit=False
    return {k:sorted(v) for k,v in sets.items()}


def distribution(c):
    return c.execute('''WITH files AS (SELECT digital_component_id,count(*) chunks,
        sum(length(extracted_text)) characters,sum(pg_column_size(search_vector)) vector_bytes
        FROM digital_component_search_chunks GROUP BY digital_component_id)
        SELECT chunks,count(*) files,min(characters) min_characters,max(characters) max_characters,
        percentile_cont(.5) WITHIN GROUP(ORDER BY characters) median_characters,
        min(vector_bytes) min_vector_bytes,max(vector_bytes) max_vector_bytes
        FROM files GROUP BY chunks ORDER BY chunks''').fetchall()


def expected_ids(label,sets):
    if label in ('broad_combined','broad_metadata','broad_word','broad_and','broad_phrase'):return None
    if label in ('rare_word','rare_or','rare_and','rare_and_combined','rare_phrase'):return sets['rare']
    if label=='empty_and':return []
    if label=='broad_not':return list(range(1,RECORDS+1,2))
    if label in ('cross_and','far_phrase'):
        return sorted(sets['cross_single'])
    if label=='cross_not':return sorted(sets['not_single']+sets['cross_multi'])
    if label=='boundary_phrase':return sorted(sets['phrase_single'])
    if label=='negative_phrase':
        banned=set(sets['phrase_single'])
        return [i for i in range(1,RECORDS+1) if i not in banned]
    raise AssertionError(label)


def oracle(c,case,sets):
    label,query,sources=case
    ids=expected_ids(label,sets)
    record_count=RECORDS if ids is None else len(ids)
    if sources=='metadata':record_count=RECORDS
    aggregation_count=AGGREGATIONS if label in ('broad_combined','broad_metadata') else 0
    rows=c.execute('''WITH q AS MATERIALIZED (
        SELECT websearch_to_tsquery('simple',%s) s,websearch_to_tsquery('english',%s) e,websearch_to_tsquery('arabic',%s) a
    ), file_scores AS (
        SELECT k.digital_component_id id,max(ts_rank_cd(k.search_vector,
          CASE k.text_search_config WHEN 'simple'::regconfig THEN q.s WHEN 'english'::regconfig THEN q.e ELSE q.a END)) score
        FROM digital_component_search_chunks k CROSS JOIN q
        WHERE %s AND (%s::bigint[] IS NULL OR k.digital_component_id=ANY(%s::bigint[])) GROUP BY k.digital_component_id
    ), hits AS (
        SELECT 'aggregation' type,d.aggregation_id id,ts_rank_cd(d.search_vector,q.s)::float8 score
        FROM aggregation_search_documents d CROSS JOIN q WHERE %s
        UNION ALL SELECT 'record',d.record_id,
            ((CASE WHEN %s THEN ts_rank_cd(d.search_vector,q.s) ELSE 0 END)::real+
             coalesce(f.score,0)::real)::float8 score
        FROM record_search_documents d CROSS JOIN q LEFT JOIN file_scores f ON f.id=d.record_id
        WHERE %s::bigint[] IS NULL OR d.record_id=ANY(%s::bigint[])
    ) SELECT * FROM hits ORDER BY score DESC,type,id LIMIT 1000''',
        (query,query,query,sources!='metadata',ids,ids,bool(aggregation_count),sources!='components',ids,ids)).fetchall()
    return {'count':record_count+aggregation_count,'hits':rows}


def payload(case):
    label,query,sources=case
    leaf={'full_text':{'query':query}}
    if sources:leaf['full_text']['sources']=[sources]
    value={'record_where':leaf,'result_types':['records'],'limit':100,'include_totals':True,'tab_id':str(uuid4())}
    if sources!='components':value.update(aggregation_where={'full_text':{'query':query,'sources':['metadata']}},result_types=['records','aggregations'])
    return value
