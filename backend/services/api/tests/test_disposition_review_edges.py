"""Task ownership, saved-work recovery, retries and current proposal access."""
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from backend.services.api.disposition import proposals as service,queries,membership
from backend.services.api.tests.test_disposition_review import db,actor,seeded,task,role,person,officer,save,create,submit,claim,decide,data,job_version,version
from backend.services.api.tests.test_disposition_membership import kwargs,ready
from backend.services.api.tests.test_disposition_foundation import ensure_officer,command


@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
def test_every_route_restores_partial_work_and_manager_can_revise_others(client,route):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,route,fa=True)
        first=save(c,job,acting=mgr if route=='records_manager_only' else officer(c),changes=[create(c,root)],overall_reason='',review_notes='First draft',note_version=0)
        if route!='records_manager_only':
            submit(c,job)
            if route=='standard':
                claim(c,job);decide(c,job);claim(c,job);decide(c,job)
            claim(c,job)
        pid=first['changes'][0]['id'];t=task(c,job['id'])
        changed=save(c,job,acting=mgr,changes=[dict(action='revise',proposal_id=pid,expected_version=1,target_version=version(c,root),proposed_values={},reason=None)],review_notes='Manager draft',note_version=1 if route=='records_manager_only' else 0)
        assert c.execute('SELECT last_revised_role_id FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['last_revised_role_id']==mgr
        c.commit()
    with db() as c:
        actor(c);work=service.work(c,t['id'])
        assert work['own_notes']['review_notes']=='Manager draft' and work['task_version']==changed['task_version']
        assert work['task_state']==t['task_state']
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['proposal_state']=='active'
        assert not c.execute('SELECT is_vital FROM aggregations WHERE id=%s',(root,)).fetchone()['is_vital']


def test_successor_officer_has_own_notes_and_can_revise_predecessor_proposal(client):
    with db() as c:
        job,root,*_=seeded(c)
        first=save(c,job,changes=[create(c,root)],review_notes='Predecessor notes',note_version=0);pid=first['changes'][0]['id'];oldtask=task(c,job['id'])
        other=person(c);ensure_officer(c,other)
        membership.assign_job(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),assigned_user_id=other))
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'):
            save(c,job,changes=[create(c,root)])
        actor(c,other)
        save(c,job,changes=[dict(action='revise',proposal_id=pid,expected_version=1,target_version=version(c,root),proposed_values={},reason='Successor review')],review_notes='Successor notes',note_version=0)
        notes=service.notes(c,job['id'],limit=25,offset=0)['items'];assert {n['author_user_id'] for n in notes}=={1,other}
        p=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone();assert p['proposer_user_id']==1 and p['last_revised_by_user_id']==other
        # A forged SQL edit cannot adopt the predecessor's attributed note.
        oldnote=next(n for n in notes if n['author_user_id']==1)
        with pytest.raises(psycopg.Error,match='disposition_own_note_required'):
            command(c,'review_save',lambda x: x.execute('UPDATE disposition_review_notes SET review_notes=%s WHERE id=%s',('Forged',oldnote['id'])),role=officer(c),payload={'task_id':task(c,job['id'])['id']})
        assert c.execute('SELECT review_notes FROM disposition_review_notes WHERE id=%s',(oldnote['id'],)).fetchone()['review_notes']=='Predecessor notes'


def test_saved_work_is_atomic_versioned_retryable_and_historical(client):
    with db() as c:
        job,root,*_=seeded(c);t=task(c,job['id']);options=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],changes=[create(c,root)],review_notes='Version one',note_version=0,acting_role_id=officer(c),command_id=uuid4())
        result=service.save(c,**options);assert service.save(c,**options)==result
        with pytest.raises(psycopg.Error,match='disposition_stale_task'):
            service.save(c,**{**options,'command_id':uuid4()})
        pid=result['changes'][0]['id'];before=job_version(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_stale_notes'):
            save(c,job,changes=[dict(action='revise',proposal_id=pid,expected_version=1,target_version=version(c,root),proposed_values={},reason='Rolled back')],review_notes='Stale notes',note_version=0)
        assert job_version(c,job['id'])==before and c.execute('SELECT version FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['version']==1
        save(c,job,review_notes='Version two',note_version=1)
        history=queries.history(c,job['id'],limit=100,offset=0)['items']
        notes=[e for e in history if e['operation']=='REVIEW_NOTES_SAVED'];assert len(notes)==2
        assert any(e['metadata']['before'] and e['metadata']['before']['review_notes']=='Version one' and e['metadata']['after']['review_notes']=='Version two' for e in notes)
        with pytest.raises(psycopg.Error,match='disposition_stale_target'):
            save(c,job,changes=[{**create(c,root),'target_version':version(c,root)-1}])
        with pytest.raises(psycopg.Error,match='disposition_stale_proposal'):
            save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=99)])


def test_task_only_review_authority_and_claim_owner_are_rechecked(client):
    with db() as c:
        job,root,*_=seeded(c)
        limited=role(c,'task-review-only','FILE_ADMIN');other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,limited));c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=1',(limited,))
        submit(c,job);claim(c,job)
        actor(c,other)
        with pytest.raises(psycopg.Error,match='disposition_task_claim_required'):
            save(c,job,acting=limited,changes=[create(c,root)])
        actor(c);from backend.services.api.tests.test_disposition_workflow import act
        act(c,task(c,job['id']),'release',limited)
        actor(c,other);claim(c,job)
        save(c,job,acting=limited,changes=[create(c,root)])
        c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s',(other,limited))
        with pytest.raises(psycopg.Error):save(c,job,acting=limited,review_notes='Lost authority',note_version=0)


def test_root_scope_exact_relationship_identity_and_current_endpoint_access(client):
    with db() as c:
        job,root,*_=seeded(c);child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(root,)).fetchone()['id']
        other,*_=ready(c);kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        link=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(kind,root,other)).fetchone()['id']
        p=save(c,job,changes=[create(c,root,'remove_aggregation_relationship',{'relationship_id':link})])['changes'][0]
        facts=service.page(c,job['id'],limit=1,offset=0)['items'][0]['current_values']['relationship'];assert facts['id']==link and facts['source_id']==root and facts['target_id']==other and facts['direction']=='outgoing'
        with pytest.raises(psycopg.Error,match='disposition_proposal_payload_invalid'):
            save(c,job,changes=[create(c,root,'local_retention_override',{'current_period_years':1,'intermediate_period_years':2,'final_disposition':'destruction','instructions':None},target=child)])
        with pytest.raises(psycopg.Error):save(c,job,changes=[create(c,root,target=other)])
        c.execute('DELETE FROM aggregation_relationships WHERE id=%s',(link,))
        with pytest.raises(psycopg.Error,match='disposition_relationship_invalid'):submit(c,job)
        save(c,job,changes=[dict(action='withdraw',proposal_id=p['id'],expected_version=p['version'])]);submit(c,job)


def test_http_save_feedback_restore_pagination_reasons_and_no_implicit_transition(client):
    with db() as c:
        job,root,*_=seeded(c);t=task(c,job['id']);jv=job_version(c,job['id']);change=create(c,root);c.commit()
    path=f"/api/v1/disposition/tasks/{t['id']}";headers={'If-Match':str(jv),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    payload=dict(command_id=str(uuid4()),acting_role_id=officer_id(),task_version=t['version'],changes=[change],review_notes='Restored after navigation',note_version=0,overall_reason='')
    response=client.post(path+'/review-work',headers=headers,json=payload);assert response.status_code==200,response.text
    assert client.get(path+'/review-work').json()['own_notes']['review_notes']=='Restored after navigation'
    assert client.post(path+'/review-work',headers=headers,json={**payload,'command_id':str(uuid4())}).status_code==409
    restored=client.get(path+'/review-work').json();headers['If-Match']=str(restored['job_version'])
    blank=client.post(path+'/submit-review',headers=headers,json=dict(command_id=str(uuid4()),acting_role_id=payload['acting_role_id'],task_version=restored['task_version'],overall_reason=''));assert blank.status_code==422,blank.text
    base=f"/api/v1/disposition/jobs/{job['id']}"
    assert client.get(base+'/proposals',params={'limit':1}).json()['total']==1
    assert client.get(base+'/proposals',params={'limit':101}).status_code==422
    assert client.get(base+'/review-notes').json()['total']==1
    assert client.get(base+'/review-rounds').json()['total']==0
    assert client.get(base+'/review-decisions').json()['total']==0
    assert client.get(path+'/review-candidates/aggregations',params={'acting_role_id':payload['acting_role_id'],'query':'a'}).json()['items']==[]
    with db() as c:
        actor(c);assert not c.execute('SELECT 1 FROM disposition_review_rounds').fetchone();assert task(c,job['id'])['id']==t['id']


def officer_id():
    with db() as c:return officer(c)


def test_hidden_external_endpoint_redacts_proposals_and_round_history_but_allows_withdrawal(client):
    with db() as c:
        job,root,*_=seeded(c);other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        change=create(c,root,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=other,relationship_type_id=kind))
        pid=save(c,job,changes=[change])['changes'][0]['id'];submit(c,job);claim(c,job)
        level=c.execute("INSERT INTO security_levels(level_number,code,name) SELECT max(level_number)+1,%s,'Hidden external resource' FROM security_levels RETURNING id",('HIDDEN-'+uuid4().hex,)).fetchone()['id']
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(level,other));c.execute("SELECT set_config('app.security_level_change_authorized','',true)")
        assert c.execute('SELECT current_user_can_view_aggregation(%s) allowed',(other,)).fetchone()['allowed'] is False
        assert service.page(c,job['id'],limit=25,offset=0)['items']==[dict(id=pid,version=1,redacted=True)]
        assert service.rounds(c,job['id'],limit=25,offset=0)['items'][0]['redacted']
        history=queries.history(c,job['id'],limit=100,offset=0)['items'];event=next(e for e in history if e['operation']=='REVIEW_PROPOSAL_CREATED')
        assert event['metadata']=={'redacted':True,'reason':'resource_access_denied'}
        with pytest.raises(psycopg.Error,match='disposition_resource_access_required'):save(c,job,changes=[{**change,'action':'create'}])
        with pytest.raises(psycopg.Error,match='disposition_resource_access_required'):decide(c,job)
        save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=1)]);decide(c,job)


def test_rejection_remains_possible_after_member_reopens_and_old_approval_is_invalidated(client):
    with db() as c:
        job,root,*_=seeded(c);submit(c,job);claim(c,job)
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        with pytest.raises(psycopg.Error):decide(c,job)
        decide(c,job,'rejected','Reopened member requires correction')
        assert task(c,job['id'])['workflow_stage']=='officer_correction'
        assert service.rounds(c,job['id'],limit=25,offset=0,decisions=True)['items'][0]['decision']=='rejected'


@pytest.mark.parametrize('blank',['','   ','\n\t'])
def test_every_whitespace_only_removal_reason_is_rejected(client,blank):
    with db() as c:
        job,root,*_=seeded(c)
        with pytest.raises(psycopg.Error,match='disposition_removal_reason_required'):save(c,job,changes=[create(c,root,'remove_from_job',reason=blank)])


def test_deleted_holds_and_inactive_relationship_types_are_not_silently_omitted(client):
    with db() as c:
        job,root,*_=seeded(c)
        hold=c.execute("INSERT INTO holds(code,name,valid_from,owner_user_id) VALUES(%s,'Selected hold',CURRENT_TIMESTAMP,1) RETURNING id",(uuid4().hex,)).fetchone()['id']
        pid=save(c,job,changes=[create(c,root,'add_to_holds',dict(hold_ids=[hold]))])['changes'][0]['id']
        # An unapplied proposal adds no resource protection or hold-deletion blocker.
        c.execute('DELETE FROM holds WHERE id=%s',(hold,))
        with pytest.raises(psycopg.Error,match='disposition_hold_access_required'):submit(c,job)
        save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=1)])
        assert not c.execute('SELECT 1 FROM disposition_proposal_holds').fetchone()
        other,*_=ready(c);kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        c.execute('UPDATE relationship_types SET is_active=false WHERE id=%s',(kind,))
        with pytest.raises(psycopg.Error,match='disposition_relationship_type_invalid'):
            save(c,job,changes=[create(c,root,'create_aggregation_relationship',dict(direction='incoming',related_aggregation_id=other,relationship_type_id=kind))])
        c.execute('UPDATE relationship_types SET is_active=true WHERE id=%s',(kind,))


def test_direct_writes_cannot_execute_erase_or_move_proposal_or_advance_on_save(client):
    with db() as c:
        job,root,*_=seeded(c);p=save(c,job,changes=[create(c,root)])['changes'][0];t=task(c,job['id'])
        operations=[('UPDATE disposition_review_proposals SET executed_at=CURRENT_TIMESTAMP,proposal_state=\'executed\' WHERE id=%s',p['id']),
                    ('DELETE FROM disposition_review_proposals WHERE id=%s',p['id']),
                    ('UPDATE disposition_review_proposals SET proposer_user_id=999 WHERE id=%s',p['id']),
                    ("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",t['id'])]
        for query,identity in operations:
            with pytest.raises(psycopg.Error):
                command(c,'review_save',lambda x: x.execute(query,(identity,)),role=officer(c),payload={'task_id':t['id']})
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s',(p['id'],)).fetchone()['proposal_state']=='active'
        assert task(c,job['id'])['id']==t['id']


def test_concurrent_saves_have_one_winner_and_no_duplicate_proposal(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with db() as c:
        job,root,*_=seeded(c);t=task(c,job['id']);options=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],changes=[create(c,root)],acting_role_id=officer(c));c.commit()
    barrier=Barrier(2)
    def run():
        with db() as c:
            actor(c);barrier.wait(timeout=10)
            try:return service.save(c,**options,command_id=uuid4())
            except psycopg.errors.SerializationFailure:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
    assert results.count('stale')==1 and sum(isinstance(r,dict) for r in results)==1
    with db() as c:assert c.execute('SELECT count(*) n FROM disposition_review_proposals').fetchone()['n']==1


def test_real_proposal_pagination_and_bounded_selected_relationship_search(client):
    with db() as c:
        job,root,*_=seeded(c);save(c,job,changes=[create(c,root,reason=f'Proposal {i}') for i in range(60)])
        first=service.page(c,job['id'],limit=25,offset=0);second=service.page(c,job['id'],limit=25,offset=25)
        assert first['total']==second['total']==60 and len(first['items'])==len(second['items'])==25
        assert not {p['id'] for p in first['items']} & {p['id'] for p in second['items']}
        c.execute("INSERT INTO holds(code,name,valid_from,owner_user_id) SELECT 'PAGE-'||n,'Page hold '||n,CURRENT_TIMESTAMP,1 FROM generate_series(1,60) n")
        found=service.candidates(c,task(c,job['id'])['id'],acting_role_id=officer(c),kind='holds',query='Page')
        assert len(found['items'])==25
        selected=c.execute("SELECT id FROM holds WHERE code='PAGE-60'").fetchone()['id']
        assert service.candidates(c,task(c,job['id'])['id'],acting_role_id=officer(c),kind='holds',selected=selected)['items'][0]['id']==selected


@pytest.mark.parametrize('state',['withdrawn','executed','failed'])
def test_closed_and_execution_outcome_rows_are_not_editable(client,state):
    with db() as c:
        job,root,*_=seeded(c);pid=save(c,job,changes=[create(c,root)])['changes'][0]['id']
        if state=='withdrawn':save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=1)])
        else:
            # Only this disposable fixture simulates an outcome from Phase 15.
            # No production command can set an execution result in Phase 14.
            c.execute('ALTER TABLE disposition_review_proposals DISABLE TRIGGER disposition_proposal_guard')
            c.execute('UPDATE disposition_review_proposals SET proposal_state=%s,executed_at=CURRENT_TIMESTAMP,executed_by_user_id=1 WHERE id=%s',(state,pid))
            c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('SET CONSTRAINTS ALL DEFERRED')
            c.execute('ALTER TABLE disposition_review_proposals ENABLE TRIGGER disposition_proposal_guard')
        current=c.execute('SELECT version FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()['version']
        with pytest.raises(psycopg.Error,match='disposition_proposal_closed'):
            save(c,job,changes=[dict(action='revise',proposal_id=pid,expected_version=current,target_version=version(c,root),proposed_values={},reason=None)])


def test_http_submission_with_enabled_task_notifications_is_atomic_and_retryable(client,monkeypatch):
    from backend.services.api.tests.test_disposition_task_notifications import configure
    from backend.services.api.messaging import notification_registry as registry
    from backend.services.api.disposition import notifications
    monkeypatch.setattr(registry,'registry',registry.NotificationRegistry(registry.application_definitions()))
    with db() as c:
        configure(c);job,root,*_=seeded(c);t=task(c,job['id']);jv=job_version(c,job['id']);acting=officer(c)
        before=c.execute('SELECT count(*) n FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['n'];c.commit()
    path=f"/api/v1/disposition/tasks/{t['id']}/submit-review"
    payload=dict(command_id=str(uuid4()),acting_role_id=acting,task_version=t['version'],overall_reason='Complete submitted job')
    headers={'If-Match':str(jv),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    first=client.post(path,json=payload,headers=headers);assert first.status_code==200,first.text
    retry=client.post(path,json=payload,headers=headers);assert retry.status_code==200 and retry.json()==first.json(),retry.text
    with db() as c:
        assert c.execute('SELECT count(*) n FROM message_request_receipts WHERE producer_code=%s',(notifications.ASSIGNED,)).fetchone()['n']==before+1
        assert c.execute('SELECT count(*) n FROM disposition_review_rounds').fetchone()['n']==1


def test_security_candidates_open_bounded_dropdown_and_filter(client):
    with db() as c,c.transaction(force_rollback=True):
        job,*_=seeded(c)
        ids=[]
        for i in range(30):
            ids.append(c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,%s,true FROM security_levels RETURNING id",(f'PICK{i:02}',f'Picker {i:02}')).fetchone()['id'])
        tid=task(c,job['id'])['id'];acting=officer(c)
        found=service.candidates(c,tid,acting_role_id=acting,kind='security_levels')
        assert len(found['items'])==25
        assert service.candidates(c,tid,acting_role_id=acting,kind='security_levels',query='PICK29')['items'][0]['id']==ids[-1]
        assert service.candidates(c,tid,acting_role_id=acting,kind='security_levels',selected=ids[-1])['items'][0]['id']==ids[-1]
        assert service.candidates(c,tid,acting_role_id=acting,kind='holds',query='')['items']==[]
        types=service.candidates(c,tid,acting_role_id=acting,kind='relationship_types')['items']
        assert 0<len(types)<=25
        assert service.candidates(c,tid,acting_role_id=acting,kind='relationship_types',selected=types[0]['id'])['items'][0]==types[0]


def test_relationship_candidate_direction_and_localized_search(client):
    with db() as c,c.transaction(force_rollback=True):
        job,*_=seeded(c)
        tid=task(c,job['id'])['id'];acting=officer(c)
        rid=c.execute("""INSERT INTO relationship_types(resource_kind,code,forward_name,reverse_name,is_symmetric,translations)
          VALUES ('aggregation','direction_test','Supersedes','Is superseded by',false,
          '{"ar":{"forward_name":"يحل محل","reverse_name":"يحل محله"}}') RETURNING id""").fetchone()['id']
        def get(**kw):return service.candidates(c,tid,acting_role_id=acting,kind='relationship_types',**kw)['items']
        assert get(selected=rid)[0]['name']=='Supersedes'
        assert get(selected=rid,direction='incoming')[0]['name']=='Is superseded by'
        assert get(selected=rid,direction='incoming',language_tag='ar')[0]['name']=='يحل محله'
        assert get(query='يحل محله',direction='incoming',language_tag='ar')[0]['id']==rid
        assert not get(query='يحل محله',direction='outgoing',language_tag='ar')
        rid=c.execute("""INSERT INTO relationship_types(resource_kind,code,forward_name,reverse_name,is_symmetric,translations) VALUES ('aggregation','symmetric_test','Related to','Related to',true,'{"ar":{"forward_name":"مرتبط بـ","reverse_name":"مرتبط بـ"}}') RETURNING id""").fetchone()['id']
        assert get(selected=rid,direction='incoming')[0]['name']=='Related to'
