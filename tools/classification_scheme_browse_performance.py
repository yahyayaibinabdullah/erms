"""Measure the localized scheme selector on the disposable search fixture."""
import json
import time
from contextlib import contextmanager

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

SCHEMES = 5003


@contextmanager
def _evidence(output, samples, plans, failures, repeats):
    try:
        yield
    finally:
        (output/'scheme-browse-plans.json').write_text(json.dumps(plans, indent=2))
        (output/'scheme-browse-results.json').write_text(json.dumps({
            'published_fixture_schemes': SCHEMES, 'draft_schemes': 23, 'future_schemes': 17,
            'page_size': 50, 'repeats': repeats, 'threshold_seconds': 3,
            'samples': samples, 'failures': failures}, indent=2))


def seed(connection):
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.execute("SELECT set_config('app.change_reason','Seed disposable scheme selector benchmark',true)")
    connection.execute("""INSERT INTO supported_languages
        (language_tag,english_name,native_name,direction,is_enabled)
        VALUES ('fr','French','Français','ltr',true)""")
    connection.execute("""INSERT INTO classification_schemes(code,title,date_published,translations)
        SELECT 'PERF-SCHEME-'||lpad(n::text,5,'0'),
               'Canonical '||lpad((5044-n)::text,5,'0'),
               CASE WHEN n<=5003 THEN CURRENT_TIMESTAMP
                    WHEN n>5026 THEN CURRENT_TIMESTAMP+interval '1 day' END,
               jsonb_build_object(
                   'en',jsonb_build_object('title','English '||lpad(n::text,5,'0')),
                   'fr',jsonb_build_object('title','disabled-probe '||n),
                   'ar',CASE WHEN n%5=0 THEN jsonb_build_object('description','description-probe')
                        ELSE jsonb_build_object('title',
                            CASE WHEN n<=7 THEN 'الإبرة ' ELSE 'مشترك ' END ||
                            CASE WHEN n>=5001 THEN 'duplicate' ELSE lpad(n::text,5,'0') END) END)
          FROM generate_series(1,5043) n""")
    connection.execute("UPDATE supported_languages SET is_enabled=false WHERE language_tag='fr'")
    connection.commit()
    previous = connection.autocommit
    connection.autocommit = True
    try:
        connection.execute('VACUUM ANALYZE classification_schemes')
    finally:
        connection.autocommit = previous


def exercise(url, output, repeats):
    from backend.services.api.main import app
    from backend.services.api.browse import _scheme_browse_collation, _scheme_browse_query
    from tools.check_search_performance import PASSWORD

    cases = [('unfiltered', '', SCHEMES + 1), ('code', 'PERF-SCHEME', SCHEMES),
             ('canonical', 'Canonical', SCHEMES), ('other_language', 'English ', SCHEMES),
             ('broad_arabic', 'مشترك', 3997), ('selective_arabic', 'الإبرة', 6),
             ('empty', 'zzabsent', 0), ('disabled_language', 'disabled-probe', 0),
             ('description_only', 'description-probe', 0)]
    samples, plans, failures = [], {}, []
    path = '/api/v1/browse/classification-schemes'
    with _evidence(output, samples, plans, failures, repeats), \
            psycopg.connect(url, row_factory=dict_row) as connection, TestClient(app) as client:
        for identity in ('reader', 'denied'):
            client.cookies.clear()
            response = client.post('/api/v1/auth/login',
                                   json={'email': identity+'@performance.invalid', 'password': PASSWORD})
            assert response.status_code == 200, response.text
            user_id = connection.execute('SELECT id FROM users WHERE email=%s',
                                         (identity+'@performance.invalid',)).fetchone()['id']
            for language in ('ar', 'en'):
                connection.execute("""INSERT INTO user_preferences(user_id,language_tag,working_timezone)
                    VALUES (%s,%s,'Asia/Dubai') ON CONFLICT(user_id)
                    DO UPDATE SET language_tag=EXCLUDED.language_tag""", (user_id, language))
                connection.commit()
                collation = _scheme_browse_collation(connection, language)
                for label, query, expected_count in cases:
                    key = identity+'-'+language+'-'+label
                    pattern = '%'+query+'%'
                    # Measure the first page before the oracle/EXPLAIN can warm
                    # this query. Diagnostic writes remain buffered by the runner.
                    started = time.perf_counter()
                    first = client.get(path, params={'q': query, 'limit': 50, 'offset': 0})
                    first_sample = {'case': key, 'repeat': 0, 'offset': 0,
                                    'seconds': time.perf_counter()-started, 'status': first.status_code}
                    samples.append(first_sample)
                    if first_sample['seconds'] > 3:
                        failures.append(first_sample)
                    # Independent oracle: no production query builder or text
                    # prefilter; the fixture has only exact en/ar projections.
                    expected = connection.execute(sql.SQL("""
                        SELECT * FROM (SELECT scheme.id,scheme.code,scheme.title,
                               COALESCE(scheme.translations->%s->>'title',scheme.title) AS display_title
                          FROM classification_schemes scheme
                         WHERE date_published IS NOT NULL AND date_published<=CURRENT_TIMESTAMP
                           AND (%s='' OR code ILIKE %s OR title ILIKE %s OR EXISTS (
                               SELECT 1 FROM jsonb_each(COALESCE(translations,'{{}}'::jsonb)) t
                               JOIN supported_languages l ON l.language_tag=t.key AND l.is_enabled
                               WHERE t.value->>'title' ILIKE %s))) matched
                         ORDER BY display_title COLLATE {collation},code COLLATE "C",id
                    """).format(collation=sql.Identifier('pg_catalog', collation)),
                        (language, query, pattern, pattern, pattern)).fetchall()
                    assert len(expected) == expected_count, (key, len(expected), expected_count)
                    (output/(key+'-expected.json')).write_text(json.dumps({
                        'query': query, 'collation': collation, 'matching_count': expected_count,
                        'ordered_rows': expected}, ensure_ascii=False, indent=2))
                    for repeat in range(repeats):
                        offsets = sorted({0, 1000, max(0, len(expected)-50), len(expected)})
                        if label == 'code' and identity == 'reader' and language == 'ar' and repeat == 0:
                            offsets = list(range(0, len(expected)+50, 50))
                        for offset in offsets:
                            if repeat == 0 and offset == 0:
                                result, sample = first, first_sample
                            else:
                                started = time.perf_counter()
                                result = client.get(path, params={'q': query, 'limit': 50, 'offset': offset})
                                elapsed = time.perf_counter()-started
                                sample = {'case': key, 'repeat': repeat, 'offset': offset,
                                          'seconds': elapsed, 'status': result.status_code}
                                samples.append(sample)
                                if elapsed > 3:
                                    failures.append(sample)
                            assert result.status_code == 200, (key, result.text)
                            observed = [{'id': row['id'], 'code': row['code'], 'title': row['title'],
                                         'display_title': row['localized']['title']} for row in result.json()]
                            assert observed == expected[offset:offset+50], (key, offset)
                            sample['ids'] = [row['id'] for row in observed]
                    if identity == 'reader':
                        statement, parameters = _scheme_browse_query(language, collation, query, 50, 0)
                        plan = connection.execute(sql.SQL('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ')
                                                  + statement, parameters).fetchone()['QUERY PLAN']
                        plans[key] = plan
                    print(json.dumps({'case': key, 'expected_count': expected_count}), flush=True)
        client.cookies.clear()
        started = time.perf_counter()
        response = client.get(path, params={'q': 'مشترك'})
        elapsed = time.perf_counter()-started
        samples.append({'case': 'anonymous', 'seconds': elapsed, 'status': response.status_code})
        assert response.status_code == 401
        if elapsed > 3:
            failures.append(samples[-1])
    assert not failures, f'{len(failures)} scheme browse responses exceeded three seconds'
