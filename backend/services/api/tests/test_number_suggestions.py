import os
import psycopg
import pytest
from psycopg.rows import dict_row
from backend.services.api.number_suggestions import suggest_number
from backend.services.api.tests.test_phase9_governance_authorization import _login_admin


@pytest.mark.parametrize('resource,column,numbers,entered,expected', [
    ('aggregations','aggregation_number',['3110/2026/1','3110/2026/2','3110/2026/4'],'3110/2026/1','3110/2026/3'),
    ('records','record_number',['3110/2026/1.001','3110/2026/1.002'],'3110/2026/1.001','3110/2026/1.003'),
    ('records','record_number',['ABC'],'ABC',None),
    ('records','record_number',['3110/2026/1'],'3110/2026/1',None),
])
def test_suggestions_find_gap_without_exposing_resources(client,resource,column,numbers,entered,expected):
    _login_admin(client)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("select set_config('app.user_id','1',true)")
        c.execute(f'CREATE TEMP TABLE {resource} ({column} text) ON COMMIT DROP')
        for number in numbers:
            c.execute(f'INSERT INTO {resource} VALUES (%s)',(number,))
        result={'suggested_number':expected}
        if expected is not None:result['generation_intent']={'source':'legacy'}
        assert suggest_number(resource,entered,c)==result


def test_suggestion_route_requires_creation_privilege(client):
    _login_admin(client)
    assert client.get('/api/v1/number-suggestions/records',params={'number':'ABC'}).json()=={'suggested_number':None}
    assert client.get('/api/v1/number-suggestions/users',params={'number':'ABC'}).status_code==404


def test_root_suggestion_increments_middle_serial_and_preserves_year(client):
    _login_admin(client)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("select set_config('app.user_id','1',true)")
        c.execute('CREATE TEMP TABLE aggregations (aggregation_number text) ON COMMIT DROP')
        c.execute("INSERT INTO aggregations VALUES ('3110/1/2026'),('3110/2/2026'),('3110/4/2026'),('3110/3/2025')")
        assert suggest_number('aggregations','3110/1/2026',c,root=True)=={'suggested_number':'3110/3/2026','generation_intent':{'source':'legacy'}}


def test_proactive_root_suggestion_uses_classification_and_current_year(client):
    _login_admin(client)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("select set_config('app.user_id','1',true)")
        c.execute('CREATE TEMP TABLE classifications (id int,code text,is_terminal bool) ON COMMIT DROP')
        c.execute("INSERT INTO classifications VALUES (9,'3110',true)")
        c.execute('CREATE TEMP TABLE aggregations (aggregation_number text) ON COMMIT DROP')
        year=c.execute('SELECT extract(year FROM CURRENT_TIMESTAMP)::int AS year').fetchone()['year']
        c.execute('INSERT INTO aggregations VALUES (%s)',(f'3110/1/{year}',))
        assert suggest_number('aggregations',None,c,classification_id=9)=={'suggested_number':f'3110/2/{year}','generation_intent':{'source':'legacy'}}


def test_proactive_parent_suggestions_use_separators_and_do_not_reserve(client, record):
    _login_admin(client)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("select set_config('app.user_id','1',true)")
        parent=c.execute('SELECT id,aggregation_number FROM aggregations WHERE current_user_can_view_aggregation(id) LIMIT 1').fetchone()
        for resource, separator in [('aggregations','/'),('records','.')]:
            first=suggest_number(resource,None,c,parent_aggregation_id=parent['id'])
            assert first['suggested_number'].startswith(parent['aggregation_number']+separator)
            assert first==suggest_number(resource,None,c,parent_aggregation_id=parent['id'])


def test_batch_numbers_use_gaps_preserve_padding_and_ignore_non_numeric_suffixes(client):
    from backend.services.api.number_suggestions import next_numbers
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute('CREATE TEMP TABLE records(record_number text) ON COMMIT DROP')
        c.execute("INSERT INTO records VALUES ('A.001'),('A.003'),('A.005'),('A.007'),('A.word')")
        assert next_numbers(c,'records','A.000',count=5)==['A.002','A.004','A.006','A.008','A.009']
