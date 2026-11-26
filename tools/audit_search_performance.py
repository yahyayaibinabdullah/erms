"""Audit Trail correctness and page-projection gate on the owned search fixture."""
import json
import time

from psycopg import sql


def _nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from _nodes(child)


def exercise(client, connection, output, repeats, identity):
    from backend.services.api.schemas import SearchRequest
    from backend.services.api.search import search_rows

    samples, plans, failures = [], {}, []
    user_id = connection.execute('SELECT id FROM users WHERE email=%s',
                                 (identity+'@performance.invalid',)).fetchone()['id']
    cases = [
        ('unfiltered', None, '', []),
        ('records', {'field': 'entity_type', 'operator': 'eq', 'value': 'record'},
         ' WHERE entity_type=%s', ['record']),
        ('empty', {'field': 'entity_type', 'operator': 'eq', 'value': 'zzabsent-audit'},
         ' WHERE entity_type=%s', ['zzabsent-audit']),
    ]
    try:
        for label, where, predicate, parameters in cases:
            payload = {'limit': 50, 'sort': [{'field': 'occurred_at', 'direction': 'desc'},
                                            {'field': 'id', 'direction': 'desc'}]}
            if where is not None:
                payload['where'] = where
            # Every event has an envelope in the authorized view. The fixture's
            # raw chronology independently establishes counts and ordered IDs;
            # the canonical projection below checks all protected page fields.
            matching = connection.execute('SELECT count(*) AS n FROM event_history'+predicate,
                                          parameters).fetchone()['n']
            expected = [row['id'] for row in connection.execute(
                'SELECT id FROM event_history'+predicate+' ORDER BY occurred_at DESC,id DESC LIMIT 1000',
                parameters).fetchall()]
            (output/f'{identity}-audit-{label}-expected.json').write_text(json.dumps({
                'request': payload, 'matching_count': matching, 'ordered_ids': expected}, indent=2))
            for repeat in range(repeats):
                for offset in (0, 50, 950) if expected else (0,):
                    request = {**payload, 'offset': offset}
                    started = time.perf_counter()
                    response = client.post('/api/v1/event-history/search', json=request)
                    sample = {'case': label, 'repeat': repeat, 'offset': offset,
                              'seconds': round(time.perf_counter()-started, 6),
                              'status': response.status_code}
                    samples.append(sample)
                    if sample['seconds'] > 3:
                        failures.append({'identity': identity, **sample})
                    assert response.status_code == 200, (sample, response.text)
                    body = response.json()
                    assert body['total'] == len(expected) and body['result_cap'] == 1000
                    assert body['truncated'] == (matching > 1000)
                    page_ids = [row['id'] for row in body['items']]
                    assert page_ids == expected[offset:offset+50], (identity, sample, 'ordered IDs')
                    sample['ids'] = page_ids
                    connection.execute("SELECT set_config('app.user_id',%s,true)", (str(user_id),))
                    projected = connection.execute('SELECT * FROM authorized_event_history WHERE id=ANY(%s) '
                                                   'ORDER BY occurred_at DESC,id DESC', (page_ids,)).fetchall()
                    columns = ('entity_id', 'actor_user_id', 'actor_name', 'actor_email',
                               'before_state', 'after_state', 'changed_fields', 'reason', 'metadata')
                    for actual, reference in zip(body['items'], projected):
                        assert all(actual.get(key) == reference.get(key) for key in columns), (sample, 'redaction')
                    if repeat == 0 and offset == 0:
                        queries = []

                        class Recorder:
                            info = connection.info

                            def execute(self, query, params=None):
                                queries.append((query, params))
                                return connection.execute(query, params)

                        search_rows(Recorder(), 'event_history', SearchRequest.model_validate(request))
                        query, params = next((q, p) for q, p in queries if '_fts_relevance' in str(q))
                        plan = connection.execute(sql.SQL('EXPLAIN (ANALYZE,VERBOSE,BUFFERS,FORMAT JSON) ')
                                                  + query, params).fetchone()['QUERY PLAN']
                        plans[label] = plan
                        projections = [node for node in _nodes(plan[0]['Plan']) if node['Node Type'] == 'Result'
                                       and any(value.startswith('current_user_can_view_event_resource(')
                                               for value in node.get('Output', []))]
                        assert sum(node['Actual Rows']*node['Actual Loops'] for node in projections) == len(page_ids)
                    connection.commit()
        print(json.dumps({'identity': identity, 'case': 'audit_trail', 'responses': len(samples),
                          'maximum_seconds': max(sample['seconds'] for sample in samples)}), flush=True)
    finally:
        (output/f'{identity}-audit-results.json').write_text(json.dumps({
            'page_size': 50, 'result_cap': 1000, 'repeats': repeats,
            'threshold_seconds': 3, 'samples': samples, 'failures': failures}, indent=2))
        (output/f'{identity}-audit-plans.json').write_text(json.dumps(plans, indent=2))
    return failures


def exercise_audit_only(url, output, repeats):
    import psycopg
    from fastapi.testclient import TestClient
    from psycopg.rows import dict_row

    from backend.services.api.main import app
    from tools.check_search_performance import PASSWORD

    failures = []
    with psycopg.connect(url, row_factory=dict_row) as connection, TestClient(app) as client:
        for identity in ('reader', 'denied'):
            client.cookies.clear()
            response = client.post('/api/v1/auth/login', json={
                'email': identity+'@performance.invalid', 'password': PASSWORD})
            assert response.status_code == 200, response.text
            client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']
            failures.extend(exercise(client, connection, output, repeats, identity))
    assert not failures, f'Audit Trail responses exceeded three seconds: {failures}'
