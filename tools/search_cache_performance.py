"""Additional large-fixture gates for the shared tab cache's actual endpoints."""
import json
import time
from uuid import uuid4

from psycopg import sql


def exercise(client, connection, output, repeats, identity, oracle):
    from backend.services.api.search_cache import _statement
    from backend.services.api.search import canonicalize_search_request
    from backend.services.api.schemas import SearchRequest
    results, failures = [], []
    # Each case has an independent SQL oracle; the fixture contains one permitted
    # active file per record, so the legacy Advanced and Global score formulas agree.
    cases = [
        ('broad_combined', 'common OR universal', None),
        ('saved_broad_combined', 'common OR universal', None),
        ('broad_grouped', 'common OR universal', None),
        ('broad_field_sort', 'common OR universal', None),
        ('broad_content', 'universal', 'components'),
        ('broad_metadata', 'common', 'metadata'),
        ('rare', 'needle', 'metadata'),
        ('empty', 'zzabsent', 'metadata'),
        ('structured', None, None),
        ('not_held', None, None),
        ('location_null', None, None),
        ('inherited_retention', None, None),
        ('filtered_descending', None, None),
    ]
    for resource, count in [('records', 153009), ('aggregations', 51003)]:
        for label, phrase, sources in cases:
            if (resource == 'aggregations' and sources == 'components') or (resource == 'records' and label == 'inherited_retention'):
                continue
            endpoint = f'/api/v1/{resource}/' + ('search' if label == 'filtered_descending' else 'advanced-search')
            where = {'field': 'id', 'operator': 'gt', 'value': 0}
            payload = {'where': where, 'limit': 100, 'tab_id': str(uuid4())}
            params = {}
            if phrase:
                where = {'full_text': {'query': phrase, 'sources': [sources] if sources else
                                      ['metadata', 'components'] if resource == 'records' else ['metadata']}}
                payload.update(where=where, include=['full_text_matches'])
                if label == 'broad_grouped':
                    payload['where'] = {'and': [where]}
                elif label == 'broad_field_sort':
                    payload.update(where={'and': [where, {'field': 'id', 'operator': 'gt', 'value': 0}]},
                                   sort=[{'field': 'id', 'direction': 'asc'}])
            elif label == 'inherited_retention':
                payload['where'] = {'field': 'effective_retention.current_period_years', 'operator': 'eq', 'value': 5}
            elif label == 'not_held':
                payload['where'] = {'field': 'on_effective_hold', 'operator': 'eq', 'value': False}
            elif label == 'location_null':
                payload['where'] = {'field': 'effective_current_location', 'operator': 'is_null'}
            elif label == 'filtered_descending':
                payload['sort'] = [{'field': 'id', 'direction': 'desc'}]
                params['display_filter'] = 'common'
            if label.startswith('saved_'):
                created = client.post('/api/v1/saved-searches', json={
                    'name': f'Performance {identity} {resource}',
                    'definition': {'resource_type': resource[:-1], 'request': {
                        key: value for key, value in payload.items() if key != 'tab_id'}},
                })
                assert created.status_code == 201, created.text
                endpoint = f"/api/v1/saved-searches/{created.json()['id']}/execute"
            expected = None
            samples = []
            for repeat in range(repeats):
                request = ({'tab_id': payload['tab_id'], 'limit': 100}
                           if label.startswith('saved_') else dict(payload))
                received = []
                while True:
                    started = time.perf_counter()
                    response = client.post(endpoint, json=request, params=params)
                    elapsed = time.perf_counter() - started
                    assert response.status_code == 200, (identity, resource, label, response.text)
                    body = response.json()
                    if request.get('search_id'):
                        assert body['search_id'] == request['search_id'], (resource, label, 'Next unexpectedly rebuilt a valid list')
                    if expected is None:
                        if identity == 'denied':
                            expected = []
                        elif phrase:
                            expected = oracle(connection, phrase, sources, kind=resource[:-1],
                                              order_by_id=label == 'broad_field_sort')[:1000]
                        else:
                            ids = range(count, count-1000, -1) if label == 'filtered_descending' else range(1, 1001)
                            expected = [{'id': i, 'score': 0.0} for i in ids]
                        (output / f'{identity}-{resource}-{label}-expected.json').write_text(json.dumps(expected, indent=2))
                    sample = {'repeat': repeat, 'offset': request.get('offset', 0), 'seconds': round(elapsed, 4)}
                    samples.append(sample)
                    if elapsed > 3:
                        failures.append({'identity': identity, 'resource': resource, 'case': label, **sample})
                    assert body['total'] == len(expected), (resource, label, body['total'], len(expected))
                    received.extend({'id': item['id'], 'score': item.get('_search', {}).get('relevance', 0.0)} for item in body['items'])
                    if not request.get('offset'):
                        cached = connection.execute('SELECT hits FROM search_results_cache WHERE search_id=%s', (body['search_id'],)).fetchone()['hits']
                        assert cached == [{'id': row['id'], 'score': row['score']} for row in expected], (resource, label, 'cache ranking')
                    if len(received) >= len(expected):
                        break
                    request.update(search_id=body['search_id'], offset=len(received))
                assert received == [{'id': row['id'], 'score': row['score']} for row in expected], (resource, label, 'page order/scores')
                (output / f'{identity}-{resource}-{label}-{repeat}-received.json').write_text(json.dumps(received, indent=2))
            result = {'identity': identity, 'resource': resource, 'case': label, 'returned': len(expected),
                      'samples': samples, 'maximum_seconds': max(s['seconds'] for s in samples)}
            results.append(result)
            print(json.dumps({k: v for k, v in result.items() if k != 'samples'}), flush=True)
            (output / f'{identity}-tab-cache-results.json').write_text(json.dumps({'results': results, 'failures': failures}, indent=2))
            if identity == 'reader':
                uid = connection.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
                connection.execute("SELECT set_config('app.user_id',%s,true)", (str(uid),))
                request = SearchRequest(**payload)
                canonical = canonicalize_search_request(connection, resource, request)
                statement, values = _statement(resource, request, canonical, params.get('display_filter'), None, 1000)
                from backend.services.api.search_execution import search_sql_execution
                with search_sql_execution(connection):
                    plan = connection.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ') + statement, values).fetchone()['QUERY PLAN']
                (output / f'tab-cache-{resource}-{label}-plan.json').write_text(json.dumps(plan, indent=2))
                if label == 'rare':
                    def indexes(node):
                        found = {node['Index Name']} if 'Index Name' in node else set()
                        return found.union(*(indexes(child) for child in node.get('Plans', [])))
                    assert f'{resource[:-1]}_search_documents_vector_gin' in indexes(plan[0]['Plan'])
                connection.commit()
    return failures
