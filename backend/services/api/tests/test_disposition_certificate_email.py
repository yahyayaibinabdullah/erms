"""Current certificate task email summary, using only a disposable database."""
from uuid import uuid4

from backend.services.api.disposition import email,completion,documents
from backend.services.api.disposition.destruction_worker import run_pass
from backend.services.api.tests.test_disposition_completion import ready
from backend.services.api.tests.test_disposition_destruction import guarded_fixture
from backend.services.api.tests.test_disposition_membership import db,actor,job_version
from backend.services.api.tests.test_disposition_review import task,officer
from backend.services.api.tests.test_disposition_communications import smtp,communications_state


def test_current_task_email_projection_filtered_history_and_postcompletion_resend(client,monkeypatch):
    job,_,mgr=ready(monkeypatch)
    assert run_pass(db,1)=={'units_processed':1,'certificates_processed':1,'operations_processed':0}
    with db() as c:
        actor(c);smtp(c)
        cert=c.execute("SELECT id FROM disposition_job_documents WHERE job_id=%s AND document_type='digital_destruction_certificate'",(job['id'],)).fetchone()['id']
        request=c.execute("SELECT id FROM disposition_job_documents WHERE job_id=%s AND document_type='destruction_request'",(job['id'],)).fetchone()['id']
        officer_role=officer(c)
        before=c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']
        assert before['lifecycle_state']=='active'
    workspace=client.get(f"/api/v1/disposition/jobs/{job['id']}/workspace").json()
    assert workspace['email']['documents'][0]['latest_attempt'] is None
    payload=dict(command_id=str(uuid4()),acting_role_id=mgr,expected_recipient='archives@test.invalid')
    path=f"/api/v1/disposition/jobs/{job['id']}/documents/{cert}/email"
    assert client.post(path,json={**payload,'acting_role_id':officer_role}).status_code==403
    sent=client.post(path,json=payload);assert sent.status_code==202,sent.text
    assert client.post(path,json=payload).json()==sent.json()
    workspace=client.get(f"/api/v1/disposition/jobs/{job['id']}/workspace").json()
    latest=next(d for d in workspace['email']['documents'] if d['id']==cert)['latest_attempt']
    assert latest['status']=='sending' and latest['recipient']=='archives@test.invalid'
    assert set(latest)=={'id','status','requested_at','outcome_at','recipient'}
    assert email.process_one(db,transport=lambda *a:('smtp_accepted',None,250,None))
    history=f"/api/v1/disposition/jobs/{job['id']}/email-attempts"
    page=client.get(history,params=dict(document_id=cert,limit=1,offset=0)).json()
    assert page['total']==1 and page['items'][0]['document_id']==cert and page['items'][0]['status']=='smtp_accepted'
    assert client.get(history,params=dict(document_id=request,limit=1)).json()=={'items':[],'total':0}
    assert client.get(history,params=dict(document_id=-1)).status_code==422
    with db() as c:
        actor(c)
        assert c.execute('SELECT to_jsonb(j) value FROM disposition_jobs j WHERE id=%s',(job['id'],)).fetchone()['value']==before
        t=task(c,job['id'])
        completion.complete_task(c,job_id=job['id'],task_id=t['id'],task_version=t['version'],expected_version=job_version(c,job['id']),acting_role_id=mgr,command_id=uuid4())
    # Same saved certificate remains sendable after explicit completion.
    assert client.post(path,json={**payload,'command_id':str(uuid4())}).status_code==202
    page=client.get(history,params=dict(document_id=cert,limit=1)).json()
    assert page['total']==2 and page['items'][0]['status']=='sending'
    workspace=client.get(f"/api/v1/disposition/jobs/{job['id']}/workspace").json()
    assert workspace['job']['lifecycle_state']=='completed'
    assert next(d for d in workspace['email']['documents'] if d['id']==cert)['latest_attempt']['id']==page['items'][0]['id']


def test_certificate_send_projection_rechecks_current_manager_authority(client,monkeypatch):
    job,_,mgr=ready(monkeypatch);run_pass(db,1)
    with db() as c:
        actor(c);officer(c)
        assert any(d['document_type']=='digital_destruction_certificate' for d in email.controls(c,job['id'])['documents'])
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        assert not any(d['document_type']=='digital_destruction_certificate' for d in email.controls(c,job['id'])['documents'])
