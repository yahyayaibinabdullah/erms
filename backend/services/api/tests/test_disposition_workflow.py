"""Phase 13 routing/task acceptance. Disposable database runner only."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from backend.services.api.disposition import membership, workflow
from backend.services.api.disposition.commands import execute_command
from backend.services.api.disposition.eligibility import worker_actor
from backend.services.api.tests.test_disposition_membership import db, actor, setup, ready, admit, job_version, kwargs, remove


def role(c, code, profile='ALL_PRIVS', owner=1, user=1):
    if profile in ('FILE_ADMIN','READ_ONLY') and not c.execute('SELECT 1 FROM profiles WHERE code=%s',(profile,)).fetchone():
        pid=c.execute('INSERT INTO profiles(code,name) VALUES(%s,%s) RETURNING id',(profile,profile)).fetchone()['id']
        if profile=='FILE_ADMIN':c.execute("INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges WHERE code<>'disposition.jobs.manage'",(pid,))
    identity=c.execute('''INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance)
      SELECT %s,%s,%s,id,%s FROM profiles WHERE code=%s RETURNING id''',
      (owner,code,code,profile in ('INFO_GOV_MGR','INFO_GOV_OFFICER','ALL_PRIVS','FILE_ADMIN'),profile)).fetchone()['id']
    if user:
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,identity))
    return identity


def person(c, name='Other reviewer'):
    return c.execute("INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",(name,str(uuid4())+'@test.invalid')).fetchone()['id']


def set_route(c, route):
    c.execute("SELECT apply_application_settings(%s,%s)", ('[{"key":"DISPOSITION_DESTRUCTION_REVIEW_ROUTE","value":"'+route+'","expected_version":'+str(c.execute("SELECT version FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REVIEW_ROUTE'").fetchone()['version'])+'}]','Phase 13 route policy'))


def submit(c, job):
    return execute_command(c,**kwargs(operation='review_submit',payload={'job_id':job},apply=lambda x: workflow.start_review(x,job_id=job,expected_version=job_version(x,job))))


def seeded(c,route='standard',fa=False,manager=True):
    actor(c)
    if route!='standard':set_route(c,route)
    mgr=role(c,'records-manager','INFO_GOV_MGR') if manager else None
    if route=='records_manager_only':
        job=membership.create_job(c,**kwargs(job_number=str(uuid4()),job_type='destruction',owning_org_unit_id=1,assigned_user_id=1))
    else:job=setup(c)
    um=role(c,'unit-manager')
    c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=1',(um,))
    faid=role(c,'file-admin') if fa else None
    if faid:c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(faid,))
    root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success']
    return job,root,um,faid,mgr


def task(c,job,stage=None):
    return c.execute("SELECT * FROM disposition_tasks WHERE job_id=%s AND task_state IN ('open','claimed') ORDER BY id DESC LIMIT 1",(job,)).fetchone()


def act(c,t,action,roleid,user=None,**extra):
    return workflow.task_command(c,task_id=t['id'],expected_version=t['version'],action=action,
      **{**kwargs(), 'acting_role_id':roleid},**({'assigned_user_id':user} if action=='reassign' else {}),**extra)


@pytest.mark.parametrize('route,stage',[('standard','unit_manager_review'),('simplified','records_manager_review')])
def test_capture_route_direct_preparation_and_saved_route_round(client,route,stage):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,route)
        first=task(c,job['id']); assert first['destination_user_id']==1 and first['task_state']=='open'
        assert job['review_route']==route
        set_route(c,'simplified' if route=='standard' else 'standard')
        result=submit(c,job['id']); assert result['workflow_stage']==stage and result['review_round']==1
        assert result['file_administrator_skipped']==(route=='standard')
        assert c.execute('SELECT review_route FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['review_route']==route
        assert c.execute('SELECT task_state FROM disposition_tasks WHERE id=%s',(first['id'],)).fetchone()['task_state']=='cancelled'
        assert c.execute('SELECT membership_snapshot FROM disposition_review_rounds WHERE job_id=%s',(job['id'],)).fetchone()['membership_snapshot']


def test_nearest_configured_ancestor_and_source_unit_no_role_grant(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        child=c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('child','Child',1) RETURNING id").fetchone()['id']
        # Move the empty job owner first, then admit a descendant-owned unit.
        remove(c,root)
        c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        membership.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=child))
        c.execute("SELECT set_config('app.ownership_correction_authorized','authorized',true)");c.execute('UPDATE aggregations SET owning_org_unit_id=%s WHERE id=%s',(child,root));c.execute("SELECT set_config('app.ownership_correction_authorized','',true)")
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,))
        from backend.services.api.disposition.eligibility import evaluate_root
        worker_actor(c);evaluate_root(c,root);actor(c)
        assert admit(c,job['id'],[root])['items'][0]['success']
        childmgr=role(c,'child-manager',owner=child)
        c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=%s',(childmgr,child))
        out=submit(c,job['id']); assert out['workflow_stage']=='file_administrator_review' and out['routing_org_unit_id']==1
        t=task(c,job['id']);assert t['destination_role_id']==fa and t['routing_org_unit_id']==1
        assert c.execute('SELECT owning_org_unit_id FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['owning_org_unit_id']==child


@pytest.mark.parametrize('failure',['inactive','no_assignee','hidden'])
def test_explicit_unusable_file_admin_blocks_without_fallback(client,failure):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        top=c.execute("INSERT INTO org_units(code,name) VALUES('ancestor','Ancestor') RETURNING id").fetchone()['id']
        ancestor=role(c,'ancestor-admin',owner=top)
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s',(ancestor,top))
        c.execute('UPDATE org_units SET parent_org_unit_id=%s WHERE id=1',(top,))
        if failure=='inactive':c.execute("UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",(fa,))
        elif failure=='no_assignee':c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(fa,))
        else:
            # A real non-governor with no resource ACL cannot be made eligible by routing.
            other=person(c);role(c,'empty-read-only','READ_ONLY',user=None);c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(fa,))
            c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='READ_ONLY') WHERE id=%s",(fa,))
            c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa))
        before=job_version(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_reviewer_unavailable'):
            submit(c,job['id'])
        assert job_version(c,job['id'])==before
        assert not c.execute('SELECT 1 FROM disposition_review_rounds').fetchone()
        assert task(c,job['id'])['task_type']=='preparation'


@pytest.mark.parametrize('stage',['file_administrator_review','unit_manager_review'])
def test_task_only_reviewer_can_claim_but_cannot_create_or_terminate(client,stage):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        # Ordinary role with full resource access but no disposition privilege.
        viewer=role(c,'reviewer','FILE_ADMIN')
        other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,viewer))
        if stage=='file_administrator_review':c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(viewer,))
        else:c.execute('UPDATE org_units SET file_administrator_role_id=NULL,managing_role_id=%s WHERE id=1',(viewer,))
        submit(c,job['id']); t=task(c,job['id'])
        assert t['workflow_stage']==stage
        actor(c,other)
        assert c.execute('SELECT disposition_private.task_eligible(%s,%s,%s) yes',(other,t['id'],viewer)).fetchone()['yes']
        claimed=act(c,t,'claim',viewer);assert claimed['claimed_by_user_id']==other
        assert workflow.tasks(c,limit=1,offset=0)['total']==1
        with pytest.raises(psycopg.Error,match='disposition_authorization_required'):
            membership.terminate_job(c,**{**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True),'acting_role_id':viewer})


def test_release_reassign_role_loss_preserves_prior_claim_history(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        submit(c,job['id']); t=task(c,job['id'])
        claimed=act(c,t,'claim',fa)
        other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa))
        reassigned=act(c,claimed,'reassign',fa,other)
        assert reassigned['destination_role_id']==fa and reassigned['claimed_by_user_id']==other
        c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s',(other,fa))
        worker_actor(c);out=workflow.reconcile_claims(c);assert out['released']==[t['id']]
        assert task(c,job['id'])['claimed_by_user_id'] is None
        assert c.execute("SELECT count(*) n FROM event_history WHERE entity_type='disposition_task' AND entity_id=%s",(t['id'],)).fetchone()['n']>=4
        actor(c);current=task(c,job['id']);again=act(c,current,'claim',fa);released=act(c,again,'release',fa)
        assert released['task_state']=='open'


def test_correction_resolves_saved_route_again_and_owner_locked_after_empty(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        submit(c,job['id'])
        # Phase 14 owns actual decisions; exercise its private routing callback.
        execute_command(c,**kwargs(operation='review_decide',payload={'job_id':job['id']},apply=lambda x:(x.execute("UPDATE disposition_jobs SET workflow_stage='unit_manager_review' WHERE id=%s",(job['id'],)),workflow.route_correction(x,job_id=job['id']),{})[-1]))
        assert task(c,job['id'])['destination_user_id']==1
        remove(c,root)
        with pytest.raises(psycopg.Error,match='disposition_owning_unit_change_invalid'):
            membership.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=c.execute("INSERT INTO org_units(code,name) VALUES('new','New') RETURNING id").fetchone()['id']))
        assert admit(c,job['id'],[root])['items'][0]['success']
        c.execute('UPDATE org_units SET file_administrator_role_id=NULL WHERE id=1')
        assert submit(c,job['id'])['workflow_stage']=='unit_manager_review'
        assert c.execute('SELECT count(*) n FROM disposition_review_rounds').fetchone()['n']==2


def test_manager_only_no_officer_or_review_queues_and_immutable_route(client):
    with db() as c:
        actor(c);set_route(c,'records_manager_only');mgr=role(c,'only-manager','INFO_GOV_MGR')
        job=membership.create_job(c,**kwargs(job_number='Manager only',job_type='destruction',owning_org_unit_id=1,assigned_user_id=1))
        assert job['workflow_stage']=='manager_preparation' and task(c,job['id'])['destination_user_id']==1
        root,*_=ready(c);assert admit(c,job['id'],[root])['items'][0]['success']
        with pytest.raises(psycopg.Error,match='disposition_combined_approval_required'):submit(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_route_immutable'):
            execute_command(c,**kwargs(operation='job_assign',payload={},apply=lambda x: (x.execute("UPDATE disposition_jobs SET review_route='standard' WHERE id=%s",(job['id'],)),{})[1]))
        assert not c.execute('SELECT 1 FROM disposition_review_rounds').fetchone()


def test_simultaneous_claims_have_one_winner_and_exact_retry(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id']);t=task(c,job['id'])
        other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,fa));c.commit()
    keys={1:uuid4(),other:uuid4()}
    def claim(user):
        try:
            with db() as c:
                actor(c,user)
                return user,workflow.task_command(c,task_id=t['id'],expected_version=t['version'],action='claim',acting_role_id=fa,reason='Claim review',command_id=keys[user])
        except psycopg.Error as error:return user,error.sqlstate
    with ThreadPoolExecutor(2) as pool:out=list(pool.map(claim,[1,other]))
    winners=[r for r in out if isinstance(r[1],dict)];assert len(winners)==1
    winner,result=winners[0]
    with db() as c:
        actor(c,winner)
        assert workflow.task_command(c,task_id=t['id'],expected_version=t['version'],action='claim',acting_role_id=fa,reason='Claim review',command_id=keys[winner])==result
        with pytest.raises(psycopg.Error,match='disposition_command_conflict'):
            workflow.task_command(c,task_id=t['id'],expected_version=t['version'],action='claim',acting_role_id=fa,reason='Changed reason',command_id=keys[winner])


def test_same_person_officer_and_manager_actions_require_independent_current_roles(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'simplified')
        officer=c.execute("SELECT id FROM roles WHERE code='fixture-records-officer'").fetchone()['id']
        submit(c,job['id']);t=task(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'):
            act(c,t,'claim',officer)
        claimed=act(c,t,'claim',mgr)
        assert claimed['claimed_by_user_id']==job['assigned_user_id']==1
        c.execute('DELETE FROM user_role_assignments WHERE user_id=1 AND role_id=%s',(mgr,))
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'):
            execute_command(c,**{**kwargs(),'acting_role_id':officer},operation='task_complete',payload={'task_id':t['id']},apply=lambda x:(x.execute("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",(t['id'],)),{})[1])
        worker_actor(c);assert workflow.reconcile_claims(c)['released']==[t['id']]


@pytest.mark.parametrize('loss',['inactive_user','inactive_role','expired','profile_privilege','designation','clearance'])
def test_eligibility_loss_blocks_work_and_returns_queue_without_changing_round(client,loss):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'simplified')
        other=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,mgr))
        submit(c,job['id']);t=task(c,job['id']);actor(c,other);claimed=act(c,t,'claim',mgr)
        actor(c)
        before=c.execute('SELECT membership_snapshot FROM disposition_review_rounds').fetchone()['membership_snapshot']
        if loss=='inactive_user':c.execute('UPDATE users SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(other,))
        elif loss=='inactive_role':c.execute('UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(mgr,))
        elif loss=='expired':c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s',(other,mgr))
        elif loss=='profile_privilege':
            role(c,'no-task-privilege','READ_ONLY',user=None)
            c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='READ_ONLY') WHERE id=%s",(mgr,))
        elif loss=='designation':
            # Manager profile loss removes this role from the Manager queue.
            c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER') WHERE id=%s",(mgr,))
        else:
            high=c.execute("INSERT INTO security_levels(level_number,code,name,prevents_disposition) SELECT max(level_number)+1,%s,'Task clearance test',false FROM security_levels RETURNING id",('P13-'+uuid4().hex,)).fetchone()['id']
            c.execute('UPDATE roles SET security_level_id=%s WHERE id=1',(high,))
            c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,root))
        actor(c,other)
        with pytest.raises(psycopg.Error,match='disposition_task_ineligible'):
            execute_command(c,**{**kwargs(),'acting_role_id':mgr},operation='task_complete',payload={'task_id':t['id']},apply=lambda x:(x.execute("UPDATE disposition_tasks SET task_state='completed' WHERE id=%s",(t['id'],)),{})[1])
        worker_actor(c);assert workflow.reconcile_claims(c)['released']==[t['id']]
        current=task(c,job['id']);assert current['task_state']=='open' and current['destination_role_id']==mgr
        assert c.execute('SELECT membership_snapshot FROM disposition_review_rounds').fetchone()['membership_snapshot']==before


def test_task_api_reason_version_current_auth_and_no_generic_completion(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id']);t=task(c,job['id'])
    path=f"/api/v1/disposition/tasks/{t['id']}"
    data={'command_id':str(uuid4()),'acting_role_id':fa}
    headers={'X-CSRF-Token':client.cookies.get('erms_csrf'),'If-Match':str(t['version'])}
    assert client.post(path+'/claim',json=data,headers=headers).status_code==422
    headers['X-Change-Reason']='Take review responsibility'
    response=client.post(path+'/claim',json=data,headers=headers);assert response.status_code==200,response.text
    page=client.get('/api/v1/disposition/tasks',params={'limit':1,'offset':0});assert page.status_code==200 and len(page.json()['items'])==1
    assert client.get('/api/v1/disposition/tasks',params={'limit':101}).status_code==422
    assert client.post(path+'/complete',json=data,headers=headers).status_code==404
    assert client.post('/api/v1/disposition/jobs/'+str(job['id'])+'/submit',json=data,headers=headers).status_code==404
    data['command_id']=str(uuid4())
    assert client.post(path+'/release',json=data,headers=headers).status_code==409
    headers['If-Match']=str(response.json()['version'])
    assert client.post(path+'/release',json=data,headers=headers).status_code==200


def test_selector_follows_saved_job_route_after_global_policy_change(client):
    from backend.services.api.disposition import queries
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'standard')
        manager=person(c,'Only Manager');role(c,'another-manager','INFO_GOV_MGR',user=manager)
        set_route(c,'records_manager_only')
        assert not queries.selector(c,'assignees',selected=manager,job_id=job['id'])['items']
        assert queries.selector(c,'assignees',selected=manager)['items'][0]['id']==manager


def test_limited_reviewer_can_read_job_members_and_history_without_management(client):
    from backend.services.api.disposition import queries
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True)
        viewer=role(c,'limited-history','FILE_ADMIN');other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,viewer))
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(viewer,))
        submit(c,job['id']);actor(c,other)
        assert not c.execute('SELECT disposition_private.can_manage() yes').fetchone()['yes']
        assert queries.job(c,job['id'])['membership_editable'] is False
        assert queries.members(c,job['id'],limit=1,offset=0)['items'][0]['owning_org_unit_name']=='Test Root'
        assert queries.history(c,job['id'],limit=100,offset=0)['items']


def test_manager_only_combined_round_boundary_locks_owner_and_external_correction(client,monkeypatch):
    from backend.services.api.tests.test_disposition_external import generate,decision
    from backend.services.api.tests.test_disposition_artifacts import configure,root as destination_root
    from backend.services.api.tests.test_disposition_approval import approve
    from backend.services.api.disposition import documents
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *args:(preview_pdf(),{}))
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'records_manager_only')
        def boundary(x):
            n=x.execute('SELECT disposition_private.start_manager_round(%s,%s) n',(job['id'],job_version(x,job['id']))).fetchone()['n']
            return {'round':n}
        result=execute_command(c,**{**kwargs(),'acting_role_id':mgr},operation='review_decide',payload={'job_id':job['id']},apply=boundary)
        assert result['round']==1
        assert c.execute("SELECT count(*) n FROM disposition_tasks WHERE destination_role_id IS NOT NULL").fetchone()['n']==0
        remove(c,root)
        owner=c.execute("INSERT INTO org_units(code,name) VALUES('new-owner','New owner') RETURNING id").fetchone()['id']
        with pytest.raises(psycopg.Error,match='disposition_owning_unit_change_invalid'):
            membership.change_job_owner(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),owning_org_unit_id=owner))
        assert admit(c,job['id'],[root])['items'][0]['success']
        configure(c);destination_root(c)
        approved=approve(c,job,mgr,overall_reason='Approve the corrected Manager Only membership')
        generate(c,job,mgr,approved['round_id'])
        decision(c,job,outcome='rejected',notes='Authority correction for the assigned Manager',acting=mgr)
        assert task(c,job['id'])['workflow_stage']=='manager_correction'
        assert task(c,job['id'])['destination_user_id']==1


def test_authorized_management_can_return_and_retarget_obsolete_queue(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=True);submit(c,job['id']);t=task(c,job['id'])
        claimed=act(c,t,'claim',fa)
        replacement=role(c,'replacement-file-admin')
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=1',(replacement,))
        # Management authority recovers the old queue; no actor gains content ACLs.
        released=act(c,claimed,'release',1)
        retargeted=workflow.task_command(c,task_id=t['id'],expected_version=released['version'],action='reassign',
          destination_role_id=replacement,**kwargs())
        assert retargeted['task_state']=='open' and retargeted['destination_role_id']==replacement
        assert act(c,retargeted,'claim',replacement)['claimed_by_user_id']==1


def test_shared_claims_across_separate_manager_roles_still_have_one_claimant(client):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,'simplified')
        second=role(c,'second-manager-role','INFO_GOV_MGR')
        submit(c,job['id'])
        rows=c.execute("SELECT * FROM disposition_tasks WHERE job_id=%s AND task_state='open' ORDER BY id",(job['id'],)).fetchall()
        assert len(rows)==2
        act(c,rows[0],'claim',rows[0]['destination_role_id'])
        with pytest.raises(psycopg.Error,match='disposition_task_already_claimed'):
            act(c,rows[1],'claim',rows[1]['destination_role_id'])


def test_current_task_index_and_real_inbox_pagination_on_representative_history(client):
    import json
    with db() as c:
        setup(c)
        def populate(x):
            x.execute("""INSERT INTO disposition_jobs(job_number,job_type,workflow_stage,disposition_status,owning_org_unit_id,assigned_user_id,created_by_user_id)
              SELECT 'TASK-PAGE-'||n,'destruction','officer_preparation',6,1,1,1 FROM generate_series(1,200) n""")
            # Four cancelled tasks represent permanent earlier assignments;
            # each job retains exactly one actionable preparation task.
            x.execute("""INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,task_state,destination_user_id)
              SELECT j.id,'preparation','officer_preparation','cancelled',1 FROM disposition_jobs j CROSS JOIN generate_series(1,4)
              WHERE j.job_number LIKE 'TASK-PAGE-%'""")
            return {}
        execute_command(c,**kwargs(operation='job_create',payload={},apply=populate))
        c.execute('ANALYZE disposition_tasks')
        plan=c.execute("EXPLAIN (FORMAT JSON) SELECT id FROM disposition_tasks WHERE job_id=100 AND workflow_stage='officer_preparation' AND task_state IN ('open','claimed') ORDER BY id").fetchone()['QUERY PLAN']
        assert 'disposition_tasks_current_stage' in json.dumps(plan)
        first=workflow.tasks(c,limit=25,offset=0);second=workflow.tasks(c,limit=25,offset=25)
        assert first['total']==second['total']==201 and len(first['items'])==len(second['items'])==25
        assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
        assert all(r['task_state']=='open' for r in first['items']+second['items'])
        print('Representative plan:',json.dumps(plan,sort_keys=True))


@pytest.mark.parametrize('after_file_admin',[False,True])
@pytest.mark.parametrize('failure',['missing','inactive','unassigned'])
def test_unit_manager_requires_own_units_usable_designated_role_before_entering_stage(client,after_file_admin,failure):
    with db() as c:
        job,root,um,fa,mgr=seeded(c,fa=after_file_admin)
        if after_file_admin:
            submit(c,job['id']);t=task(c,job['id']);act(c,t,'claim',fa)
        top=c.execute("INSERT INTO org_units(code,name) VALUES('top-manager','Top manager unit') RETURNING id").fetchone()['id']
        parent_manager=role(c,'parent-manager',owner=top)
        c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=%s',(parent_manager,top))
        c.execute('UPDATE org_units SET parent_org_unit_id=%s WHERE id=1',(top,))
        if failure=='missing':c.execute('UPDATE org_units SET managing_role_id=NULL WHERE id=1')
        elif failure=='inactive':c.execute('UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(um,))
        else:c.execute('DELETE FROM user_role_assignments WHERE role_id=%s',(um,))
        before=job_version(c,job['id'])
        with pytest.raises(psycopg.Error,match='disposition_reviewer_unavailable'):
            if after_file_admin:
                execute_command(c,**{**kwargs(),'acting_role_id':fa},operation='review_decide',payload={'task_id':t['id']},
                  apply=lambda x:workflow.route_review(x,job_id=job['id'],stage='unit_manager_review'))
            else:submit(c,job['id'])
        assert job_version(c,job['id'])==before
        assert task(c,job['id'])['workflow_stage']==('file_administrator_review' if after_file_admin else 'officer_preparation')


@pytest.mark.parametrize('kind',['destruction','permanent_transfer','selective_transfer','local_archives'])
def test_shared_job_projection_keeps_all_common_job_types_and_scopes_preparer_flag(client,kind):
    from backend.services.api.disposition import queries
    with db() as c:
        job=setup(c,kind)
        row=queries.job(c,job['id'])
        assert row['job_type']==kind and row['membership_editable']
        other=person(c);role(c,'another-reader',user=other)
        actor(c,other)
        assert queries.job(c,job['id'])['membership_editable']==(kind!='destruction')
