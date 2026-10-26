"""Actual recipients throughout post-review stages, including automated completion."""
import pytest
from backend.services.api.disposition import handoff, documents, destruction, completion
from backend.services.api.tests.test_disposition_membership import db, actor
from backend.services.api.tests.test_disposition_review import claim, task
from backend.services.api.tests.test_disposition_external import prepared, generate, decision
from backend.services.api.tests.test_disposition_physical import report, confirmation
from backend.services.api.tests.test_disposition_destruction import request
from backend.services.api.tests.test_disposition_recovery import make_unit


@pytest.mark.parametrize('language', ['en','ar'])
def test_post_review_handoffs_and_certificate_download_use_actual_tasks(client, monkeypatch, language):
    from tools.preview_disposition import preview_pdf
    from psycopg.types.json import Jsonb
    from backend.services.api.tests import test_disposition_workflow as fixtures
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    monkeypatch.setattr(fixtures,'ready',lambda c:make_unit(c,'mixed'))
    def check(c, result, job, stage, *, completed=False):
        value=handoff.describe(c,result,language,job_id=job['id'])
        assert value['next_stage']==stage and value['workflow_completed']==completed
        expected={'kind':'role_queue','name':'مدير الوثائق' if language=='ar' else 'records-manager'} if stage in ('physical_destruction','digital_destruction') else {'kind':'person','name':'المراجع' if language=='ar' else 'Test Administrator'}
        assert value['next_recipients']==[expected]
        return value
    with db() as c:
        job,root,mgr,rid=prepared(c)
        c.execute('UPDATE users SET translations=%s WHERE id=1',(Jsonb({'ar':{'name':'المراجع'}}),))
        c.execute('UPDATE roles SET translations=%s WHERE id=%s',(Jsonb({'ar':{'name':'مدير الوثائق'}}),mgr))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES(1,%s,'Asia/Dubai')",(language,))
        result=generate(c,job,mgr,rid)
        check(c,result,job,'external_approval_pending')
        result=decision(c,job)
        check(c,result,job,'physical_destruction')
        c.commit();actor(c)
        report(c,job,mgr);claim(c,job);c.commit();actor(c)
        result=confirmation(c,job,mgr)
        check(c,result,job,'digital_destruction')
        c.commit();actor(c);claim(c,job);request(c,job,mgr)
    assert destruction.process_one(db)
    with db() as c:
        actor(c)
        value=handoff.describe(c,destruction.progress(c,job['id']),language,job_id=job['id'])
        assert value['next_stage']=='certificate_generation' and value['next_recipients']==[] and not value['workflow_completed']
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/destruction-progress")
    assert response.status_code==200 and response.json()['next_stage']=='certificate_generation' and response.json()['next_recipients']==[]
    assert completion.process_one(db)
    with db() as c:
        actor(c)
        check(c,{},job,'certificate_generation',completed=True)
        assert task(c,job['id'])['task_type']=='certificate_download'
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/completion-progress")
    assert response.status_code==200, response.text
    assert response.json()['workflow_completed'] and response.json()['next_recipients']==[{'kind':'person','name':'المراجع' if language=='ar' else 'Test Administrator'}]


def test_external_rejection_returns_to_actual_assigned_officer(client, monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid)
        result=decision(c,job,outcome='rejected',notes='Correct and resubmit')
        value=handoff.describe(c,result,'en')
        assert value['next_stage']=='officer_correction'
        assert value['next_recipients']==[{'kind':'person','name':'Test Administrator'}]


def test_physical_only_completion_does_not_invent_a_following_stage(client, monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.tests import test_disposition_workflow as fixtures
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    monkeypatch.setattr(fixtures,'ready',lambda c:make_unit(c,'physical'))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);decision(c,job)
        c.commit();actor(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        result=confirmation(c,job,mgr)
        value=handoff.describe(c,result,'en')
        assert value['workflow_completed'] and value['next_stage'] is None and value['next_recipients']==[]
