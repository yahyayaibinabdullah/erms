"""Phase 22 acceptance; the runner creates and always drops the test database."""
from uuid import uuid4
import pytest
from backend.services.api.disposition import completion, destruction, documents
from backend.services.api.disposition.destruction_worker import run_pass
from backend.services.api.tests.test_disposition_destruction import prepared, request, guarded_fixture
from backend.services.api.tests.test_disposition_membership import actor, job_version, db
from backend.services.api.tests.test_disposition_review import task, claim

REAL_RENDER=documents.engine.render


def ready(monkeypatch):
    with db() as c:
        job, root, mgr = prepared(c, monkeypatch)

        request(c, job, mgr)
    return job, root, mgr


def test_automatic_saved_certificate_completes_before_download(client, monkeypatch):
    job, root, mgr = ready(monkeypatch)
    assert run_pass(db, 1) == {'units_processed': 1, 'certificates_processed': 1}
    with db() as c:
        actor(c)
        jobrow=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        work=c.execute('SELECT * FROM disposition_private.completion_work').fetchone()
        assert work['state']=='succeeded', work
        assert jobrow['lifecycle_state']=='completed' and jobrow['completed_by_user_id']==1
        proof=c.execute('SELECT * FROM disposition_retained_records WHERE resource_kind=\'aggregation\' AND resource_id=%s',(root,)).fetchone()
        assert jobrow['completed_at']==proof['destroyed_at']
        certificate=c.execute("SELECT * FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()
        assert certificate and certificate['record_id'] and certificate['digital_component_id']
        fields=certificate['provenance']['snapshot']['fields']
        assert fields['counts.roots']==1 and fields['counts.records']==1 and fields['integrity.value']
        assert task(c,job['id'])['task_type']=='certificate_download'
        assert completion.view(c,jobrow)['completed']
    assert not completion.process_one(db)
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/documents/{certificate['id']}/content")
    assert response.status_code==200,response.text[:300]
    with db() as c:
        assert c.execute("SELECT task_state FROM disposition_tasks WHERE task_type='certificate_download'").fetchone()['task_state']=='completed'
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DIGITAL_CERTIFICATE_DOWNLOADED'").fetchone()['n']==1


def test_certificate_failure_retains_erasure_and_retry_saves_once(client,monkeypatch):
    job,root,mgr=ready(monkeypatch)
    assert destruction.process_one(db)
    original=documents.engine.render
    monkeypatch.setattr(documents.engine,'render',lambda *a:(_ for _ in ()).throw(RuntimeError('secret password /private/path')))
    assert completion.process_one(db)
    with db() as c:
        actor(c)
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10
        work=c.execute('SELECT * FROM disposition_private.completion_work').fetchone()
        assert work['state']=='failed' and 'secret' not in str(work)
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['lifecycle_state']=='active'
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()
        t=task(c,job['id']);key=uuid4()
        kwargs=dict(job_id=job['id'],task_id=t['id'],task_version=t['version'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=key)

        result=completion.retry(c,**kwargs);assert completion.retry(c,**kwargs)==result
    monkeypatch.setattr(documents.engine,'render',original)
    assert completion.process_one(db)
    with db() as c:
        work=c.execute('SELECT * FROM disposition_private.completion_work').fetchone()
        assert work['state']=='succeeded',work
        assert c.execute('SELECT count(*) n FROM disposition_destruction_runs').fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()['n']==1


def test_physical_only_completes_with_original_evidence(client,monkeypatch):
    from backend.services.api.tests import test_disposition_workflow as fixtures
    from backend.services.api.tests.test_disposition_recovery import make_unit
    from backend.services.api.tests.test_disposition_physical import approved,report,confirmation
    monkeypatch.setattr(fixtures,'ready',lambda c:make_unit(c,'physical'))
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        from backend.services.api.disposition import physical,artifacts
        from backend.services.api.application_settings import load_snapshot
        from backend.services.api.content_storage import stage_governed_upload
        from backend.services.api.tests.test_disposition_artifacts import uploaded
        t=task(c,job['id'])
        args=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],successful=True,certificate_reference='PHYS/2026/1',preview=artifacts.destination_token(artifacts.destination(c,job['id'],'physical_destruction_certificate')),acting_role_id=mgr,command_id=uuid4())
        results=[]
        for _ in range(2):
            with stage_governed_upload(uploaded(b'Physical certificate'),load_snapshot(c),connection_factory=db) as staged:results.append(physical.confirm(c,staged=staged,**args))
        assert results[0]==results[1]
        result=results[0]
        with pytest.raises(Exception,match='disposition_command_conflict'),c.transaction():
            with stage_governed_upload(uploaded(b'Physical certificate'),load_snapshot(c),connection_factory=db) as staged:physical.confirm(c,staged=staged,**{**args,'certificate_reference':'DIFFERENT'})
        with pytest.raises(Exception,match='disposition_task_ineligible'),c.transaction():
            with stage_governed_upload(uploaded(b'Physical certificate'),load_snapshot(c),connection_factory=db) as staged:physical.confirm(c,staged=staged,**{**args,'command_id':uuid4()})
        assert result['lifecycle_state']=='completed'
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10
        assert not c.execute('SELECT 1 FROM disposition_destruction_runs').fetchone()
        assert not c.execute("SELECT 1 FROM disposition_tasks WHERE task_type='certificate_download'").fetchone()
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        with pytest.raises(Exception,match='disposition_manager_role_required'),c.transaction():
            with stage_governed_upload(uploaded(b'Physical certificate'),load_snapshot(c),connection_factory=db) as staged:physical.confirm(c,staged=staged,**args)


def test_storage_or_completion_failure_is_atomic_after_erasure(client,monkeypatch):
    job,root,mgr=ready(monkeypatch)
    assert destruction.process_one(db)
    with db() as c:
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        c.execute("CREATE FUNCTION fail_completion_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.lifecycle_state='completed' THEN RAISE EXCEPTION 'private secret path'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_completion_fixture BEFORE UPDATE ON disposition_jobs FOR EACH ROW EXECUTE FUNCTION fail_completion_fixture()')
    assert completion.process_one(db)
    with db() as c:
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10
        assert c.execute('SELECT state FROM disposition_private.completion_work').fetchone()['state']=='failed'
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()
        assert not c.execute("SELECT 1 FROM disposition_tasks WHERE task_type='certificate_download'").fetchone()
        c.execute('DROP TRIGGER fail_completion_fixture ON disposition_jobs');c.execute('DROP FUNCTION fail_completion_fixture()')
        actor(c);t=task(c,job['id'])
        completion.retry(c,job_id=job['id'],task_id=t['id'],task_version=t['version'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4())
    assert completion.process_one(db)
    with db() as c:assert c.execute('SELECT state FROM disposition_private.completion_work').fetchone()['state']=='succeeded'


def test_missing_destination_and_current_authority_rechecked_after_render(client,monkeypatch):
    from backend.services.api.tests.test_disposition_artifacts import configure,root as new_root
    job,root,mgr=ready(monkeypatch)
    assert destruction.process_one(db)
    with db() as c:
        actor(c)
        cl=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'EMPTY-EVIDENCE','Empty evidence',true) RETURNING id").fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(cl,))
        configure(c,evidence=cl)
    assert completion.process_one(db)
    with db() as c:
        actor(c)
        assert c.execute('SELECT last_error_code FROM disposition_private.completion_work').fetchone()['last_error_code']=='disposition_destination_open_root_missing'
        new_root(c,cl);t=task(c,job['id'])
        completion.retry(c,job_id=job['id'],task_id=t['id'],task_version=t['version'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4())
    original=documents.engine.render
    def revoke(*args):
        with db() as c:c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        return original(*args)
    monkeypatch.setattr(documents.engine,'render',revoke)
    assert completion.process_one(db)
    with db() as c:
        assert c.execute('SELECT state FROM disposition_private.completion_work').fetchone()['state']=='failed'
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==10


def test_two_workers_save_once_and_interrupted_claim_requires_retry(client,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    job,root,mgr=ready(monkeypatch);assert destruction.process_one(db)
    with db() as c:c.execute("UPDATE disposition_private.completion_work SET state='running',claim_token=%s",(uuid4(),))
    assert completion.process_one(db)
    assert not completion.process_one(db)
    with db() as c:
        actor(c);t=task(c,job['id'])
        assert c.execute('SELECT last_error_code FROM disposition_private.completion_work').fetchone()['last_error_code']=='disposition_certificate_interrupted'
        completion.retry(c,job_id=job['id'],task_id=t['id'],task_version=t['version'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4())
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:completion.process_one(db),range(2)))
    assert results.count(True)==1
    with db() as c:
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()['n']==1
        assert c.execute('SELECT state FROM disposition_private.completion_work').fetchone()['state']=='succeeded'


def test_mixed_job_completes_all_units_with_one_certificate(client,monkeypatch):
    from backend.services.api.tests.test_disposition_recovery import mixed_done
    with db() as c:
        job,first,second,fully,untouched,mgr=mixed_done(c,monkeypatch)
        claim(c,job);request(c,job,mgr)
    result=run_pass(db,10)
    assert result['units_processed']==4 and result['certificates_processed']==1,result
    with db() as c:
        work=c.execute('SELECT * FROM disposition_private.completion_work').fetchone()
        assert work['state']=='succeeded',work
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state='completed_history'",(job['id'],)).fetchone()['n']==4
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='digital_destruction_certificate'").fetchone()['n']==1


def test_real_certificate_pdf_has_final_facts_and_embedded_changa(client,monkeypatch):
    from pathlib import Path
    from io import BytesIO
    from pypdf import PdfReader
    job,root,mgr=ready(monkeypatch)
    assert destruction.process_one(db)
    monkeypatch.setattr(documents.engine,'render',REAL_RENDER)
    assert completion.process_one(db)
    with db() as c:
        work=c.execute('SELECT * FROM disposition_private.completion_work').fetchone()
        assert work['state']=='succeeded',work
        rows=c.execute("SELECT b.content FROM disposition_job_documents d JOIN digital_components dc ON dc.id=d.digital_component_id JOIN digital_component_blobs b ON b.content_set_id=dc.active_content_set_id WHERE d.document_type='digital_destruction_certificate' ORDER BY b.segment_no").fetchall()
        pdf=b''.join(bytes(r['content']) for r in rows)
        assert documents.engine.verify_pdf(pdf)>=1
        text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        assert str(root) in text and '{{' not in text and 'Digital destruction certificate' in text
        Path('/private/tmp/phase22-real-certificate.pdf').write_bytes(pdf)


def test_completion_notification_is_current_authorized_and_deduplicated(client,monkeypatch):
    from pathlib import Path
    from backend.services.api.disposition import notifications
    from backend.services.api.messaging import notification_configuration as config
    job,root,mgr=ready(monkeypatch)
    with db() as c:
        c.execute((Path(__file__).parents[4]/'database/seeds/disposition-notification-producers.sql').read_text());c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
        payload=config.Configuration(expected_version=0,enabled=True,audience_mode='current_eligible_managers',operational_owner='Disposable completion acceptance',templates=[config.Template(language_tag=tag,subject_template=subject,body_template_rich_text=body,review_status='published') for tag,subject,body in [('en','Destruction job outcome','<p>Destruction job {job_id} has completed or requires certificate recovery.</p>'),('ar','نتيجة عملية الإتلاف','<p>اكتملت عملية الإتلاف {job_id} أو تتطلب استرداد الشهادة.</p>')]])
        version=config.save(c,1,notifications.COMPLETION_OUTCOME,payload,'Configure disposable completion notification')
        config.activate(c,1,notifications.COMPLETION_OUTCOME,version['id'],config.Expected(expected_version=version['version']),'Activate disposable completion notification')
    assert run_pass(db,1)=={'units_processed':1,'certificates_processed':1}
    with db() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');actor(c)
        count=c.execute('SELECT count(*) n FROM message_envelopes').fetchone()['n'];assert count==1
        notifications.publish_completion_outcomes(c,job['id'])
        assert c.execute('SELECT count(*) n FROM message_envelopes').fetchone()['n']==count
        assert c.execute('SELECT state FROM disposition_private.completion_work').fetchone()['state']=='succeeded'
