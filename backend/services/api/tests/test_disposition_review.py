"""Phase 14 proposals, atomic Save, review decisions and permanent history."""
from copy import deepcopy
from uuid import uuid4
import json

import psycopg
import pytest

from backend.services.api.disposition import proposals as service, membership,workflow
from backend.services.api.tests.test_disposition_workflow import seeded,task,role,person,set_route,act
from backend.services.api.tests.test_disposition_membership import db,actor,setup,ready,admit,job_version,remove,kwargs
from backend.services.api.tests.test_disposition_foundation import version,command


def officer(c):return c.execute("SELECT id FROM roles WHERE code='fixture-records-officer'").fetchone()['id']


def save(c,job,*,changes=None,acting=None,**fields):
    t=task(c,job['id']);roleid=acting or (t['destination_role_id'] if t['destination_role_id'] else officer(c))
    return service.save(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],changes=changes or [],acting_role_id=roleid,command_id=uuid4(),**fields)


def create(c,root,kind='make_vital',values=None,target=None,record=None,reason=None):
    return dict(action='create',governing_root_id=root,target_aggregation_id=target or root,
      target_record_id=record,target_version=c.execute('SELECT version FROM records WHERE id=%s',(record,)).fetchone()['version'] if record else version(c,target or root),
      proposal_type=kind,proposed_values=values or {},reason=reason)


def submit(c,job,reason='Review the complete destruction job'):
    t=task(c,job['id'])
    return service.submit(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],
      overall_reason=reason,acting_role_id=officer(c),command_id=uuid4())


def claim(c,job):
    t=task(c,job['id'])
    if t['task_state']=='claimed':
        assert t['claimed_by_user_id']==c.execute('SELECT current_user_id() id').fetchone()['id']
        return t
    return act(c,t,'claim',t['destination_role_id'])


def decide(c,job,decision='approved',reason=''):
    t=task(c,job['id'])
    return service.decide(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],decision=decision,decision_reason=reason,acting_role_id=t['destination_role_id'],command_id=uuid4())


def data(c,root):
    return {'aggregations':c.execute('SELECT to_jsonb(a) item FROM aggregations a ORDER BY id').fetchall(),
      'records':c.execute('SELECT to_jsonb(a) item FROM records a ORDER BY id').fetchall(),
      'holds':c.execute('SELECT to_jsonb(a) item FROM hold_aggregation_assignments a ORDER BY id').fetchall(),
      'links':c.execute('SELECT to_jsonb(a) item FROM aggregation_relationships a ORDER BY id').fetchall(),
      'rules':c.execute('SELECT to_jsonb(a) item FROM aggregation_retention_rules a ORDER BY id').fetchall(),
      'memberships':c.execute('SELECT to_jsonb(a) item FROM disposition_job_memberships a ORDER BY id').fetchall()}


def payloads(c,root):
    child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(root,)).fetchone()['id']
    leaf=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(child,)).fetchone()['id']
    recordid=c.execute('SELECT id FROM records WHERE aggregation_id=%s',(leaf,)).fetchone()['id']
    other,*_=ready(c)
    otherrecord=c.execute('SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s))',(other,)).fetchone()['id']
    level=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,%s,true FROM security_levels RETURNING id",('P14-'+uuid4().hex,'Review blocking '+uuid4().hex)).fetchone()['id']
    holds=[c.execute("INSERT INTO holds(code,name,valid_from,owner_user_id) VALUES(%s,'Review hold',CURRENT_TIMESTAMP,1) RETURNING id",(uuid4().hex,)).fetchone()['id'] for _ in range(2)]
    aggtype=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active ORDER BY id LIMIT 1").fetchone()['id']
    rectype=c.execute("SELECT id FROM relationship_types WHERE resource_kind='record' AND is_active ORDER BY id LIMIT 1").fetchone()['id']
    aggrel=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(aggtype,child,other)).fetchone()['id']
    recrel=c.execute('INSERT INTO record_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(rectype,recordid,otherrecord)).fetchone()['id']
    return [create(c,root,'remove_from_job',reason='Retain this whole unit'),create(c,root,target=child),
      create(c,root,'blocking_security',{'security_level_id':level},target=child),
      create(c,root,'add_to_holds',{'hold_ids':holds},target=child),
      create(c,root,'create_aggregation_relationship',{'relationship_type_id':aggtype,'related_aggregation_id':other,'direction':'incoming'},target=child),
      create(c,root,'remove_aggregation_relationship',{'relationship_id':aggrel},target=child),
      create(c,root,'remove_record_relationship',{'relationship_id':recrel},target=leaf,record=recordid),
      create(c,root,'local_retention_override',{'current_period_years':6,'intermediate_period_years':2,'final_disposition':'selective_preservation','instructions':None})]


def test_all_types_save_atomically_without_resource_membership_or_stage_changes(client):
    with db() as c:
        job,root,*_=seeded(c);changes=payloads(c,root);before=data(c,root)
        result=save(c,job,changes=changes,review_notes='مرحلة المراجعة / Review observations',note_version=0,overall_reason='Partly entered')
        assert len(result['changes'])==8 and result['note_version']==1
        assert data(c,root)==before
        assert task(c,job['id'])['workflow_stage']=='officer_preparation'
        assert not c.execute('SELECT 1 FROM disposition_review_rounds').fetchone()
        assert c.execute('SELECT count(*) n FROM disposition_proposal_holds').fetchone()['n']==2
        work=service.work(c,result['task_id']);assert work['overall_reason']=='Partly entered' and work['own_notes']['review_notes'].startswith('مرحلة')
        stored=service.page(c,job['id'],limit=25,offset=0);assert stored['total']==8
        local=next(p for p in stored['items'] if p['proposal_type']=='local_retention_override')
        assert local['current_values']['classification_rule']['rule_id'] and local['reason'] is None
        assert all(p['proposer_user_id']==1 and p['proposer_role_id']==officer(c) for p in stored['items'])


@pytest.mark.parametrize('bad',[('make_vital',{'security_level_id':1}),('blocking_security',{'security_level_id':1}),('blocking_security',{'security_level_id':None}),('add_to_holds',{'hold_ids':[]}),('add_to_holds',{'hold_ids':[1,1]}),('create_aggregation_relationship',{'relationship_type_id':1,'related_aggregation_id':1,'direction':None}),('local_retention_override',{'current_period_years':-1,'intermediate_period_years':0,'final_disposition':'destruction','instructions':None}),('local_retention_override',{'current_period_years':1,'intermediate_period_years':0,'final_disposition':None,'instructions':None})])
def test_invalid_type_payload_rolls_back_the_complete_save(client,bad):
    with db() as c:
        job,root,*_=seeded(c);before=job_version(c,job['id']);t=task(c,job['id'])
        with pytest.raises(psycopg.Error):save(c,job,changes=[create(c,root),create(c,root,bad[0],bad[1])],review_notes='Not persisted',note_version=0)
        assert not c.execute('SELECT 1 FROM disposition_review_proposals UNION ALL SELECT 1 FROM disposition_review_notes').fetchone()
        assert job_version(c,job['id'])==before and task(c,job['id'])['version']==t['version']


def test_removal_reason_mandatory_but_governance_and_save_overall_reasons_optional(client):
    with db() as c:
        job,root,*_=seeded(c)
        with pytest.raises(psycopg.Error,match='disposition_removal_reason_required'):save(c,job,changes=[create(c,root,'remove_from_job')])
        save(c,job,changes=[create(c,root)],overall_reason='')
        with pytest.raises(Exception,match='disposition_submission_reason_required'):submit(c,job,'   ')
        assert not c.execute('SELECT 1 FROM disposition_review_rounds').fetchone()


@pytest.mark.parametrize('route',['standard','simplified'])
def test_submit_saved_proposals_round_reason_claim_and_stage_decisions(client,route):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,route,fa=True)
        if route=='standard':
            other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa))
        saved=save(c,job,changes=[create(c,root)],review_notes='Officer notes',note_version=0)
        result=submit(c,job);assert result['review_round']==1
        r=c.execute('SELECT * FROM disposition_review_rounds').fetchone();assert r['submission_reason']=='Review the complete destruction job' and len(r['proposal_snapshot'])==1
        if route=='standard':
            with pytest.raises(psycopg.Error,match='disposition_task_claim_required'):save(c,job,review_notes='Unclaimed notes',note_version=0)
            claim(c,job);decide(c,job)
            assert task(c,job['id'])['workflow_stage']=='unit_manager_review'
            claim(c,job);decide(c,job)
        assert task(c,job['id'])['workflow_stage']=='records_manager_review'
        claim(c,job)
        with pytest.raises(psycopg.Error,match='disposition_proposal_execution_not_implemented'):decide(c,job)
        decide(c,job,'rejected','Resolve the conflicting active proposals')
        assert task(c,job['id'])['workflow_stage']=='officer_correction'
        assert c.execute('SELECT count(*) n FROM disposition_review_notes').fetchone()['n']==1
        assert not c.execute('SELECT is_vital FROM aggregations WHERE id=%s',(root,)).fetchone()['is_vital']


def test_successor_and_reviewers_revise_others_preserve_original_and_closed_history(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        first=save(c,job,changes=[create(c,root)]);pid=first['changes'][0]['id'];submit(c,job);claim(c,job)
        save(c,job,changes=[dict(action='revise',proposal_id=pid,expected_version=1,target_version=version(c,root),proposed_values={},reason='File Administrator clarification')])
        p=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()
        assert p['proposer_role_id']==officer(c) and p['last_revised_role_id']==fa and p['version']==2
        decide(c,job);claim(c,job)
        save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=2,reason=None)])
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['proposal_state']=='withdrawn'
        with pytest.raises(psycopg.Error,match='disposition_proposal_closed'):save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=3)])
        events=c.execute("SELECT count(*) n FROM event_history WHERE entity_type='disposition_review_proposal' AND entity_id=%s",(pid,)).fetchone()['n'];assert events==3


def test_marked_removal_blocks_approval_and_resubmission_until_actual_officer_removal(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);other,*_=ready(c);assert admit(c,job['id'],[other])['items'][0]['success']
        save(c,job,changes=[create(c,other)]);submit(c,job);claim(c,job)
        save(c,job,changes=[create(c,root,'remove_from_job',reason='Not for destruction')])
        decide(c,job);claim(c,job)
        with pytest.raises(psycopg.Error,match='disposition_marked_removals_require_rejection'):decide(c,job)
        decide(c,job,'rejected','Remove the marked aggregation before resubmission')
        with pytest.raises(psycopg.Error,match='disposition_marked_removals_require_correction'):submit(c,job)
        remove(c,root)
        second=submit(c,job,'Corrected batch, round two');assert second['review_round']==2
        ps=c.execute('SELECT * FROM disposition_review_proposals WHERE governing_root_id=%s ORDER BY id',(other,)).fetchall()
        assert len(ps)==2 and ps[1]['carried_from_proposal_id']==ps[0]['id'] and ps[1]['proposer_role_id']==ps[0]['proposer_role_id']
        assert c.execute('SELECT count(*) n FROM disposition_review_rounds').fetchone()['n']==2
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s',(root,)).fetchone()['disposition_status']==2


def test_multiple_relationship_removal_proposals_save_atomically_and_defer_removal():
    with db() as c:
        job,root,*_=seeded(c)
        first=next(x for x in payloads(c,root) if x['proposal_type']=='remove_aggregation_relationship')
        # A second exact relationship with a distinct endpoint.
        other,*_=ready(c)
        source=c.execute('SELECT * FROM aggregation_relationships WHERE id=%s',(first['proposed_values']['relationship_id'],)).fetchone()
        second_id=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(source['relationship_type_id'],source['source_id'],other)).fetchone()['id']
        second={**first,'proposed_values':{'relationship_id':second_id}}
        bad={**second,'target_version':-1}
        with pytest.raises(psycopg.Error),c.transaction():save(c,job,changes=[first,bad])
        assert not c.execute('SELECT 1 FROM disposition_review_proposals').fetchone()
        result=save(c,job,changes=[first,second])
        assert len(result['changes'])==2
        stored=service.page(c,job['id'],limit=25,offset=0)['items']
        assert {x['proposed_values']['relationship_id'] for x in stored}=={source['id'],second_id}
        assert c.execute('SELECT count(*) n FROM aggregation_relationships WHERE id=ANY(%s)',([source['id'],second_id],)).fetchone()['n']==2


def test_blank_rejection_comments_rejected_even_with_marked_removal(client):
    from fastapi import HTTPException
    from backend.services.api.disposition.commands import execute_command
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        submit(c,job);claim(c,job)
        save(c,job,changes=[create(c,root,'remove_from_job',reason='Not for destruction')])
        decide(c,job);claim(c,job)
        with pytest.raises(HTTPException) as error:decide(c,job,'rejected','  ')
        assert error.value.detail['code']=='disposition_decision_reason_required'
        t=task(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_decision_reason_required'),c.transaction():
            execute_command(c,command_id=uuid4(),operation='review_decide',payload={'task_id':t['id']},acting_role_id=t['destination_role_id'],reason='Return review',apply=lambda x:x.execute('SELECT disposition_private.decide_review_work(%s,%s,%s,%s,%s) result',(t['id'],job_version(c,job['id']),t['version'],'rejected','')).fetchone()['result'])
        assert task(c,job['id'])['id']==t['id']


@pytest.mark.parametrize('language,translated',[('en',False),('ar',True),('ar-AE',True),('fr',False)])
def test_proposal_and_workspace_names_use_saved_entity_translations(client,language,translated):
    from psycopg.types.json import Jsonb
    from backend.services.api.disposition import workspace
    with db() as c:
        job,root,*_=seeded(c)
        save(c,job,changes=[create(c,root)])
        original=service.page(c,job['id'],limit=25,offset=0)['items'][0]
        c.execute('UPDATE users SET translations=%s WHERE id=%s',(Jsonb({'ar':{'name':'مقدم المقترح'}}),original['proposer_user_id']))
        c.execute('UPDATE roles SET translations=%s WHERE id=%s',(Jsonb({'ar':{'name':'مسؤول الوثائق'}}),original['proposer_role_id']))
        row=service.page(c,job['id'],limit=25,offset=0,language_tag=language)['items'][0]
        assert row['proposer_name']==('مقدم المقترح' if translated else original['proposer_name'])
        assert row['proposer_role_name']==('مسؤول الوثائق' if translated else original['proposer_role_name'])
        assert not any(k.endswith('_translations') for k in row)
        view=workspace.read(c,job['id'],language_tag=language)
        if view['task']['destination_user_id']==original['proposer_user_id']:
            assert view['task']['direct_assignee']==row['proposer_name']
        assert not any(k.endswith('_translations') for k in view['task'])


@pytest.mark.parametrize('route,fa',[('standard',True),('standard',False),('simplified',False)])
def test_submission_confirmation_names_actual_shared_queues(client,route,fa):
    from psycopg.types.json import Jsonb
    with db() as c:
        job,root,um,faid,mgr=seeded(c,route,fa=fa)
        other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,faid or (um if route=='standard' else mgr)))
        result=submit(c,job)
        tasks=c.execute('SELECT destination_role_id FROM disposition_tasks WHERE job_id=%s AND workflow_stage=%s AND review_round=%s',(job['id'],result['workflow_stage'],result['review_round'])).fetchall()
        assert tasks
        for t in tasks:
            c.execute('UPDATE roles SET translations=%s WHERE id=%s',(Jsonb({'ar':{'name':'دور المراجعة'}}),t['destination_role_id']))
        recipients=service.submission_recipients(c,result,'ar')
        assert len(recipients)==len(tasks)
        assert all(r=={'kind':'role_queue','name':'دور المراجعة'} for r in recipients)
        assert all(r['name']!='دور المراجعة' for r in service.submission_recipients(c,result,'en'))


def test_hidden_related_resource_preserves_readable_proposal_target_before_claim(client):
    from backend.services.api.disposition import workspace
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        reviewer=person(c,'Target reader')
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(reviewer,fa))
        other,*_=ready(c)
        typ=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        link=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(typ,root,other)).fetchone()['id']
        save(c,job,changes=[create(c,root,'remove_aggregation_relationship',{'relationship_id':link})])
        # Only the related aggregation becomes unreadable to the reviewer.
        high=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,'Restricted related',false FROM security_levels RETURNING id",(uuid4().hex,)).fetchone()['id']
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,other))
        submit(c,job)
        actor(c,reviewer)
        assert c.execute('SELECT current_user_can_view_aggregation(%s) ok',(root,)).fetchone()['ok']
        assert not c.execute('SELECT current_user_can_view_aggregation(%s) ok',(other,)).fetchone()['ok']
        actions=workspace.read(c,job['id'])['actions']
        assert 'claim' in actions and 'propose' not in actions
        rows=service.page(c,job['id'],limit=25,offset=0)['items']
        assert len(rows)==1 and rows[0]['redacted']
        target=c.execute('SELECT aggregation_number,title FROM aggregations WHERE id=%s',(root,)).fetchone()
        assert rows[0]['target_summary']==dict(number=target['aggregation_number'],title=target['title'])
        assert rows[0]['partial'] and rows[0]['proposal_type']=='remove_aggregation_relationship'
        assert rows[0]['proposal_state']=='active' and rows[0]['proposer_name']
        assert rows[0]['review_round']==1 and rows[0]['proposed_at']
        assert not {'current_values','proposed_values','reason','relationship_source_label','relationship_target_label','execution_message'} & set(rows[0])
        with pytest.raises(psycopg.Error,match='disposition_task_claim_required'),c.transaction():
            workspace.targets(c,task(c,job['id'])['id'],acting_role_id=fa,root_id=root,kind='aggregations',selected=root)
        # A real File Administrator without IG management may inspect blockers.
        for resource in c.execute('SELECT id FROM disposition_private.unit_ids(%s) id',(root,)).fetchall():
            c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id) SELECT %s,'role',%s,id FROM permissions WHERE code='aggregation.view' ON CONFLICT DO NOTHING",(resource['id'],fa))
        c.execute("INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id) SELECT r.id,'role',%s,p.id FROM records r CROSS JOIN permissions p WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s)) AND p.code='record.view' ON CONFLICT DO NOTHING",(fa,root))
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=%s',(fa,))
        from backend.services.api.disposition import blockers
        assert not c.execute('SELECT disposition_private.can_manage() ok').fetchone()['ok']
        assert blockers.summary(c,root)['relationships_block_final']
        relationships=blockers.relationship_page(c,root,language_tag='ar')['items']
        assert len(relationships)==1
        relation=relationships[0]
        assert relation['source']==dict(number=target['aggregation_number'],title=target['title'])
        assert relation['target'] is None and relation['target_id'] is None
        assert relation['relationship_id'] is None and relation['redacted'] and relation['blocks_final']
        assert relation['relationship_label']
        outsider=person(c,'Unrelated reader');outsider_role=role(c,'unrelated-reader',user=outsider)
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=%s',(outsider_role,))
        actor(c,outsider)
        from fastapi import HTTPException
        with pytest.raises(HTTPException):blockers.summary(c,root)
        actor(c,reviewer)
        actor(c)
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        actor(c,reviewer)
        rows=service.page(c,job['id'],limit=25,offset=0)['items']
        assert len(rows)==1 and set(rows[0])=={'id','version','redacted'}
        assert rows[0]['redacted']
