"""Phase 15 execution acceptance, disposable runner only."""
from uuid import uuid4

import psycopg
import pytest

from backend.services.api.disposition import approval
from backend.services.api.tests.test_disposition_review import db,seeded,task,officer,save,create,submit,claim,decide,data
from backend.services.api.tests.test_disposition_membership import ready,admit,actor,job_version


def manager(c,route='standard'):
    job,root,um,fa,mgr=seeded(c,route)
    return job,root,mgr


def reach_manager(c,job,route):
    if route!='records_manager_only':
        submit(c,job)
        if route=='standard':claim(c,job);decide(c,job)
        claim(c,job)


def approve(c,job,mgr,**extra):
    t=task(c,job['id']);p=approval.preview(c,t['id'],mgr)
    return approval.approve(c,task_id=t['id'],expected_version=p['job_version'],task_version=p['task_version'],membership_token=p['membership_token'],proposals_token=p['proposals_token'],acting_role_id=mgr,command_id=uuid4(),**extra)


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_atomic_empty_approval_executes_vital_and_preserves_original_proposer(client,route):
    with db() as c:
        job,root,mgr=manager(c,route);acting=mgr if route=='records_manager_only' else officer(c)
        pid=save(c,job,acting=acting,changes=[create(c,root)])['changes'][0]['id'];reach_manager(c,job,route)
        result=approve(c,job,mgr,overall_reason='Approve complete unit' if route=='records_manager_only' else None)
        assert result['remaining_units']==0
        p=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()
        assert p['proposal_state']=='executed' and p['executed_by_user_id']==1 and p['proposer_role_id']==acting
        assert c.execute('SELECT is_vital,disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()=={'is_vital':True,'disposition_status':2}
        assert task(c,job['id'])['workflow_stage']==('manager_preparation' if route=='records_manager_only' else 'officer_correction')
        assert c.execute('SELECT approval_execution FROM disposition_review_rounds WHERE id=%s',(result['round_id'],)).fetchone()['approval_execution']['results'][0]['id']==pid


def test_every_governance_type_executes_as_one_plan_and_keeps_selected_holds(client):
    from backend.services.api.tests.test_disposition_review import payloads
    with db() as c:
        job,root,mgr=manager(c);changes=payloads(c,root)[1:]
        changes[1]=create(c,root,'blocking_security',changes[1]['proposed_values'])
        changes[3]['proposed_values']['related_aggregation_id']=root
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(changes[1]['proposed_values']['security_level_id'],))
        save(c,job,changes=changes);reach_manager(c,job,'standard');out=approve(c,job,mgr)
        assert out['remaining_units']==0
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE proposal_state='executed'").fetchone()['n']==7
        assert c.execute('SELECT count(*) n FROM hold_aggregation_assignments').fetchone()['n']==2
        assert c.execute('SELECT count(*) n FROM disposition_proposal_holds').fetchone()['n']==0
        assert len(c.execute("SELECT proposed_values FROM disposition_review_proposals WHERE proposal_type='add_to_holds'").fetchone()['proposed_values']['hold_ids'])==2
        assert not c.execute('SELECT 1 FROM record_relationships').fetchone()
        saved_round=approval.execution(c,job['id'],out['round_id'],mgr)
        report=approval.report_snapshot(saved_round)
        record_result=next(r for r in report['proposals'] if r['proposal.action']=='Remove Record Relationship')
        actual_record=c.execute('SELECT record_number FROM records WHERE id=%s',(changes[5]['target_record_id'],)).fetchone()
        assert actual_record['record_number'] in record_result['proposal.target']
        assert c.execute('SELECT current_period_years FROM aggregation_retention_rules WHERE aggregation_id=%s',(root,)).fetchone()['current_period_years']==6
        events=c.execute("SELECT actor_type,actor_user_id,metadata FROM event_history WHERE operation IN ('VITAL_STATUS_CHANGED','SECURITY_LEVEL_UPGRADED','RESOURCE_ADDED_TO_HOLD')").fetchall()
        assert events and all(e['actor_type']=='user' and e['actor_user_id']==1 and e['metadata']['acting_role_id']==mgr and e['metadata']['proposal_id'] for e in events)


@pytest.mark.parametrize('proposal_type,privilege',[('make_vital','aggregation.vital_status.change'),('blocking_security','aggregation.security_level.change'),('create_aggregation_relationship','relationships.link'),('remove_aggregation_relationship','relationships.link'),('remove_record_relationship','relationships.link'),('local_retention_override','classifications.administer')])
def test_every_underlying_privilege_is_checked_before_any_resource_write(client,proposal_type,privilege):
    from backend.services.api.tests.test_disposition_review import payloads
    with db() as c:
        job,root,mgr=manager(c);available=payloads(c,root)
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(available[2]['proposed_values']['security_level_id'],))
        chosen=next(p for p in available if p['proposal_type']==proposal_type)
        save(c,job,changes=[chosen]);reach_manager(c,job,'standard');before=data(c,root)
        with c.transaction(force_rollback=True):
            c.execute('DELETE FROM profile_privileges WHERE privilege_id=(SELECT id FROM privileges WHERE code=%s)',(privilege,))
            with pytest.raises(psycopg.Error,match='disposition_proposal_requires_correction'):approve(c,job,mgr)
            assert data(c,root)==before
            assert not c.execute("SELECT 1 FROM disposition_review_decisions WHERE review_stage='records_manager_review'").fetchone()
            assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==0


def test_hold_visibility_does_not_grant_hold_management(client):
    with db() as c:
        job,root,mgr=manager(c)
        from backend.services.api.tests.test_disposition_workflow import person
        owner=person(c)
        h=c.execute("INSERT INTO holds(code,name,owner_user_id,valid_from) VALUES('OTHER-HOLD','Visible to governance',%s,CURRENT_TIMESTAMP) RETURNING id",(owner,)).fetchone()['id']
        save(c,job,changes=[create(c,root,'add_to_holds',{'hold_ids':[h]})]);reach_manager(c,job,'standard')
        with c.transaction(force_rollback=True):
            c.execute("DELETE FROM profile_privileges WHERE privilege_id IN (SELECT id FROM privileges WHERE code IN ('holds.administer','holds.held_items.manage_all'))")
            with pytest.raises(psycopg.Error,match='disposition_proposal_requires_correction'):approve(c,job,mgr)
            assert not c.execute('SELECT 1 FROM hold_aggregation_assignments').fetchone()


def test_cascading_old_links_reach_a_stable_result_and_record_causal_proposals(client):
    with db() as c:
        job,a,mgr=manager(c);b,*_=ready(c);d,*_=ready(c);admit(c,job['id'],[b,d])
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s),(%s,%s,%s)',(kind,a,b,kind,b,d))
        child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(a,)).fetchone()['id']
        pid=save(c,job,changes=[create(c,a,target=child)])['changes'][0]['id'];reach_manager(c,job,'standard');out=approve(c,job,mgr)
        assert out['remaining_units']==0 and set(out['removed_units'])=={str(a),str(b),str(d)}
        effects=c.execute("SELECT governing_root_id,effect_type FROM disposition_proposal_effects WHERE proposal_id=%s AND effect_type IN ('unit_removed','cascading_unit_removed')",(pid,)).fetchall()
        assert {e['governing_root_id'] for e in effects}=={a,b,d} and sum(e['effect_type']=='cascading_unit_removed' for e in effects)==2


@pytest.mark.parametrize('with_matching_proposal',[False,True])
def test_independent_existing_blockers_do_not_automatically_remove_units_on_approval(client,with_matching_proposal):
    with db() as c:
        job,root,mgr=manager(c);other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s)',(kind,root,other))
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        if with_matching_proposal:save(c,job,changes=[create(c,root)])
        # Independent changes before submission are part of the reviewed round;
        # their blocker state does not authorize membership removal by itself.
        reach_manager(c,job,'standard');result=approve(c,job,mgr)
        assert result['remaining_units']==1 and not result['removed_units']
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6


@pytest.mark.parametrize('action,expected',[('destruction',1),('retain_as_local_archives',5),('transfer_to_external_archive',3)])
def test_retention_override_removal_keeps_recalculated_full_unit_status(client,action,expected):
    with db() as c:
        job,root,mgr=manager(c)
        values=dict(current_period_years=100 if action=='destruction' else 0,intermediate_period_years=0,final_disposition=action,instructions='Approved local rule')
        save(c,job,changes=[create(c,root,'local_retention_override',values)]);reach_manager(c,job,'standard');out=approve(c,job,mgr)
        assert out['remaining_units']==0
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==expected
        assert {r['disposition_status'] for r in c.execute('SELECT disposition_status FROM records')}=={expected}


def test_new_link_and_other_protection_cascade_together(client):
    with db() as c:
        job,a,mgr=manager(c);b,*_=ready(c);admit(c,job['id'],[b])
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        save(c,job,changes=[create(c,a,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=b,relationship_type_id=kind)),create(c,a)])
        reach_manager(c,job,'standard');out=approve(c,job,mgr);assert out['remaining_units']==0
        assert str(b) in out['removed_units']


def test_whole_approval_rolls_back_after_a_late_resource_failure(client):
    with db() as c:
        job,root,mgr=manager(c);child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(root,)).fetchone()['id']
        save(c,job,changes=[create(c,root),create(c,root,target=child)]);reach_manager(c,job,'standard');before=data(c,root)
        c.execute("CREATE FUNCTION pg_temp.fail_phase15() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic late resource failure'; END $$")
        c.execute(f'CREATE TRIGGER zz_fail_phase15 BEFORE UPDATE ON aggregations FOR EACH ROW WHEN (NEW.id={child}) EXECUTE FUNCTION pg_temp.fail_phase15()')
        with pytest.raises(psycopg.Error,match='Synthetic late resource failure'):approve(c,job,mgr)
        assert data(c,root)==before and not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()
        assert not c.execute("SELECT 1 FROM disposition_review_decisions WHERE review_stage='records_manager_review'").fetchone()
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE proposal_state='active'").fetchone()['n']==2
        c.execute('DROP TRIGGER zz_fail_phase15 ON aggregations')


@pytest.mark.parametrize('drift',['target','proposal'])
def test_approval_tokens_bind_every_current_member_and_complete_proposal_set(client,drift):
    with db() as c:
        job,root,mgr=manager(c);pid=save(c,job,changes=[create(c,root)])['changes'][0]['id'];reach_manager(c,job,'standard')
        t=task(c,job['id']);values=approval.preview(c,t['id'],mgr)
        if drift=='target':
            c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        else:save(c,job,acting=mgr,changes=[create(c,root)])
        with pytest.raises(psycopg.Error):
            approval.approve(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=task(c,job['id'])['version'],membership_token=values['membership_token'],proposals_token=values['proposals_token'],acting_role_id=mgr,command_id=uuid4())
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['proposal_state']=='active'


def test_conflicting_complete_set_is_rejected_without_silent_omission(client):
    with db() as c:
        job,root,mgr=manager(c);values=dict(current_period_years=0,intermediate_period_years=0,final_disposition='destruction',instructions=None)
        save(c,job,changes=[create(c,root,'local_retention_override',values),create(c,root,'local_retention_override',{**values,'current_period_years':1})]);reach_manager(c,job,'standard')
        with pytest.raises(psycopg.Error,match='disposition_proposal_conflict'):approve(c,job,mgr)
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()


def test_different_manager_executes_with_own_identity_and_reason_fallback(client):
    from backend.services.api.tests.test_disposition_workflow import person,role
    with db() as c:
        job,root,mgr=manager(c);pid=save(c,job,changes=[create(c,root,reason='Proposal-specific reason')])['changes'][0]['id']
        submit(c,job);claim(c,job);decide(c,job)
        other=person(c,'Approving Manager');c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        # Underlying authority comes from this person's actual current roles.
        role(c,'executor-underlying-authority','ALL_PRIVS',user=other)
        actor(c,other);claim(c,job);out=approve(c,job,mgr)
        p=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()
        assert p['proposer_user_id']==1 and p['executed_by_user_id']==other and p['execution_message']['reason_source']=='proposal'
        events=c.execute("SELECT actor_user_id,actor_type,reason,metadata FROM event_history WHERE operation='VITAL_STATUS_CHANGED'").fetchall()
        assert all(e['actor_user_id']==other and e['actor_type']=='user' and e['reason']=='Proposal-specific reason' and e['metadata']['acting_role_id']==mgr for e in events)


def test_missing_claim_inactive_assignment_and_wrong_role_cannot_approve(client):
    with db() as c:
        job,root,mgr=manager(c);submit(c,job);claim(c,job);decide(c,job)
        with pytest.raises(psycopg.Error):approve(c,job,mgr)
        claim(c,job)
        with pytest.raises(psycopg.Error):approve(c,job,officer(c))
        c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(mgr,))
        with pytest.raises(psycopg.Error):approve(c,job,mgr)
        assert not c.execute("SELECT 1 FROM disposition_review_decisions WHERE review_stage='records_manager_review'").fetchone()


def test_report_uses_frozen_execution_and_retry_does_not_reexecute(client,monkeypatch):
    import hashlib
    from pathlib import Path
    from backend.services.api.tests.test_disposition_artifacts import configure,root as report_root
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.disposition import documents
    with db() as c:
        job,root,mgr=manager(c);configure(c);destination=report_root(c)
        save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard');out=approve(c,job,mgr);c.commit();actor(c)
        row=approval.execution(c,job['id'],out['round_id'],mgr);snapshot=approval.report_snapshot(row)
        assert snapshot['proposals'][0]['proposal.proposer'].startswith('Test Administrator')
        result=approval.generate_report(c,job_id=job['id'],round_id=out['round_id'],acting_role_id=mgr,settings=load_snapshot(c),connection_factory=db)
        c.commit();actor(c)
        pdf=c.execute('SELECT b.content FROM digital_component_blobs b JOIN digital_components dc ON dc.active_content_set_id=b.content_set_id WHERE dc.id=%s ORDER BY b.segment_no',(result['digital_component_id'],)).fetchall()
        content=b''.join(bytes(r['content']) for r in pdf);assert content.startswith(b'%PDF-')
        Path('/private/tmp/phase15-execution-report.pdf').write_bytes(content)
        version=c.execute('SELECT version FROM disposition_review_proposals').fetchone()['version']
        monkeypatch.setattr(documents.engine,'render',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Must reuse the existing report')))
        retry=approval.generate_report(c,job_id=job['id'],round_id=out['round_id'],acting_role_id=mgr,settings=load_snapshot(c),connection_factory=db)
        assert retry['id']==result['id'] and c.execute('SELECT version FROM disposition_review_proposals').fetchone()['version']==version
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='proposal_execution_report'").fetchone()['n']==1
        report=c.execute('SELECT * FROM disposition_job_documents WHERE id=%s',(result['id'],)).fetchone()
        assert report['aggregation_id']==destination and report['review_round']==1
        actual=report['provenance']['snapshot'];assert actual['source']==snapshot['source'] and actual['proposals']==snapshot['proposals']
        from datetime import datetime
        assert datetime.fromisoformat(actual['fields']['generated_at'])>=datetime.fromisoformat(snapshot['source']['executed_at'])
        assert {k:v for k,v in actual['fields'].items() if k!='generated_at'}=={k:v for k,v in snapshot['fields'].items() if k!='generated_at'}
        assert report['checksum']==hashlib.sha256(content).hexdigest()


def test_actual_http_commits_approval_even_when_report_fails_then_retry_stores_once(client,monkeypatch):
    from backend.services.api.tests.test_disposition_artifacts import configure,root as report_root
    from backend.services.api.disposition import documents
    with db() as c:
        job,root,mgr=manager(c);configure(c);report_root(c);save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard')
        t=task(c,job['id']);values=approval.preview(c,t['id'],mgr);c.commit()
    headers={'If-Match':str(values['job_version']),'X-CSRF-Token':client.cookies.get('erms_csrf')};payload=dict(command_id=str(uuid4()),acting_role_id=mgr,task_version=values['task_version'],membership_token=values['membership_token'],proposals_token=values['proposals_token'])
    original=documents.engine.render
    monkeypatch.setattr(documents.engine,'render',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Synthetic report failure')))
    path=f"/api/v1/disposition/tasks/{t['id']}/approve-proposals"
    result=client.post(path,json=payload,headers=headers);assert result.status_code==200,result.text
    out=result.json();assert out['report_status']=='pending'
    with db() as c:assert c.execute('SELECT is_vital FROM aggregations WHERE id=%s',(root,)).fetchone()['is_vital']
    monkeypatch.setattr(documents.engine,'render',original)
    retry_path=f"/api/v1/disposition/jobs/{job['id']}/review-rounds/{out['round_id']}/execution-report"
    retry=client.post(retry_path,json=dict(command_id=str(uuid4()),acting_role_id=mgr),headers=headers)
    assert retry.status_code==200 and retry.json()['report_status']=='available',retry.text
    again=client.post(path,json=payload,headers=headers);assert again.status_code==200 and again.json()['report_document_id']==retry.json()['report_document_id'],again.text
    with db() as c:
        assert c.execute("SELECT count(*) n FROM disposition_job_documents WHERE document_type='proposal_execution_report'").fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==3


@pytest.mark.parametrize('change',['external_version','missing_link','hidden_endpoint'])
def test_stale_or_hidden_relationships_fail_the_complete_plan_without_exposing_endpoints(client,change):
    with db() as c:
        job,root,mgr=manager(c);other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        link=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(kind,root,other)).fetchone()['id']
        proposed=create(c,root,'remove_aggregation_relationship',dict(relationship_id=link))
        if change=='external_version':
            child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(root,)).fetchone()['id']
            proposed=create(c,root,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=other,relationship_type_id=kind),target=child)
        pid=save(c,job,changes=[proposed,create(c,root)])['changes'][0]['id'];reach_manager(c,job,'standard')
        if change=='missing_link':c.execute('DELETE FROM aggregation_relationships WHERE id=%s',(link,))
        elif change=='external_version':
            c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(other,))
        else:
            level=c.execute("INSERT INTO security_levels(level_number,code,name) SELECT max(level_number)+1,%s,%s FROM security_levels RETURNING id",(uuid4().hex,uuid4().hex)).fetchone()['id']
            c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(level,other))
        before=data(c,root)
        with pytest.raises(psycopg.Error,match='disposition_proposal_requires_correction') as error:approve(c,job,mgr)
        assert str(pid) in error.value.diag.message_detail
        assert data(c,root)==before and not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()


def test_preview_checksums_are_identical_across_session_timezones(client):
    with db() as c:
        job,root,mgr=manager(c);save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard');t=task(c,job['id'])
        first=approval.preview(c,t['id'],mgr);c.execute("SET LOCAL timezone='UTC'")
        second=approval.preview(c,t['id'],mgr)
        assert second==first
        result=approve(c,job,mgr);assert result['remaining_units']==0


def test_manager_only_empty_result_can_start_another_round_without_replaying_executed_work(client):
    with db() as c:
        job,root,mgr=manager(c,'records_manager_only');pid=save(c,job,acting=mgr,changes=[create(c,root)])['changes'][0]['id']
        first=approve(c,job,mgr,overall_reason='First combined approval');assert first['review_round']==1
        other,*_=ready(c);admit(c,job['id'],[other]);save(c,job,acting=mgr,changes=[create(c,other)])
        second=approve(c,job,mgr,overall_reason='New combined approval');assert second['review_round']==2
        assert c.execute('SELECT version FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['version']==2
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects WHERE proposal_id=%s',(pid,)).fetchone()['n']==3
        assert len(c.execute('SELECT * FROM disposition_review_rounds WHERE approval_execution IS NOT NULL').fetchall())==2


def test_unclaimed_new_external_link_removes_only_the_proposal_affected_unit(client):
    with db() as c:
        job,root,mgr=manager(c);inside,*_=ready(c);outside,*_=ready(c);admit(c,job['id'],[inside])
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        save(c,job,changes=[create(c,root,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=outside,relationship_type_id=kind))]);reach_manager(c,job,'standard');out=approve(c,job,mgr)
        assert out['remaining_units']==1 and set(out['removed_units'])=={str(root)}
        assert c.execute("SELECT effect_type FROM disposition_proposal_effects WHERE effect_type IN ('unit_removed','cascading_unit_removed')").fetchone()['effect_type']=='unit_removed'


def test_concurrent_approval_has_one_execution_and_the_stale_caller_cannot_repeat_it(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with db() as c:
        job,root,mgr=manager(c);save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard');t=task(c,job['id']);p=approval.preview(c,t['id'],mgr);c.commit()
    barrier=Barrier(2)
    def run():
        with db() as c:
            actor(c);barrier.wait(timeout=10)
            try:return approval.approve(c,task_id=t['id'],expected_version=p['job_version'],task_version=p['task_version'],membership_token=p['membership_token'],proposals_token=p['proposals_token'],acting_role_id=mgr,command_id=uuid4())
            except psycopg.Error:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(lambda _:run(),range(2)))
    assert out.count('stale')==1
    with db() as c:
        assert c.execute('SELECT count(*) n FROM disposition_proposal_effects').fetchone()['n']==3
        assert c.execute("SELECT count(*) n FROM disposition_review_decisions WHERE review_stage='records_manager_review'").fetchone()['n']==1


def test_manager_only_nonempty_approved_job_requires_a_new_open_task_for_membership_changes(client):
    with db() as c:
        job,root,mgr=manager(c,'records_manager_only')
        out=approve(c,job,mgr,overall_reason='Approve existing complete membership')
        assert out['remaining_units']==1 and task(c,job['id']) is None
        another,*_=ready(c)
        denied=admit(c,job['id'],[another])
        assert denied['items'][0]['success'] is False and denied['items'][0]['code']=='disposition_membership_stage_invalid'
        from backend.services.api.disposition import queries
        from backend.services.api.tests.test_disposition_membership import remove
        assert queries.job(c,job['id'])['membership_editable'] is False
        with pytest.raises(psycopg.Error,match='disposition_membership_stage_invalid'):remove(c,root)
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==6


def test_manager_only_report_uses_actual_manager_duty_label(client):
    from io import BytesIO
    from zipfile import ZipFile
    from backend.services.api.disposition import documents
    with db() as c:
        job,root,mgr=manager(c,'records_manager_only');save(c,job,acting=mgr,changes=[create(c,root)])
        out=approve(c,job,mgr,overall_reason='Manager combined approval')
        row=approval.execution(c,job['id'],out['round_id'],mgr);snapshot=approval.report_snapshot(row)
        filled=documents.engine.fill(documents.default('proposal_execution_report')['content'],'proposal_execution_report',snapshot,104857600)
        with ZipFile(BytesIO(filled)) as archive:xml=archive.read('word/document.xml').decode()
        assert 'Assigned Records Manager' in xml and 'Assigned Records Officer' not in xml
        assert 'مدير الوثائق المكلّف' in xml
        from backend.services.api.application_settings import load_snapshot
        from pathlib import Path
        pdf,_=documents.engine.render(documents.default('proposal_execution_report')['content'],'proposal_execution_report',snapshot,load_snapshot(c))
        Path('/private/tmp/phase15-manager-only-report.pdf').write_bytes(pdf)


def test_immutable_effects_approval_and_bounded_effect_projection(client):
    from backend.services.api.tests.test_disposition_foundation import command
    with db() as c:
        job,root,mgr=manager(c);save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard');out=approve(c,job,mgr)
        first=approval.effects(c,job['id'],limit=1,offset=0);second=approval.effects(c,job['id'],limit=1,offset=1)
        assert first['total']==3 and first['items'][0]['id']!=second['items'][0]['id']
        with pytest.raises(psycopg.Error):command(c,'review_decide',lambda x:x.execute('DELETE FROM disposition_proposal_effects'))
        with pytest.raises(psycopg.Error):command(c,'review_decide',lambda x:x.execute("UPDATE disposition_review_rounds SET approval_execution='{}' WHERE id=%s",(out['round_id'],)))
        assert not c.execute('SELECT 1 FROM disposition_private.approval_context').fetchone()


def test_report_failure_audit_is_surfaced_if_it_cannot_be_written(client,monkeypatch):
    from backend.services.api.disposition import routes
    from contextlib import contextmanager
    from fastapi import HTTPException
    def broken():raise RuntimeError('Synthetic audit connection failure');yield
    monkeypatch.setattr(routes,'get_connection',broken)
    with pytest.raises(HTTPException) as error:routes._execution_report_after_commit(1,1,1)
    assert error.value.status_code==503 and error.value.detail['approval_committed'] is True
    assert error.value.detail['code']=='disposition_report_failure_audit_unavailable'


def test_committed_execution_report_can_be_retried_after_job_termination(client):
    from backend.services.api.tests.test_disposition_artifacts import configure,root as report_root
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.disposition import membership
    from backend.services.api.tests.test_disposition_membership import kwargs
    with db() as c:
        job,root,mgr=manager(c);configure(c);report_root(c);save(c,job,changes=[create(c,root)]);reach_manager(c,job,'standard')
        out=approve(c,job,mgr);c.commit();actor(c)
        membership.terminate_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True));c.commit();actor(c)
        saved=approval.generate_report(c,job_id=job['id'],round_id=out['round_id'],acting_role_id=mgr,settings=load_snapshot(c),connection_factory=db)
        assert saved['id'] and c.execute('SELECT lifecycle_state FROM disposition_jobs').fetchone()['lifecycle_state']=='terminated'
        assert c.execute('SELECT version FROM disposition_review_proposals').fetchone()['version']==2


@pytest.mark.parametrize('existing',[False,True])
def test_symmetric_links_cannot_create_duplicate_or_create_remove_conflicts(client,existing):
    with db() as c:
        job,root,mgr=manager(c,'simplified');other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active AND is_symmetric LIMIT 1").fetchone()['id']
        if existing:
            link=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(kind,root,other)).fetchone()['id']
            second=create(c,root,'remove_aggregation_relationship',dict(relationship_id=link))
        else:second=create(c,root,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=other,relationship_type_id=kind))
        first=create(c,root,'create_aggregation_relationship',dict(direction='incoming',related_aggregation_id=other,relationship_type_id=kind))
        save(c,job,changes=[first,second]);reach_manager(c,job,'simplified');before=data(c,root)
        with pytest.raises(psycopg.Error,match='disposition_proposal_(conflict|requires_correction)'):approve(c,job,mgr)
        assert data(c,root)==before and not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()


@pytest.mark.parametrize('route,reason,marked,code',[
 ('records_manager_only',None,False,'disposition_submission_reason_required'),
 ('records_manager_only',' \n\t',False,'disposition_submission_reason_required'),
 ('records_manager_only','Complete preparation',True,'disposition_marked_removals_require_correction'),
 ('simplified',None,True,'disposition_marked_removals_require_rejection')])
def test_combined_reason_and_removal_marks_block_approval_without_advancing(client,route,reason,marked,code):
    with db() as c:
        job,root,mgr=manager(c,route);reach_manager(c,job,route)
        if marked:save(c,job,acting=mgr,changes=[create(c,root,'remove_from_job',reason='Retain the complete unit')])
        before=data(c,root);t=task(c,job['id'])
        with pytest.raises(psycopg.Error,match=code):approve(c,job,mgr,overall_reason=reason)
        assert data(c,root)==before and task(c,job['id'])['id']==t['id']
        assert not c.execute('SELECT 1 FROM disposition_proposal_effects').fetchone()


def test_identical_vital_proposals_preserve_both_results_without_false_mutation_events(client):
    with db() as c:
        job,root,mgr=manager(c);save(c,job,changes=[create(c,root),create(c,root)]);reach_manager(c,job,'standard');approve(c,job,mgr)
        proposals=c.execute('SELECT * FROM disposition_review_proposals ORDER BY id').fetchall()
        assert all(p['proposal_state']=='executed' for p in proposals)
        assert [p['execution_message']['resource_changed'] for p in proposals]==[True,False]
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='VITAL_STATUS_CHANGED'").fetchone()['n']==1


def test_new_inactive_hold_does_not_make_an_independent_blocker_a_proposal_removal(client):
    with db() as c:
        job,root,mgr=manager(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)");c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        h=c.execute("INSERT INTO holds(code,name,valid_from,owner_user_id) VALUES('FUTURE-HOLD','Future legal hold',CURRENT_TIMESTAMP+interval '30 days',1) RETURNING id").fetchone()['id']
        save(c,job,changes=[create(c,root,'add_to_holds',dict(hold_ids=[h]))]);reach_manager(c,job,'standard');out=approve(c,job,mgr)
        assert out['remaining_units']==1 and not out['removed_units']
        assert c.execute('SELECT 1 FROM hold_aggregation_assignments WHERE hold_id=%s',(h,)).fetchone()
        assert not c.execute('SELECT 1 FROM disposition_proposal_holds').fetchone()
