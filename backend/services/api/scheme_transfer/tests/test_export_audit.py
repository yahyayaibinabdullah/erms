"""IE-14 export auditing and authorized actor search acceptance."""
import pytest

from backend.services.api.scheme_transfer.tests.test_transfer import upload
from backend.services.api.scheme_transfer.codec import decode, TransferError


from tools.historical_schema import historical_schema


@pytest.mark.parametrize('format,language', [('json',None),('csv',None),('docx','en'),('docx','ar'),('docx','fr')])
def test_successful_export_history(client, connection, package, format, language):
    sid = upload(client, package).json()['id']
    before = connection.execute('SELECT to_jsonb(s) AS row FROM classification_schemes s WHERE id=%s',(sid,)).fetchone()['row']
    rules = connection.execute('SELECT to_jsonb(r) AS row FROM classification_retention_rules r JOIN classifications c ON c.id=r.classification_id WHERE c.classification_scheme_id=%s ORDER BY r.id',(sid,)).fetchall()
    children = connection.execute('SELECT to_jsonb(c) AS row FROM classifications c WHERE classification_scheme_id=%s ORDER BY id',(sid,)).fetchall()
    response = client.get(f'/api/v1/classification-schemes/{sid}/export', params={'format':format, **({'language':language} if language else {})})
    assert response.status_code == 200, response.text
    events = connection.execute("SELECT * FROM event_history WHERE entity_type='classification_scheme' AND entity_id=%s AND operation='EXPORT'",(sid,)).fetchall()
    assert len(events) == 1
    event = events[0]
    assert event['actor_name'] == 'Transfer Administrator'
    assert event['actor_email'] == 'transfer@test.invalid'
    assert event['actor_user_id'] and event['request_id'] and event['correlation_id']
    assert event['actor_type'] == 'user' and event['source'] == 'api'
    assert event['metadata']['format'] == format
    assert event['metadata']['scheme'] == {'id':sid,'code':before['code'],'title':before['title']}
    assert event['changed_fields'] == [] and event['before_state'] is None and event['after_state'] is None
    if language:
        assert event['metadata']['language'] == language
    else:
        assert 'language' not in event['metadata']
        assert event['metadata']['export_id'] == decode(response.content,format)['manifest']['export_id']
    assert connection.execute('SELECT to_jsonb(s) AS row FROM classification_schemes s WHERE id=%s',(sid,)).fetchone()['row'] == before
    assert connection.execute('SELECT to_jsonb(c) AS row FROM classifications c WHERE classification_scheme_id=%s ORDER BY id',(sid,)).fetchall() == children
    assert connection.execute('SELECT to_jsonb(r) AS row FROM classification_retention_rules r JOIN classifications c ON c.id=r.classification_id WHERE c.classification_scheme_id=%s ORDER BY r.id',(sid,)).fetchall() == rules
    result = client.post('/api/v1/event-history/search',json={'where':{'and':[{'field':'operation','operator':'eq','value':'EXPORT'},{'field':'entity_id','operator':'eq','value':sid}]},'limit':50})
    assert result.status_code == 200 and result.json()['total'] == 1


def test_failed_generation_and_validation_are_not_exports(client, connection, package, monkeypatch):
    from backend.services.api.scheme_transfer import routes
    sid = upload(client,package).json()['id']
    assert client.get(f'/api/v1/classification-schemes/{sid}/export',params={'format':'docx','language':'invalid'}).status_code == 422
    def fail(*args):
        raise TransferError('invalid_package')
    monkeypatch.setattr(routes,'encode',fail)
    assert client.get(f'/api/v1/classification-schemes/{sid}/export',params={'format':'json'}).status_code == 422
    assert connection.execute("SELECT count(*) AS n FROM event_history WHERE entity_id=%s AND operation='EXPORT'",(sid,)).fetchone()['n'] == 0


def test_history_commit_failure_prevents_success(client, connection, package):
    sid = upload(client,package).json()['id']
    connection.execute("""CREATE FUNCTION reject_test_export() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.operation='EXPORT' THEN RAISE EXCEPTION 'Forced export commit failure'; END IF; RETURN NEW; END $$;
    CREATE CONSTRAINT TRIGGER reject_test_export AFTER INSERT ON event_history DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_test_export();""")
    connection.commit()
    try:
        response = client.get(f'/api/v1/classification-schemes/{sid}/export',params={'format':'json'})
        assert response.status_code >= 400, response.text
        assert connection.execute("SELECT count(*) AS n FROM event_history WHERE entity_id=%s AND operation='EXPORT'",(sid,)).fetchone()['n'] == 0
    finally:
        connection.execute('DROP TRIGGER reject_test_export ON event_history; DROP FUNCTION reject_test_export()')
        connection.commit()


def test_actor_search_snapshots_literal_and_authorization(client, connection):
    # Deleted/renamed accounts are represented by immutable snapshots, independent
    # of the current directory. Same names are intentionally not unique.
    actor = connection.execute("INSERT INTO users(name,email) VALUES ('Former Name','old@example.invalid') RETURNING id").fetchone()['id']
    connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id) VALUES ('classification_scheme',987654,'EXPORT',%s)",(actor,))
    connection.execute("UPDATE users SET name='Renamed Actor',email='renamed@example.invalid' WHERE id=%s",(actor,))
    connection.execute('DELETE FROM users WHERE id=%s',(actor,))
    for name,email in [('Former Name','another@example.invalid'),('Percent%_Name','literal@example.invalid'),(None,None)]:
        connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_name,actor_email) VALUES ('classification_scheme',987654,'EXPORT',%s,%s)",(name,email))
    # A historical deleted aggregation with no recoverable clearance is redacted.
    hidden = connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_name,actor_email) VALUES ('aggregation',987654,'EXPORT','Secret Actor','secret@example.invalid') RETURNING id").fetchone()['id']
    connection.commit()
    def search(value, offset=0, limit=50):
        response = client.post('/api/v1/event-history/search',json={'where':{'and':[{'field':'entity_id','operator':'eq','value':987654},{'field':'operation','operator':'eq','value':'EXPORT'},{'or':[{'field':f,'operator':'contains_ci','value':value} for f in ('actor_name','actor_email')]}]},'offset':offset,'limit':limit})
        assert response.status_code == 200, response.text
        return response.json()
    assert search('FORMER')['total'] == 2
    assert search('OLD@EXAMPLE')['total'] == 1
    assert search('Renamed Actor')['total'] == 0
    assert search('renamed@example.invalid')['total'] == 0
    assert search('%_')['total'] == 1
    assert search('FORMER',offset=1,limit=1)['total'] == 2
    assert len(search('FORMER',offset=1,limit=1)['items']) == 1
    assert search('Secret Actor')['total'] == 0
    assert search('secret@example.invalid')['total'] == 0
    redacted = client.post('/api/v1/event-history/search',json={'where':{'field':'id','operator':'eq','value':hidden}}).json()['items'][0]
    assert redacted['metadata']['redacted']
    assert redacted['actor_name'] is None and redacted['actor_email'] is None and redacted['actor_user_id'] is None


def test_actor_redaction_upgrade_matches_canonical(connection):
    from pathlib import Path
    root = Path(__file__).resolve().parents[5]
    canonical = connection.execute("SELECT pg_get_viewdef('authorized_event_history'::regclass) AS definition").fetchone()['definition']
    schema = historical_schema()
    view = schema.split('CREATE VIEW authorized_event_history AS',1)[1].split('CREATE VIEW authorized_aggregations_for_search',1)[0]
    old = view.replace('CASE WHEN visible.allowed THEN event.actor_user_id END AS actor_user_id','event.actor_user_id').replace('CASE WHEN visible.allowed THEN event.actor_name END AS actor_name','event.actor_name').replace('CASE WHEN visible.allowed THEN event.actor_email END AS actor_email','event.actor_email')
    connection.execute('CREATE OR REPLACE VIEW authorized_event_history AS'+old)
    connection.commit()
    try:
        connection.execute((root/'database/migrations/046_audit_actor_redaction.sql').read_text())
        assert connection.execute("SELECT pg_get_viewdef('authorized_event_history'::regclass) AS definition").fetchone()['definition'] == canonical
        assert connection.execute("SELECT count(*) AS n FROM schema_migrations WHERE version='046_audit_actor_redaction'").fetchone()['n'] == 1
    finally:
        connection.rollback()
        connection.execute('CREATE OR REPLACE VIEW authorized_event_history AS '+canonical)
        connection.commit()
