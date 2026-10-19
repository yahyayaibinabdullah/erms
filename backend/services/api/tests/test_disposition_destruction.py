"""Phase21 acceptance: every database is created/dropped by the disposable runner."""
from uuid import uuid4
import pytest,psycopg
from backend.services.api.disposition import destruction,documents
from backend.services.api.tests.test_disposition_membership import actor,job_version,db
from backend.services.api.tests.test_disposition_review import task,claim
from backend.services.api.tests.test_disposition_recovery import make_unit

@pytest.fixture(autouse=True)
def guarded_fixture(monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:security=c.execute('SELECT id,prevents_disposition FROM security_levels').fetchall()
    yield
    with db() as c:
        for row in security:c.execute('UPDATE security_levels SET prevents_disposition=%s WHERE id=%s',(row['prevents_disposition'],row['id']))
        for gate in ('digital','physical'):c.execute(f'CREATE OR REPLACE FUNCTION disposition_private.{gate}_execution_released() RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT false $$')


def prepared(c,monkeypatch,before_close=None):
    from backend.services.api.tests import test_disposition_workflow as fixtures
    from backend.services.api.tests.test_disposition_external import prepared,generate,decision
    monkeypatch.setattr(fixtures,'ready',lambda c:make_unit(c,'digital',before_close=before_close))
    job,root,mgr,rid=prepared(c,'simplified');generate(c,job,mgr,rid);decision(c,job);c.commit();actor(c);claim(c,job)
    return job,root,mgr


def request(c,job,mgr,confirmed=True,key=None):
    t=task(c,job['id'])
    return destruction.request(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],confirmed=confirmed,acting_role_id=mgr,command_id=key or uuid4())


def release_fixture(c):
    assert c.info.dbname.startswith('erms_messaging_test_acl_')
    c.execute('CREATE OR REPLACE FUNCTION disposition_private.digital_execution_released() RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT true $$')


def test_request_gate_confirmation_exact_retry_and_single_run(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch)
        with pytest.raises(psycopg.Error,match='digital_release_pending'):request(c,job,mgr)
        release_fixture(c)
        with pytest.raises(psycopg.Error,match='digital_confirmation_required'):request(c,job,mgr,False)
        key=uuid4();result=request(c,job,mgr,key=key);assert request(c,job,mgr,key=key)==result
        with pytest.raises(psycopg.Error,match='digital_already_running'):request(c,job,mgr)
        assert c.execute('SELECT count(*) n FROM disposition_destruction_runs').fetchone()['n']==1
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6


def test_manifest_has_proof_only_and_crashed_claim_requires_explicit_retry(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);result=request(c,job,mgr)
    with db() as c:
        c.execute("SET timezone='Pacific/Auckland'")
        owned=destruction.claim(c);assert owned and owned['root_id']==root;c.commit()
        manifest=c.execute('SELECT to_jsonb(m) data FROM disposition_destruction_manifest_items m').fetchall()
        assert len(manifest)==5 and 'remaining.pdf' not in str(manifest) and 'confidential' not in str(manifest)
        assert any(r['data']['source_component_id'] and r['data']['checksum_value'] for r in manifest)
        # Connection close models death after the durable claim commit.
    with db() as c:
        assert destruction.claim(c) is None
        assert c.execute('SELECT state FROM disposition_destruction_runs').fetchone()['state']=='failed'
        actor(c);again=request(c,job,mgr);assert again['run_id']!=result['run_id']


def test_destruction_tables_reject_ordinary_writes(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        with pytest.raises(psycopg.Error,match='destruction_command_required'),c.transaction():c.execute("UPDATE disposition_destruction_runs SET state='succeeded'")


def erase_fixture(c,run):
    from backend.services.api.disposition.commands import execute_command
    def apply(x):
        x.execute("INSERT INTO disposition_private.destruction_context VALUES(txid_current(),pg_backend_pid(),(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()),%s,%s,%s,'delete')",(run['id'],run['root_id'],run['claim_token']))
        x.execute('SELECT disposition_private.erase_unit_content(%s)',(run['root_id'],))
        destruction._clear(x);return {'erased':True}
    return execute_command(c,command_id=uuid4(),operation='final_complete',payload={'job_id':run['job_id']},acting_role_id=run['acting_role_id'],reason='Isolated storage boundary acceptance',apply=apply)


def copies_and_indexes(c,root,record):
    from backend.services.api.content_storage import PostgreSQLContentStorage
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.tests.test_disposition_artifacts import uploaded
    component=c.execute('SELECT id FROM digital_components WHERE record_id=%s',(record,)).fetchone()['id']
    PostgreSQLContentStorage().store_upload(c,component,uploaded(b'Second confidential version'),settings=load_snapshot(c))
    c.execute("UPDATE records SET title='Confidential title',description='Confidential description' WHERE id=%s",(record,))
    c.execute("INSERT INTO digital_component_search_chunks(digital_component_id,chunk_no,extracted_text,search_vector,text_search_config) VALUES(%s,0,'Confidential OCR',to_tsvector('simple','Confidential OCR'),'simple')",(component,))


def test_real_storage_all_versions_ocr_indexes_and_evidence_isolation(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch,before_close=copies_and_indexes);release_fixture(c);request(c,job,mgr)
        evidence=c.execute('SELECT d.id,b.content FROM digital_components d JOIN records r ON r.id=d.record_id JOIN digital_component_content_sets s ON s.digital_component_id=d.id JOIN digital_component_blobs b ON b.content_set_id=s.id WHERE r.aggregation_id NOT IN (SELECT disposition_private.unit_ids(%s)) ORDER BY d.id,b.id',(root,)).fetchall()
    with db() as c:
        run=destruction.claim(c);c.commit();actor(c);erase_fixture(c,run)
        for table in ('digital_components','content_indexing_jobs','digital_component_search_documents'):
            assert not c.execute(f'SELECT 1 FROM {table} WHERE record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s)))',(root,)).fetchone()
        assert evidence==c.execute('SELECT d.id,b.content FROM digital_components d JOIN records r ON r.id=d.record_id JOIN digital_component_content_sets s ON s.digital_component_id=d.id JOIN digital_component_blobs b ON b.content_set_id=s.id WHERE r.aggregation_id NOT IN (SELECT disposition_private.unit_ids(%s)) ORDER BY d.id,b.id',(root,)).fetchall()
        destruction.release(c,run['id'])


def test_owned_files_cleanup_ack_blocks_erasure_until_real_cleanup(client,monkeypatch,tmp_path):
    from backend.services.processing_workspace import workspace,recover
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch)
        component=c.execute('SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,)).fetchone()['id']
    def register(meta):
        with db() as c:c.execute("SELECT disposition_private.register_processing_copy(%s,%s,1,'rendition')",(meta['token'],component))
    def acknowledge(meta):
        with db() as c:c.execute('DELETE FROM disposition_private.processing_copies WHERE token=%s',(meta['token'],))
    def unavailable(meta):raise OSError('Synthetic ack outage')
    with pytest.raises(OSError),workspace(tmp_path,{},register,unavailable) as directory:
        (directory/'source.bin').write_bytes(b'Confidential temporary working copy')
        with db() as c:actor(c);release_fixture(c);request(c,job,mgr)
        with db() as c:
            run=destruction.claim(c);c.commit();actor(c)
            with pytest.raises(psycopg.Error,match='processing_cleanup_required'):erase_fixture(c,run)
            destruction.release(c,run['id'])
    assert not list(tmp_path.rglob('source.bin'))
    assert recover(tmp_path,acknowledge)==1
    with db() as c:
        actor(c);erase_fixture(c,run)
        assert not c.execute('SELECT 1 FROM digital_components WHERE id=%s',(component,)).fetchone()


def test_complete_unit_real_erasure_minimal_retained_proof_and_pending_job(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch,before_close=copies_and_indexes);release_fixture(c);request(c,job,mgr)
        record=c.execute('SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,)).fetchone()['id']
    assert destruction.process_one(db)
    with db() as c:
        actor(c)
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10
        assert c.execute('SELECT title,description,record_number FROM records WHERE id=%s',(record,)).fetchone()=={'title':None,'description':None,'record_number':None}
        proof=c.execute('SELECT * FROM disposition_retained_records ORDER BY resource_kind,resource_id').fetchall()
        assert len(proof)==4 and all(r['executor_user_id']==1 and r['destruction_number'] for r in proof)
        assert 'Confidential' not in str(proof) and 'remaining.pdf' not in str(proof)
        assert not c.execute("SELECT 1 FROM event_history WHERE before_state::text LIKE '%Confidential%' OR after_state::text LIKE '%Confidential%' OR metadata::text LIKE '%Confidential%'").fetchone()
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['lifecycle_state']=='active'
        assert not c.execute('SELECT 1 FROM authorized_records_for_search WHERE id=%s',(record,)).fetchone()
        assert destruction.progress(c,job['id'])['state']=='succeeded'
    assert client.get(f'/api/v1/records/{record}').status_code==404
    assert client.get(f'/api/v1/aggregations/{root}').status_code==404


def test_worker_failure_rolls_back_storage_and_hides_raw_error_then_retry(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        c.execute("CREATE FUNCTION fail_erasure_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.record_id IN (SELECT id FROM records WHERE title='Remaining material') THEN RAISE EXCEPTION 'secret filesystem path /private/sensitive-content'; END IF; RETURN OLD; END $$")
        c.execute('CREATE TRIGGER fail_erasure_fixture BEFORE DELETE ON digital_components FOR EACH ROW EXECUTE FUNCTION fail_erasure_fixture()')
        before=c.execute('SELECT content FROM digital_component_blobs ORDER BY id').fetchall()
    assert destruction.process_one(db)
    with db() as c:
        actor(c);row=c.execute('SELECT * FROM disposition_destruction_runs').fetchone()
        assert row['state']=='failed' and row['last_error_code']=='disposition_digital_storage_failed' and 'secret' not in str(row)
        assert before==c.execute('SELECT content FROM digital_component_blobs ORDER BY id').fetchall()
        assert not c.execute('SELECT 1 FROM disposition_retained_records').fetchone()
        c.execute('DROP TRIGGER fail_erasure_fixture ON digital_components');c.execute('DROP FUNCTION fail_erasure_fixture()')
        retry=request(c,job,mgr);assert retry['run_id']!=row['id']
    assert destruction.process_one(db)
    with db() as c:assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10


def test_authority_loss_after_queue_preserves_content_and_safe_failure(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
    assert destruction.process_one(db)
    with db() as c:
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6
        assert c.execute('SELECT count(*) n FROM digital_component_blobs').fetchone()['n']>0
        assert c.execute('SELECT state FROM disposition_destruction_runs').fetchone()['state']=='failed'


def test_current_hold_stops_before_irreversible_boundary_and_explicit_retry(client,monkeypatch):
    from backend.services.api.tests.test_disposition_eligibility import make_hold
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr);hold=make_hold(c,'aggregation',root)
    assert destruction.process_one(db)
    with db() as c:
        actor(c);assert c.execute('SELECT last_error_code FROM disposition_destruction_runs').fetchone()['last_error_code']=='disposition_digital_blocked'
        c.execute('UPDATE holds SET valid_to=CURRENT_TIMESTAMP WHERE id=%s',(hold,))
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6
        request(c,job,mgr)
    assert destruction.process_one(db)


def test_partial_job_retry_skips_succeeded_unit_and_retains_same_job_links(client,monkeypatch):
    from backend.services.api.tests.test_disposition_recovery import mixed_done,terminate,resolve
    with db() as c:
        job,a,b,physical,untouched,mgr=mixed_done(c,monkeypatch)
        before_numbers={r['id']:r['aggregation_number'] for r in c.execute('SELECT id,aggregation_number FROM aggregations WHERE id IN (%s,%s)',(a,b))}
        # Real immutable physical confirmation; the default digital release is
        # still closed until this owned test fixture enables it.
        from backend.services.api.tests.test_disposition_review import claim as claim_task
        claim_task(c,job);release_fixture(c);request(c,job,mgr)
        typ=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(a,b,typ))
    assert destruction.process_one(db)
    with db() as c:
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(a,)).fetchone()['disposition_status']==10
        proof=c.execute("SELECT * FROM disposition_retained_records WHERE resource_kind='aggregation' AND resource_id=%s",(a,)).fetchone()
        snapshots=str(c.execute('SELECT membership_snapshot,approval_execution FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchall())
        assert before_numbers[b] in snapshots and before_numbers[a] not in snapshots
        c.execute(f"CREATE FUNCTION fail_second_unit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.record_id IN (SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids({b}))) THEN RAISE EXCEPTION 'storage failure'; END IF; RETURN OLD; END $$")
        c.execute('CREATE TRIGGER fail_second_unit BEFORE DELETE ON digital_components FOR EACH ROW EXECUTE FUNCTION fail_second_unit()')
    assert destruction.process_one(db)
    with db() as c:
        actor(c);c.execute('DROP TRIGGER fail_second_unit ON digital_components');c.execute('DROP FUNCTION fail_second_unit()')
        retry=request(c,job,mgr)
        assert retry['total_units']==3
    while destruction.process_one(db):pass
    with db() as c:
        assert c.execute("SELECT * FROM disposition_retained_records WHERE resource_kind='aggregation' AND resource_id=%s",(a,)).fetchone()==proof
        assert not c.execute('SELECT 1 FROM disposition_destruction_run_units WHERE run_id=%s AND root_id=%s',(retry['run_id'],a)).fetchone()
        assert c.execute('SELECT count(*) n FROM disposition_retained_records').fetchone()['n']==16
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['lifecycle_state']=='active'


def test_terminal_rows_and_events_reject_mutation_outside_erasure(client,monkeypatch):
    with db() as c:job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
    assert destruction.process_one(db)
    with db() as c:
        actor(c)
        for statement in ['UPDATE aggregations SET date_closed=NULL WHERE id=%s','UPDATE aggregations SET title=\'Restored\' WHERE id=%s','DELETE FROM disposition_retained_records WHERE resource_id=%s']:
            with pytest.raises(psycopg.Error),c.transaction():c.execute(statement,(root,))
        with pytest.raises(psycopg.Error,match='event history is immutable'),c.transaction():c.execute("UPDATE event_history SET metadata='{}'")


def test_actual_process_death_before_commit_rolls_back_and_requires_retry(client,monkeypatch):
    import os,subprocess,sys
    from pathlib import Path
    with db() as c:job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
    code='''from backend.services.api.tests.test_disposition_membership import db
from backend.services.api.disposition import destruction
import os
with db() as c:
 u=destruction.claim(c);c.commit()
 destruction.execute_unit(c,u)
 os._exit(17)
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[4],env=os.environ.copy(),capture_output=True)
    assert result.returncode==17,result.stderr.decode()[-1000:]
    with db() as c:
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6
        assert not c.execute('SELECT 1 FROM disposition_retained_records').fetchone()
        assert destruction.claim(c) is None;c.commit();actor(c)
        assert c.execute('SELECT state FROM disposition_destruction_runs').fetchone()['state']=='failed'
        request(c,job,mgr)
    assert destruction.process_one(db)
    assert not destruction.process_one(db)


def test_actual_scratch_owner_death_removes_real_bytes_before_cleanup_ack(client,monkeypatch,tmp_path):
    import os,subprocess,sys,json
    from pathlib import Path
    from backend.services.processing_workspace import recover
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch)
        component=c.execute('SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,)).fetchone()['id']
    code='''from backend.services.processing_workspace import workspace
from backend.services.api.tests.test_disposition_membership import db
import os,sys
def register(m):
 with db() as c:c.execute("SELECT disposition_private.register_processing_copy(%s,%s,1,'rendition')",(m['token'],int(sys.argv[2])))
with workspace(sys.argv[1],{},register,lambda m:None) as directory:
 (directory/'source.bin').write_bytes(b'Actual temporary confidential content')
 os._exit(18)
'''
    process=subprocess.run([sys.executable,'-c',code,str(tmp_path),str(component)],cwd=Path(__file__).parents[4],env=os.environ.copy(),capture_output=True)
    assert process.returncode==18,process.stderr.decode()[-1000:]
    assert list(tmp_path.rglob('source.bin'))
    with db() as c:assert c.execute('SELECT 1 FROM disposition_private.processing_copies').fetchone()
    def ack(m):
        assert not list(tmp_path.rglob('source.bin'))
        with db() as c:c.execute('DELETE FROM disposition_private.processing_copies WHERE token=%s',(m['token'],))
    assert recover(tmp_path,ack)==1 and not list(tmp_path.iterdir())
    with db() as c:assert not c.execute('SELECT 1 FROM disposition_private.processing_copies').fetchone()


def test_retained_routes_require_disposition_or_audit_and_current_resource_access(client,monkeypatch):
    with db() as c:job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
    assert destruction.process_one(db)
    single=client.get(f'/api/v1/disposition/retained/aggregation/{root}')
    assert single.status_code==200,single.text
    assert single.json()['executor_name'] and single.json()['manifest_count']==5
    page=client.get(f"/api/v1/disposition/jobs/{job['id']}/retained-records",params={'limit':1,'offset':0})
    assert page.status_code==200 and page.json()['total']==4 and len(page.json()['items'])==1
    assert client.get(f"/api/v1/disposition/jobs/{job['id']}/retained-records",params={'offset':4}).json()['items']==[]
    manifest=client.get(f"/api/v1/disposition/jobs/{job['id']}/destruction-manifest",params={'root_id':root,'limit':2})
    assert manifest.status_code==200 and manifest.json()['total']==5 and len(manifest.json()['items'])==2
    assert 'remaining.pdf' not in manifest.text and 'storage_key' not in manifest.text
    assert client.get(f'/api/v1/disposition/retained/aggregation/{root}',params={'audit':True}).status_code==200
    events=client.get(f"/api/v1/disposition/jobs/{job['id']}/history",params={'limit':100}).json()['items']
    assert any(e['operation']=='DIGITAL_DESTRUCTION_UNIT_COMPLETED' for e in events)
    with db() as c:
        actor(c);user=c.execute("SELECT id FROM users WHERE id=1").fetchone()['id']
        # A platform administrator does not acquire retained content merely
        # through its admin/global profile; clear both privileged roles and ACLs.
        c.execute('UPDATE roles SET is_information_governance=false WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)')
        c.execute('DELETE FROM aggregation_acl_grants WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,))
        c.execute('DELETE FROM aggregation_child_aggregation_acl_defaults WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,))
    assert client.get(f'/api/v1/disposition/retained/aggregation/{root}').status_code==404


def test_worker_rechecks_new_relationship_after_request(client,monkeypatch):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        other,*_=make_unit(c,'digital')
        typ=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(root,other,typ))
    assert destruction.process_one(db)
    with db() as c:
        assert c.execute('SELECT last_error_code FROM disposition_destruction_runs').fetchone()['last_error_code']=='disposition_digital_blocked'
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6


def test_progress_outcome_notifications_are_attributed_and_not_repeated(client,monkeypatch):
    from pathlib import Path
    from backend.services.api.disposition import notifications
    from backend.services.api.messaging import notification_configuration as config,notification_registry as registry
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c)
        c.execute((Path(__file__).parents[4]/'database/seeds/disposition-notification-producers.sql').read_text());c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
        payload=config.Configuration(expected_version=0,enabled=True,audience_mode='current_eligible_managers',operational_owner='Disposable execution acceptance',templates=[config.Template(language_tag=tag,subject_template=subject,body_template_rich_text=body,review_status='published') for tag,subject,body in [('en','Digital destruction outcome','<p>Digital destruction run {run_id} has an outcome.</p>'),('ar','نتيجة الإتلاف الرقمي','<p>أصبحت نتيجة تنفيذ الإتلاف الرقمي {run_id} متاحة.</p>')]])
        version=config.save(c,1,notifications.DESTRUCTION_OUTCOME,payload,'Configure disposable execution notifications')
        config.activate(c,1,notifications.DESTRUCTION_OUTCOME,version['id'],config.Expected(expected_version=version['version']),'Activate disposable execution notifications')
        request(c,job,mgr)
    assert destruction.process_one(db)
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c);run=c.execute('SELECT id FROM disposition_destruction_runs').fetchone()['id']
        outcome=c.execute('SELECT state,last_error_code FROM disposition_destruction_runs').fetchone();assert outcome['state']=='succeeded',outcome
        count=c.execute('SELECT count(*) n FROM message_envelopes').fetchone()['n'];assert count==1
        notifications.publish_destruction_outcomes(c,run)
        assert c.execute('SELECT count(*) n FROM message_envelopes').fetchone()['n']==count
        assert c.execute("SELECT metadata FROM event_history WHERE operation='DIGITAL_DESTRUCTION_SUCCEEDED'").fetchone()['metadata']['job_completed'] is False


def test_two_live_workers_cannot_claim_same_unit(client,monkeypatch):
    with db() as c:job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
    with db() as first,db() as second:
        unit=destruction.claim(first);first.commit()
        assert destruction.claim(second) is None;second.commit()
        destruction.execute_unit(first,unit);first.commit();destruction.release(first,unit['id']);first.commit()
        assert destruction.claim(second) is None


def test_native_rendition_owns_working_copy_until_response_finishes(client,monkeypatch):
    from backend.services.api import processing_copies
    from backend.services.api.content_storage import PostgreSQLContentStorage
    from tools.preview_disposition import preview_pdf
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.tests.test_disposition_artifacts import uploaded
    def source(c,root,record):
        component=c.execute('SELECT id FROM digital_components WHERE record_id=%s',(record,)).fetchone()['id']
        PostgreSQLContentStorage().store_upload(c,component,uploaded(preview_pdf()),settings=load_snapshot(c))
        c.execute("UPDATE digital_components SET mime_type='application/pdf' WHERE id=%s",(component,))
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch,before_close=source)
        component=c.execute('SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,)).fetchone()['id']
    original=PostgreSQLContentStorage.read;observed=[]
    def observe(storage,c,identity):
        with db() as other:observed.append(other.execute('SELECT 1 FROM disposition_private.processing_copies WHERE component_id=%s',(identity,)).fetchone() is not None)
        return original(storage,c,identity)
    monkeypatch.setattr(PostgreSQLContentStorage,'read',observe)
    response=client.get(f'/api/v1/digital-components/{component}/rendition')
    assert response.status_code==200,response.text
    assert response.content.startswith(b'%PDF-') and response.headers['cache-control']=='private, no-store' and observed==[True]
    with db() as c:assert not c.execute('SELECT 1 FROM disposition_private.processing_copies').fetchone()
    assert not list(processing_copies.root().glob('wathiq-processing-*'))


def test_scratch_recovery_does_not_delete_live_converter_children(tmp_path):
    import subprocess,sys
    from backend.services.processing_workspace import workspace,recover,working_copy_fds
    children=[];acks=[]
    try:
        with workspace(tmp_path,{},lambda m:None,lambda m:acks.append(m)) as directory:
            (directory/'source.bin').write_bytes(b'Owned converter input')
            child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE,pass_fds=working_copy_fds());children.append(child)
        assert not acks and list(tmp_path.rglob('source.bin'))
        assert recover(tmp_path,lambda m:acks.append(m))==0
        child.stdin.close();child.wait(timeout=10)
        assert recover(tmp_path,lambda m:acks.append(m))==1 and len(acks)==1 and not list(tmp_path.iterdir())
    finally:
        for child in children:
            if child.poll() is None:child.kill();child.wait()


@pytest.mark.parametrize('change',['vital','security'])
def test_current_vital_and_clearance_changes_block_execution(client,monkeypatch,change):
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        if change=='vital':
            c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        else:c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM aggregations WHERE id=%s)',(root,))
    assert destruction.process_one(db)
    with db() as c:
        assert c.execute('SELECT state FROM disposition_destruction_runs').fetchone()['state']=='failed'
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6
        assert c.execute('SELECT 1 FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(root,)).fetchone()


@pytest.mark.parametrize('kind',['hold','vital','security','relationship'])
def test_concurrent_hold_committed_while_worker_waits_is_visible(client,monkeypatch,kind):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from backend.services.api.tests.test_disposition_eligibility import make_hold
    with db() as c:job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
    started=threading.Event()
    @contextmanager
    def factory():
        with db() as c:started.set();yield c
    with db() as blocker,ThreadPoolExecutor(max_workers=1) as workers:
        actor(blocker);blocker.execute('SELECT pg_advisory_xact_lock(7357,1)')
        if kind=='hold':make_hold(blocker,'aggregation',root)
        elif kind=='vital':
            blocker.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");blocker.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        elif kind=='security':blocker.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM aggregations WHERE id=%s)',(root,))
        else:
            other,*_=make_unit(blocker,'digital');typ=blocker.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' LIMIT 1").fetchone()['id']
            blocker.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(root,other,typ))
        pending=workers.submit(destruction.process_one,factory);assert started.wait(10)
        blocker.commit();assert pending.result(timeout=20)
    with db() as c:
        assert c.execute('SELECT last_error_code FROM disposition_destruction_runs').fetchone()['last_error_code']=='disposition_digital_blocked'
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6



def test_released_task_after_queue_requires_current_manager_claim(client,monkeypatch):
    from backend.services.api.disposition import workflow
    with db() as c:
        job,root,mgr=prepared(c,monkeypatch);release_fixture(c);request(c,job,mgr)
        current=task(c,job['id'])
        workflow.task_command(c,action='release',task_id=current['id'],expected_version=current['version'],acting_role_id=mgr,command_id=uuid4(),reason='Return synthetic task to its role queue')
    assert destruction.process_one(db)
    with db() as c:
        assert c.execute('SELECT state,last_error_code FROM disposition_destruction_runs').fetchone()==dict(state='failed',last_error_code='disposition_task_claim_required')
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6
