"""Current task authority and bounded Phase 16 workspace projections."""
import pytest
from fastapi import HTTPException
from backend.services.api.disposition import workspace,workflow,proposals
from backend.services.api.tests.test_disposition_membership import db,actor
from backend.services.api.tests.test_disposition_workflow import seeded,task,act,person,role
from backend.services.api.tests.test_disposition_review import submit


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_direct_task_actions_and_selected_scope(client,route):
    with db() as c:
        job,root,*_=seeded(c,route)
        view=workspace.read(c,job['id'])
        assert set(view['actions'])=={'save','propose','approve' if route=='records_manager_only' else 'submit'}
        t=view['task'];acting=view['roles'][0]['id']
        assert workspace.targets(c,t['id'],acting_role_id=acting,root_id=root,kind='aggregations',query='x')['items']==[]
        selected=workspace.targets(c,t['id'],acting_role_id=acting,root_id=root,kind='aggregations',selected=root)['items']
        assert selected[0]['id']==root and selected[0]['version']
        assert view['job']['membership_editable']


def test_queue_claim_gates_and_task_only_reviewer(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        reviewer=person(c,'Task-only File Administrator')
        limited=role(c,'limited-fa','FILE_ADMIN',user=reviewer)
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(limited,))
        submit(c,job)
        actor(c,reviewer)
        view=workspace.read(c,job['id'])
        assert view['actions']==['claim'] and view['roles']==[{'id':limited,'name':'limited-fa'}]
        assert not view['job']['assignment_editable'] and not view['job']['membership_editable'] and not view['job']['owner_editable']
        t=view['task'];act(c,t,'claim',limited)
        view=workspace.read(c,job['id'],t['id'])
        assert set(view['actions'])=={'save','propose','complete_review','release','reassign'}
        other=person(c,'Other reviewer')
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,limited));actor(c,other)
        assert workspace.read(c,job['id'])['actions']==[]
        assert workflow.tasks(c,limit=10,offset=0)['items'][0]['claimant']=='Task-only File Administrator'
        with pytest.raises(HTTPException):workspace.read(c,job['id'],999999)


def test_task_filters_and_stable_pagination(client):
    with db() as c:
        job,root,*_=seeded(c)
        first=workflow.tasks(c,limit=1,offset=0,query=job['job_number'])
        assert first['total']==1 and len(first['items'])==1
        assert workflow.tasks(c,limit=1,offset=1,query=job['job_number'])['items']==[]
        assert workflow.tasks(c,limit=10,offset=0,stage='records_manager_review')['total']==0
        assert workflow.tasks(c,limit=10,offset=0,task_type='preparation')['total']==1


def test_review_attribution_compact_rounds_and_revision_history(client):
    from backend.services.api.tests.test_disposition_review import save,create,officer
    with db() as c:
        job,root,*_=seeded(c,'simplified')
        saved=save(c,job,changes=[create(c,root)],review_notes='Attributed observations',note_version=0)
        row=proposals.page(c,job['id'],limit=1,offset=0)['items'][0]
        assert row['proposer_name'] and row['proposer_role_name'] and row['current_security_name']
        assert row['current_values']['aggregation_number']
        assert proposals.page(c,job['id'],limit=1,offset=0,root_id=root+1000)['total']==0
        note=proposals.notes(c,job['id'],limit=1,offset=0)['items'][0]
        assert note['author_name'] and note['role_name'] and note['review_notes']=='Attributed observations'
        save(c,job,review_notes='Revised observations',note_version=note['version'])
        history=workspace.review_history(c,job['id'],kind='note',identity=note['id'],limit=1,offset=0)
        assert history['total']==2 and len(history['items'])==1
        assert history['items'][0]['metadata']['after']['review_notes']=='Revised observations'
        assert workspace.review_history(c,job['id'],kind='proposal',identity=row['id'],limit=1,offset=0)['total']>=1
        submit(c,job)
        compact=proposals.rounds(c,job['id'],limit=1,offset=0,summary=True)['items'][0]
        assert compact['root_count']==1 and 'membership_snapshot' not in compact and 'approval_execution' not in compact and not compact['approved']
        assert workspace.read(c,job['id'],saved['task_id'])['actions']==[]


def test_reassignment_candidates_scope_and_current_indicator_filters(client):
    from backend.services.api.tests.test_disposition_review import save,create
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        fa=role(c,'handover-file-admin','FILE_ADMIN')
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(fa,))
        save(c,job,changes=[create(c,root,'remove_from_job',reason='Do not destroy this unit')])
        listed=workflow.tasks(c,limit=1,offset=0,indicator='removal_required',min_priority=0,min_roots=1,has_claimant=False)
        assert listed['total']==1 and listed['items'][0]['action_removal_required']
        assert workspace.read(c,job['id'])['job']['action_required']['removal_required']
        assert workflow.tasks(c,limit=1,offset=0,min_roots=2)['total']==0
        # Resolve the mark before valid submission; Save keeps it as history.
        p=proposals.page(c,job['id'],limit=1,offset=0)['items'][0]
        save(c,job,changes=[{'action':'withdraw','proposal_id':p['id'],'expected_version':p['version']}])
        submit(c,job);t=task(c,job['id']);act(c,t,'claim',fa)
        other=person(c,'Eligible handover colleague')
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa))
        assert workspace.assignment_candidates(c,t['id'],acting_role_id=fa,kind='users',query='E')['items']==[]
        rows=workspace.assignment_candidates(c,t['id'],acting_role_id=fa,kind='users',selected=other)['items']
        assert rows[0]['id']==other
        assert workspace.assignment_candidates(c,t['id'],acting_role_id=fa,kind='roles',selected=fa)['items'][0]['id']==fa
        act(c,task(c,job['id']),'release',fa)
        # A global manager can recover the queue; an unclaimed task-only actor cannot.
        actor(c,other)
        with pytest.raises(HTTPException):workspace.assignment_candidates(c,t['id'],acting_role_id=fa,kind='users',selected=other)


def test_task_notification_has_current_authorized_workspace_link(client,monkeypatch):
    from backend.services.api.tests.test_disposition_task_notifications import configure
    from backend.services.api.messaging import notification_registry as registry,reading
    from backend.services.api.tests.test_disposition_membership import setup
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c);job=setup(c)
        inbox=reading.inbox(c,1,25)
        delivery=inbox['items'][0]['id']
        detail=reading.delivery(c,1,delivery)
        assert detail['disposition_task']=={'task_id':task(c,job['id'])['id'],'job_id':job['id']}
        assert 'disposition_task' not in inbox['items'][0]


@pytest.mark.parametrize('route,fa_stage',[('standard',True),('standard',False),('simplified',False)])
def test_committed_claim_preserves_timestamp_when_saving_in_a_new_transaction(client,route,fa_stage):
    from uuid import uuid4
    from backend.services.api.tests.test_disposition_review import save,create
    with db() as c:
        job,root,um,fa,mgr=seeded(c,route,fa=fa_stage)
        created=save(c,job,changes=[create(c,root)])['changes'][0]
        submit(c,job);t=task(c,job['id'])
        person_id=person(c,'Committed claimant')
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(person_id,t['destination_role_id']))
        actor(c,person_id);act(c,t,'claim',t['destination_role_id']);claimed=task(c,job['id']);c.commit()
    with db() as c:
        actor(c,person_id);work=proposals.work(c,claimed['id'])
        assert c.execute('SELECT CURRENT_TIMESTAMP AS now').fetchone()['now']>claimed['claimed_at']
        root_version=c.execute('SELECT version FROM aggregations WHERE id=%s',(root,)).fetchone()['version']
        proposals.save(c,task_id=claimed['id'],expected_version=work['job_version'],task_version=work['task_version'],
            changes=[{'action':'revise','proposal_id':created['id'],'expected_version':created['version'],'target_version':root_version,'proposed_values':{},'reason':'Reviewed by the current claimant'}],
            review_notes='Work saved after a committed claim',note_version=0,acting_role_id=claimed['destination_role_id'],command_id=uuid4())
        after=task(c,job['id']);assert after['claimed_at']==claimed['claimed_at'] and after['claimed_by_user_id']==person_id and after['task_state']=='claimed'
        row=proposals.page(c,job['id'],limit=1,offset=0)['items'][0]
        assert row['proposer_user_id']==1 and row['last_revised_by_user_id']==person_id and row['editor_name']=='Committed claimant'
