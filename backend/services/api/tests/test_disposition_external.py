"""Phase 17 request, external decision and correction acceptance; disposable DB only."""
from uuid import uuid4
from copy import deepcopy
import pytest
import psycopg
from backend.services.api.disposition import external,artifacts,documents,membership
from backend.services.api.disposition.commands import StaleVersion
from backend.services.api.application_settings import load_snapshot
from backend.services.api.content_storage import stage_governed_upload
from backend.services.api.tests.test_disposition_approval import manager,reach_manager,approve
from backend.services.api.tests.test_disposition_review import db,officer,task,submit,claim,decide,save,create
from backend.services.api.tests.test_disposition_artifacts import configure,root as destination_root,uploaded
from backend.services.api.tests.test_disposition_membership import actor,job_version,ready,admit,setup


def prepared(c,route='simplified'):
    job,root,mgr=manager(c,route);configure(c);destination_root(c)
    reach_manager(c,job,route)
    result=approve(c,job,mgr,overall_reason='Review complete current membership' if route=='records_manager_only' else None)
    return job,root,mgr,result['round_id']


def generate(c,job,mgr,rid):
    c.commit();actor(c)
    result=external.generate_request(c,job_id=job['id'],round_id=rid,acting_role_id=mgr,settings=load_snapshot(c),connection_factory=db)
    c.commit();actor(c)
    return result


def decision(c,job,*,outcome='approved',number='SA/2026-#1',notes=None,key=None,acting=None):
    t=task(c,job['id']);role=acting or (c.execute("SELECT id FROM roles WHERE profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') ORDER BY id LIMIT 1").fetchone() or {}).get('id')
    if acting is None:role=officer(c) if c.execute('SELECT review_route FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['review_route']!='records_manager_only' else role
    kind='external_approval_letter' if outcome=='approved' else 'external_rejection_letter'
    with stage_governed_upload(uploaded(b'Authority letter'),load_snapshot(c),connection_factory=db) as staged:
        return external.decide(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],request_document_id=t['request_document_id'],decision=outcome,correction_notes=notes,destruction_number=number if outcome=='approved' else None,staged=staged,preview=artifacts.destination_token(artifacts.destination(c,job['id'],kind)),acting_role_id=role,command_id=key or uuid4())


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_request_exact_approved_groups_round_and_direct_task(client,route,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{'renderer':'test'}))
    with db() as c:
        job,root,mgr,rid=prepared(c,route);out=generate(c,job,mgr,rid)
        doc=artifacts.document(c,job['id'],out['request_document_id']);snapshot=doc['provenance']['snapshot']
        assert snapshot['fields']['counts.roots']==1 and snapshot['fields']['counts.descendant_aggregations']==2 and snapshot['fields']['counts.records']==1
        assert len(snapshot['aggregations'])==1 and snapshot['aggregations'][0]['aggregation.records']==1
        assert snapshot['fields']['authority.name']=='دار الوثائق في إمارة الشارقة / Sharjah Archives' and snapshot['fields']['review.records_manager']
        if route!='standard':assert 'Skipped' in snapshot['fields']['review.unit_manager']
        assert c.execute('SELECT workflow_stage FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['workflow_stage']=='external_approval_pending'
        assert task(c,job['id'])['destination_user_id']==job['assigned_user_id']
        assert generate(c,job,mgr,rid)['request_document_id']==doc['id']
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='destruction_request'").fetchone()['n']==1


@pytest.mark.parametrize('number',['A','رقم/إتلاف #١','  A/1  ','12345678901234567890'])
def test_received_approval_keeps_exact_number_and_governed_letter(client,number,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);result=decision(c,job,number=number)
        row=c.execute('SELECT * FROM disposition_external_approvals WHERE id=%s',(result['id'],)).fetchone()
        assert row['destruction_number']==number and row['recorded_by_user_id']==1 and row['acting_role_id']==officer(c)
        assert c.execute('SELECT destruction_number FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['destruction_number']==number
        assert artifacts.document(c,job['id'],row['approval_letter_document_id'])['record_id']
        assert task(c,job['id'])['task_type']=='physical_destruction'
        assert external.history(c,job['id'],limit=1,offset=0)['items'][0]['decision']=='approved'


@pytest.mark.parametrize('number',['','   ','123456789012345678901'])
def test_invalid_number_never_creates_evidence_or_consumes_task(client,number,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        with pytest.raises(Exception,match='disposition_destruction_number_invalid'):
            decision(c,job,number=number)
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before and task(c,job['id'])['task_state']=='open'


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_external_rejection_preserves_form_and_repeats_saved_route(client,route,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c,route);first=generate(c,job,mgr,rid)
        result=decision(c,job,outcome='rejected',notes='Correct the authority schedule',acting=mgr if route=='records_manager_only' else officer(c))
        assert result['workflow_stage']==('manager_correction' if route=='records_manager_only' else 'officer_correction')
        reach_manager(c,job,route)
        renewed=approve(c,job,mgr,overall_reason='Corrected authority schedule' if route=='records_manager_only' else None)
        second=generate(c,job,mgr,renewed['round_id'])
        assert second['request_document_id']!=first['request_document_id']
        assert artifacts.document(c,job['id'],first['request_document_id'])['id']
        assert external.history(c,job['id'],limit=1,offset=0)['items'][0]['correction_notes']=='Correct the authority schedule'
        assert c.execute('SELECT count(*) n FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()['n']==2


def test_changed_approved_facts_block_approval_and_renew_complete_review(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid)
        c.execute('UPDATE aggregation_retention_rules SET current_period_years=6 WHERE aggregation_id=%s',(root,))
        c.commit();actor(c)
        assert not external.view(c,c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone())['approval_current']
        with pytest.raises(psycopg.Error,match='disposition_approval_invalidated'),c.transaction():decision(c,job)
        assert not c.execute('SELECT 1 FROM disposition_external_approvals').fetchone()
        external.renew(c,job_id=job['id'],round_id=rid,expected_version=job_version(c,job['id']),acting_role_id=officer(c),command_id=uuid4())
        assert task(c,job['id'])['workflow_stage']=='officer_correction'
        assert c.execute('SELECT invalidated_at FROM disposition_review_rounds WHERE id=%s',(rid,)).fetchone()['invalidated_at']


def test_protective_blocker_preserves_approval_but_never_destroys_content(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        c.commit();actor(c)
        assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) allowed',(job['id'],rid)).fetchone()['allowed']
        result=decision(c,job)
        assert result['decision']=='approved' and c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6


def test_request_excludes_applied_removals_and_separates_local_sources(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,removed,mgr=manager(c,'simplified');configure(c);destination_root(c)
        classification,*_=ready(c);local,*_=ready(c)
        c.execute('DELETE FROM aggregation_retention_rules WHERE aggregation_id=%s',(classification,))
        admit(c,job['id'],[classification,local]);save(c,job,changes=[create(c,removed)])
        reach_manager(c,job,'simplified');out=approve(c,job,mgr)
        request=generate(c,job,mgr,out['round_id']);snap=artifacts.document(c,job['id'],request['request_document_id'])['provenance']['snapshot']
        assert snap['fields']['counts.roots']==2 and len(snap['aggregations'])==2
        assert {r['id'] for r in snap['source']['approved_facts']['source']['roots']}=={classification,local}
        assert all(row['aggregation.classification_code'] for row in snap['aggregations'])
        versions=c.execute('SELECT id,version FROM disposition_review_proposals WHERE job_id=%s',(job['id'],)).fetchall()
        decision(c,job,outcome='rejected',notes='New authority round')
        reach_manager(c,job,'simplified');second=approve(c,job,mgr);generate(c,job,mgr,second['round_id'])
        assert c.execute('SELECT id,version FROM disposition_review_proposals WHERE job_id=%s',(job['id'],)).fetchall()==versions
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==3


def test_exact_external_retry_returns_one_letter_decision_number_and_correction_task(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);t=task(c,job['id']);key=uuid4();v=job_version(c,job['id'])
        preview=artifacts.destination_token(artifacts.destination(c,job['id'],'external_rejection_letter'))
        def invoke(notes='Required authority corrections'):
            with stage_governed_upload(uploaded(b'Exact retry letter'),load_snapshot(c),connection_factory=db) as staged:
                return external.decide(c,task_id=t['id'],expected_version=v,task_version=t['version'],request_document_id=t['request_document_id'],decision='rejected',correction_notes=notes,destruction_number=None,staged=staged,preview=preview,acting_role_id=officer(c),command_id=key)
        first=invoke();c.commit();actor(c);assert invoke()==first
        assert c.execute('SELECT count(*) n FROM disposition_external_approvals').fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='external_rejection_letter'").fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM disposition_tasks WHERE job_id=%s AND task_state='open'",(job['id'],)).fetchone()['n']==1
        with pytest.raises(psycopg.Error,match='disposition_command_conflict'):invoke('Changed retry payload')


def test_duplicate_number_after_termination_rolls_back_every_new_evidence_row(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        first,root,mgr,rid=prepared(c);generate(c,first,mgr,rid);decision(c,first,number='Permanent / #1')
        membership.terminate_job(c,job_id=first['id'],expected_version=job_version(c,first['id']),acting_role_id=officer(c),reason='Terminate approved fixture',command_id=uuid4(),confirmed=True)
        second=setup(c);new_root,*_=ready(c);admit(c,second['id'],[new_root]);reach_manager(c,second,'simplified');rid=approve(c,second,mgr)['round_id'];generate(c,second,mgr,rid)
        records=c.execute('SELECT count(*) n FROM records').fetchone()['n'];docs=c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']
        with pytest.raises(psycopg.Error,match='disposition_destruction_number_used'):decision(c,second,number='Permanent / #1')
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==records
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==docs
        assert task(c,second['id'])['task_state']=='open'


def test_late_external_failure_rolls_back_letter_number_task_and_event(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        c.execute("CREATE FUNCTION pg_temp.fail_external() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic external failure'; END $$")
        c.execute('CREATE TRIGGER zz_fail_external AFTER INSERT ON disposition_external_approvals FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_external()')
        with pytest.raises(psycopg.Error,match='Synthetic external failure'):decision(c,job,number='Rolled back number')
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert not c.execute('SELECT 1 FROM disposition_external_approvals').fetchone()
        assert not c.execute('SELECT 1 FROM disposition_private.destruction_numbers').fetchone()
        assert task(c,job['id'])['task_state']=='open'
        c.execute('DROP TRIGGER zz_fail_external ON disposition_external_approvals')


def test_request_failure_does_not_create_document_or_task_and_retry_never_reexecutes(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    with db() as c:
        job,root,mgr,rid=prepared(c);c.commit();actor(c)
        monkeypatch.setattr(documents.engine,'render',lambda *args:(_ for _ in ()).throw(RuntimeError('Renderer failure')))
        with pytest.raises(RuntimeError,match='Renderer failure'):generate(c,job,mgr,rid)
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='destruction_request'").fetchone()
        assert not c.execute("SELECT 1 FROM disposition_tasks WHERE job_id=%s AND task_type='external_approval'",(job['id'],)).fetchone()
        monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}));generate(c,job,mgr,rid)
        assert c.execute('SELECT count(*) n FROM disposition_review_decisions').fetchone()['n']==1


def test_http_approval_generates_request_and_received_rejection_is_atomic_and_retryable(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.disposition import approval
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr=manager(c,'simplified');configure(c);destination_root(c);reach_manager(c,job,'simplified')
        t=task(c,job['id']);p=approval.preview(c,t['id'],mgr);c.commit()
    headers={'If-Match':str(p['job_version']),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    payload=dict(command_id=str(uuid4()),acting_role_id=mgr,task_version=p['task_version'],membership_token=p['membership_token'],proposals_token=p['proposals_token'])
    response=client.post(f"/api/v1/disposition/tasks/{t['id']}/approve-proposals",json=payload,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['request_status']=='available' and response.json()['report_status']=='available'
    with db() as c:
        actor(c);t=task(c,job['id']);v=job_version(c,job['id']);role=officer(c);token=artifacts.destination_token(artifacts.destination(c,job['id'],'external_rejection_letter'))
    fields=dict(command_id=str(uuid4()),acting_role_id=str(role),task_version=str(t['version']),request_document_id=str(t['request_document_id']),decision='rejected',correction_notes='Authority requires a corrected schedule',destination_token=token)
    headers={'If-Match':str(v),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    path=f"/api/v1/disposition/tasks/{t['id']}/external-decision"
    invalid=client.post(path,data={**fields,'correction_notes':'  '},files={'file':('letter.pdf',preview_pdf(),'application/pdf')},headers=headers)
    assert invalid.status_code==422
    result=client.post(path,data=fields,files={'file':('letter.pdf',preview_pdf(),'application/pdf')},headers=headers)
    assert result.status_code==200,result.text
    retry=client.post(path,data=fields,files={'file':('letter.pdf',preview_pdf(),'application/pdf')},headers=headers)
    assert retry.status_code==200 and retry.json()==result.json(),retry.text
    page=client.get(f"/api/v1/disposition/jobs/{job['id']}/external-decisions?limit=1&offset=0&sort=decision&descending=false")
    assert page.status_code==200 and page.json()['total']==1 and page.json()['items'][0]['letter_name']=='letter.pdf'
    with db() as c:
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='external_rejection_letter'").fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM disposition_external_approvals').fetchone()['n']==1


def test_request_requires_current_actual_manager_and_decision_requires_assigned_preparer(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.tests.test_disposition_workflow import person,role
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c)
        with pytest.raises(Exception,match='disposition_manager_role_required'):external.generate_request(c,job_id=job['id'],round_id=rid,acting_role_id=officer(c),settings=load_snapshot(c),connection_factory=db)
        generate(c,job,mgr,rid);other=person(c,'Unassigned Officer');other_role=role(c,'unassigned-officer','INFO_GOV_OFFICER',user=other)
        c.commit();actor(c,other)
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'),c.transaction():decision(c,job,acting=other_role)
        assert not c.execute('SELECT 1 FROM disposition_external_approvals').fetchone()


def test_request_generation_rechecks_post_render_fact_changes_and_rolls_back_document(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    with db() as c:
        job,root,mgr,rid=prepared(c);c.commit();actor(c)
        def changed(*args):
            with db() as other:
                actor(other);other.execute('UPDATE aggregation_retention_rules SET current_period_years=6 WHERE aggregation_id=%s',(root,))
            return preview_pdf(),{}
        monkeypatch.setattr(documents.engine,'render',changed)
        with pytest.raises(StaleVersion,match='disposition_stale_version'):generate(c,job,mgr,rid)
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='destruction_request'").fetchone()
        assert not c.execute("SELECT 1 FROM disposition_tasks WHERE job_id=%s AND task_type='external_approval'",(job['id'],)).fetchone()


def test_large_request_groups_and_actual_pdf_paginate_without_losing_final_group(client):
    from pathlib import Path
    from io import BytesIO
    from pypdf import PdfReader
    from backend.services.api.tests.test_disposition_templates import sample
    snap=sample('destruction_request',rows=0)
    snap['aggregations']=[{'aggregation.serial_number':index,'aggregation.number':f'AGG-{index:04}','aggregation.title':f'ملف الوثائق {index} / Aggregation {index}',
      'aggregation.from_year':1990,'aggregation.to_year':2026,'aggregation.classification_code':f'CLASS-{index:04}',
      'aggregation.records':3,'aggregation.assigned_location':'المستودع / Repository'} for index in range(1,121)]
    snap['fields'].update({'job.number':'PHASE17-LARGE-120','counts.roots':120,'counts.descendant_aggregations':0,'counts.records':0,'counts.physical':0,'counts.digital':0,'counts.mixed':120})
    with db() as c:settings=load_snapshot(c)
    content,_=documents.engine.render(documents.default('destruction_request')['content'],'destruction_request',snap,settings)
    reader=PdfReader(BytesIO(content));assert len(reader.pages)>2
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert 'CLASS-0001' in text and 'CLASS-0120' in text
    assert '{{' not in text and '}}' not in text
    Path('/private/tmp/phase17-large-request.pdf').write_bytes(content)


def test_concurrent_received_decisions_have_one_winner_and_one_letter(client,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);t=task(c,job['id']);v=job_version(c,job['id']);acting=officer(c);token=artifacts.destination_token(artifacts.destination(c,job['id'],'external_approval_letter'))
    def record(number):
        return client.post(f"/api/v1/disposition/tasks/{t['id']}/external-decision",data={'command_id':str(uuid4()),'acting_role_id':str(acting),'task_version':str(t['version']),'request_document_id':str(t['request_document_id']),'decision':'approved','destruction_number':number,'destination_token':token},files={'file':('approval.pdf',preview_pdf(),'application/pdf')},headers={'If-Match':str(v),'X-CSRF-Token':client.cookies.get('erms_csrf')})
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(record,['CONCURRENT-A','CONCURRENT-B']))
    assert sum(r.status_code==200 for r in responses)==1,[r.text for r in responses]
    assert all(r.status_code in (200,403,409) for r in responses)
    with db() as c:
        assert c.execute('SELECT count(*) n FROM disposition_external_approvals').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM disposition_private.destruction_numbers').fetchone()['n']==1
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='external_approval_letter'").fetchone()['n']==1


def test_history_redacts_notes_when_letter_becomes_hidden(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.tests.test_disposition_workflow import person,role
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);result=decision(c,job,outcome='rejected',notes='Protected authority notes')
        reader=person(c,'Limited historical reviewer');limited=role(c,'limited-external-reviewer','FILE_ADMIN',user=reader)
        # Give a historical task association through the existing role queue;
        # it grants no evidence ACLs or security clearance.
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(reader,mgr))
        high=c.execute('SELECT id FROM security_levels ORDER BY level_number DESC LIMIT 1').fetchone()['id']
        letter=artifacts.document(c,job['id'],result['letter_document_id'])
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,letter['aggregation_id']))
        c.execute('UPDATE records SET security_level_id=%s WHERE id=%s',(high,letter['record_id']))
        actor(c,reader)
        page=external.history(c,job['id'],limit=1,offset=0)
        assert page['items']==[{'id':result['id'],'redacted':True}]
        assert not c.execute("SELECT current_user_can_view_event_resource('disposition_job',job_id,NULL,to_jsonb(a)) allowed FROM disposition_external_approvals a WHERE id=%s",(result['id'],)).fetchone()['allowed']


def test_current_approval_uses_semantic_facts_across_timezones(client):
    with db() as c:
        job,root,mgr,rid=prepared(c)
        assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) allowed',(job['id'],rid)).fetchone()['allowed']
        c.execute("SET LOCAL timezone='Asia/Dubai'")
        assert c.execute('SELECT disposition_private.request_approval_current(%s,%s) allowed',(job['id'],rid)).fetchone()['allowed']


def test_request_grouping_is_bounded_in_work_and_does_not_combine_different_local_rules():
    from backend.services.api.disposition.document_snapshots import request_groups
    roots=[];aggs=[];records=[]
    for index in range(1,2001):
        roots.append({'id':index,'rule_snapshot':{'rule_source':'aggregation','current_period_years':5,'intermediate_period_years':1,'final_disposition':'destruction','instructions':'A' if index%2 else 'B'}})
        aggs.append({'id':index,'root_id':index,'classification_id':1,'classification_code':'CLASS','classification_title':'Shared classification','medium':'digital'})
        records.append({'id':index,'aggregation_id':index,'medium':'digital'})
    groups=request_groups({'roots':roots,'aggregations':aggs,'records':records})
    assert len(groups)==2 and sum(g['group.roots'] for g in groups)==2000
    assert sum(g['group.records'] for g in groups)==2000 and sum(g['group.digital'] for g in groups)==4000


def test_retained_request_does_not_regenerate_after_settings_or_template_changes(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);first=generate(c,job,mgr,rid)
        before=artifacts.document(c,job['id'],first['request_document_id'])
        version=c.execute("SELECT version FROM application_settings WHERE key='DISPOSITION_EXTERNAL_AUTHORITY_NAME'").fetchone()['version']
        import json
        c.execute('SELECT apply_application_settings(%s,%s)',(json.dumps([{'key':'DISPOSITION_EXTERNAL_AUTHORITY_NAME','value':'New authority name','expected_version':version}]),'Change future request addressee'))
        c.commit();actor(c)
        monkeypatch.setattr(documents.engine,'render',lambda *args:(_ for _ in ()).throw(RuntimeError('Must retain exact existing PDF')))
        second=generate(c,job,mgr,rid);after=artifacts.document(c,job['id'],second['request_document_id'])
        assert before==after and after['provenance']['snapshot']['fields']['authority.name']=='دار الوثائق في إمارة الشارقة / Sharjah Archives'


def test_external_decisions_and_number_claims_are_immutable_outside_their_operation(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.disposition.commands import execute_command
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);decision(c,job,number='Permanently reserved')
        for query in ["UPDATE disposition_external_approvals SET correction_notes='rewrite'","DELETE FROM disposition_external_approvals","DELETE FROM disposition_private.destruction_numbers"]:
            with pytest.raises(psycopg.Error,match='disposition_external_immutable|disposition_number_immutable'):
                execute_command(c,command_id=uuid4(),operation='review_decide',payload={'job_id':job['id']},acting_role_id=officer(c),reason='Must not rewrite received history',apply=lambda x,q=query: (x.execute(q),{})[1])


def test_received_decision_is_projected_read_only_after_task_completion(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    from backend.services.api.disposition import workspace
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);decision(c,job)
        view=workspace.read(c,job['id'])
        assert view['task']['task_type']=='physical_destruction' and view['actions']==['claim','reassign']
        assert view['external']['received_decision']=='approved' and not view['external']['can_generate']
