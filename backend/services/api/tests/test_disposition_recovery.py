"""Phase 20, owned disposable PostgreSQL only; production release stays closed."""
from uuid import uuid4
import pytest
import psycopg
from backend.services.api.disposition import documents,membership,recovery,artifacts
from backend.services.api.tests.test_disposition_physical import approved,report,confirmation,release_for_test
from backend.services.api.tests.test_disposition_review import db,claim
from backend.services.api.tests.test_disposition_membership import actor,job_version,kwargs,setup,admit
from backend.services.api.tests.test_disposition_eligibility import statuses

@pytest.fixture(autouse=True)
def renderer(monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    yield
    with db() as c:c.execute('CREATE OR REPLACE FUNCTION disposition_private.physical_execution_released() RETURNS boolean LANGUAGE sql IMMUTABLE AS $$ SELECT false $$')


def physical_done(c):
    job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);release_for_test(c);c.commit();actor(c)
    confirmation(c,job,mgr);c.commit();actor(c)
    return job,root,mgr


def terminate(c,job,**extra):
    return membership.terminate_job(c,job_id=job['id'],expected_version=job_version(c,job['id']),confirmed=True,**kwargs(**extra))


def resolve(c,job,*,status=2,root=None,key=None,**extra):
    preview=recovery.preview(c,job['id']) if root is None else {}
    args=dict(job_id=job['id'],target_status=status,acting_role_id=1,command_id=key or uuid4(),reason='Preserve and redirect remaining digital material',**extra)
    if root is None:args.update(confirmed=True,affected_count=preview['affected_count'],scope_token=preview['scope_token'])
    else:args.update(root_id=root,root_version=c.execute('SELECT version FROM aggregations WHERE id=%s',(root,)).fetchone()['version'])
    return recovery.resolve(c,**args)


def test_terminate_physical_preserves_scope_and_sets_full_unit_partial(client):
    with db() as c:
        job,root,mgr=physical_done(c)
        physical=c.execute('SELECT * FROM disposition_physical_confirmations').fetchone()
        out=terminate(c,job)
        assert out['lifecycle_state']=='terminated' and statuses(c,root)==[13]*4
        assert c.execute('SELECT * FROM disposition_physical_confirmations').fetchone()==physical
        assert c.execute('SELECT membership_state FROM disposition_job_memberships WHERE root_aggregation_id=%s',(root,)).fetchone()['membership_state']=='terminated_history'
        assert recovery.preview(c,job['id'])['affected_count']==1


@pytest.mark.parametrize('status',[2,3,4,5])
def test_individual_resolution_selected_status_then_matching_job(client,status):
    with db() as c:
        job,root,mgr=physical_done(c);terminate(c,job);result=resolve(c,job,status=status,root=root)
        assert result['affected_count']==1 and statuses(c,root)==[status]*4
        new=setup(c,kind={2:'destruction',3:'permanent_transfer',4:'selective_transfer',5:'local_archives'}[status])
        assert admit(c,new['id'],[root])['items'][0]['success']
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE root_aggregation_id=%s AND membership_state='terminated_history'",(root,)).fetchone()['n']==1


def make_unit(c,medium='mixed',private_child=False):
    from backend.services.api.application_settings import load_snapshot
    from backend.services.api.content_storage import PostgreSQLContentStorage
    from backend.services.api.tests.test_disposition_artifacts import uploaded
    from backend.services.api.disposition.eligibility import evaluate_root,worker_actor
    root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened,medium) VALUES(%s,'Recovery root',1,1,'1900-01-01',%s) RETURNING id",(str(uuid4()),medium)).fetchone()['id']
    child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,medium) VALUES(%s,%s,'Recovery child',%s) RETURNING id",(root,str(uuid4()),medium)).fetchone()['id']
    leaf=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,medium) VALUES(%s,%s,'Recovery leaf',%s) RETURNING id",(child,str(uuid4()),medium)).fetchone()['id']
    record=c.execute("INSERT INTO records(aggregation_id,record_number,title,medium) VALUES(%s,%s,'Remaining material',%s) RETURNING id",(leaf,str(uuid4()),medium)).fetchone()['id']
    if private_child:
        c.execute('UPDATE aggregations SET inherit_acl_from_parent=false WHERE id=%s',(child,))
        c.execute('DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s',(child,))
    if medium!='physical':
        import hashlib
        content=b'Preserved confidential digital material, not audit content.'
        component=c.execute("INSERT INTO digital_components(record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value,storage_backend,content_status) VALUES(%s,1,'remaining.pdf','application/pdf',%s,'sha256',%s,'postgresql','available') RETURNING id",(record,len(content),hashlib.sha256(content).hexdigest())).fetchone()['id']
        PostgreSQLContentStorage().store_upload(c,component,uploaded(content),settings=load_snapshot(c))
    c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,5,0,'destruction','Isolated recovery fixture')",(root,))
    c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,));worker_actor(c);evaluate_root(c,root);actor(c)
    return root,child,leaf,record


def mixed_done(c,monkeypatch,private_child=False):
    from backend.services.api.tests import test_disposition_workflow as fixtures
    from backend.services.api.tests.test_disposition_approval import manager,reach_manager,approve
    from backend.services.api.tests.test_disposition_external import generate,decision
    from backend.services.api.tests.test_disposition_artifacts import configure,root as destination
    monkeypatch.setattr(fixtures,'ready',lambda c:make_unit(c,private_child=private_child))
    job,first,mgr=manager(c,'simplified');configure(c);destination(c)
    second,*_=make_unit(c);fully,*_=make_unit(c,'physical');untouched,*_=make_unit(c,'digital')
    assert all(r['success'] for r in admit(c,job['id'],[second,fully,untouched])['items'])
    reach_manager(c,job,'simplified');rid=approve(c,job,mgr)['round_id'];generate(c,job,mgr,rid);decision(c,job);c.commit();actor(c)
    report(c,job,mgr);claim(c,job);release_for_test(c);c.commit();actor(c);confirmation(c,job,mgr);c.commit();actor(c)
    return job,first,second,fully,untouched,mgr


def content_rows(c):
    return c.execute('SELECT to_jsonb(b) data FROM digital_component_blobs b ORDER BY id').fetchall()


def test_mixed_termination_preserves_completed_partial_untouched_and_actual_executor(client,monkeypatch):
    with db() as c:
        job,a,b,done,untouched,mgr=mixed_done(c,monkeypatch);content=content_rows(c)
        confirmation_row=c.execute('SELECT * FROM disposition_physical_confirmations').fetchone()
        terminate(c,job)
        assert statuses(c,a)==[13]*4 and statuses(c,b)==[13]*4 and statuses(c,done)==[10]*4 and statuses(c,untouched)==[2]*4
        final=c.execute('SELECT * FROM aggregations WHERE id=%s',(done,)).fetchone()
        assert final['final_disposition_at']==confirmation_row['confirmed_at'] and final['final_disposition_by_user_id']==confirmation_row['confirmed_by_user_id']
        assert final['destruction_number'] and final['final_disposition_event_id']
        assert content_rows(c)==content
        assert c.execute('SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state=\'terminated_history\'',(job['id'],)).fetchone()['n']==4
        assert recovery.preview(c,job['id'])['affected_count']==2
        from backend.services.api.disposition import queries
        rows={r['root_aggregation_id']:r for r in queries.members(c,job['id'],limit=25,offset=0)['items']}
        assert rows[a]['partially_destroyed'] and rows[a]['can_recover']
        assert not rows[done]['partially_destroyed'] and not rows[done]['can_recover']
        assert not admit(c,setup(c)['id'],[done])['items'][0]['success']


def test_bulk_resolution_exact_retry_linked_events_excludes_final_and_eligible(client,monkeypatch):
    with db() as c:
        job,a,b,done,untouched,mgr=mixed_done(c,monkeypatch);terminate(c,job);before=content_rows(c);preview=recovery.preview(c,job['id'])
        args=dict(job_id=job['id'],target_status=4,acting_role_id=1,command_id=uuid4(),reason='Send remaining digital material to selective preservation',confirmed=True,**preview)
        result=recovery.resolve(c,**args);assert recovery.resolve(c,**args)==result
        assert result['affected_count']==2 and statuses(c,a)==[4]*4 and statuses(c,b)==[4]*4
        assert statuses(c,done)==[10]*4 and statuses(c,untouched)==[2]*4 and content_rows(c)==before
        events=c.execute("SELECT metadata FROM event_history WHERE operation IN ('DISPOSITION_PARTIAL_RESOLVED','DISPOSITION_PARTIAL_BULK_RESOLVED') AND metadata->>'command_id'=%s",(str(args['command_id']),)).fetchall()
        assert len(events)==3 and all(e['metadata']['new_status']==4 for e in events)
        unit_events=[e['metadata'] for e in events if 'preserved_digital_material' in e['metadata']]
        assert len(unit_events)==2 and all(e['preserved_digital_material'] and e['certificate_document_id'] for e in unit_events)
        assert 'confidential digital material' not in str(events)
        wrong=setup(c);assert not admit(c,wrong['id'],[a])['items'][0]['success']
        matching=setup(c,kind='selective_transfer');assert admit(c,matching['id'],[a])['items'][0]['success']


def test_late_bulk_failure_rolls_back_every_unit_and_event(client,monkeypatch):
    with db() as c:
        job,a,b,*_=mixed_done(c,monkeypatch);terminate(c,job)
        c.execute(f"CREATE FUNCTION fail_recovery_unit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.aggregation_id IN (SELECT disposition_private.unit_ids({b})) AND NEW.disposition_status=3 THEN RAISE EXCEPTION 'isolated recovery failure'; END IF; RETURN NEW; END $$")
        c.execute('CREATE TRIGGER fail_recovery_unit BEFORE UPDATE ON records FOR EACH ROW EXECUTE FUNCTION fail_recovery_unit()')
        before=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        try:
            with pytest.raises(psycopg.Error,match='isolated recovery failure'),c.transaction():resolve(c,job,status=3)
            assert statuses(c,a)==[13]*4 and statuses(c,b)==[13]*4
            assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==before
        finally:c.execute('DROP TRIGGER fail_recovery_unit ON records');c.execute('DROP FUNCTION fail_recovery_unit()')


def test_stale_bulk_preview_confirmation_and_required_reason_are_atomic(client,monkeypatch):
    with db() as c:
        job,a,b,*_=mixed_done(c,monkeypatch);terminate(c,job);preview=recovery.preview(c,job['id'])
        resolve(c,job,root=a)
        args=dict(job_id=job['id'],target_status=2,acting_role_id=1,command_id=uuid4(),reason='One reason for this scope',confirmed=True,**preview)
        with pytest.raises(psycopg.Error,match='recovery_stale'),c.transaction():recovery.resolve(c,**args)
        args.update(recovery.preview(c,job['id']));args['confirmed']=False
        with pytest.raises(psycopg.Error,match='confirmation_required'),c.transaction():recovery.resolve(c,**args)
        args.update(confirmed=True,reason='  ')
        with pytest.raises(psycopg.Error,match='reason_required'),c.transaction():recovery.resolve(c,**args)
        assert statuses(c,b)==[13]*4


def test_recovered_new_job_skips_already_destroyed_physical_scope(client):
    from backend.services.api.tests.test_disposition_approval import reach_manager,approve
    from backend.services.api.tests.test_disposition_external import generate,decision
    with db() as c:
        job,root,mgr=physical_done(c);terminate(c,job);resolve(c,job,root=root)
        new=setup(c);admit(c,new['id'],[root]);reach_manager(c,new,'simplified');rid=approve(c,new,mgr)['round_id'];generate(c,new,mgr,rid)
        result=decision(c,new,number='NEXT-JOB-APPROVAL')
        assert result['workflow_stage']=='digital_destruction'
        assert c.execute('SELECT disposition_private.physical_scope(%s) scope',(new['id'],)).fetchone()['scope']=={'aggregations':[],'records':[]}


@pytest.mark.parametrize('correction',['reopen','rule','membership'])
def test_post_physical_correction_requires_termination(client,correction):
    from backend.services.api.tests.test_disposition_membership import remove
    with db() as c:
        job,root,mgr=physical_done(c)
        with pytest.raises(psycopg.Error,match='physical_recovery_required|membership_stage_invalid'),c.transaction():
            if correction=='reopen':c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
            elif correction=='rule':c.execute('UPDATE aggregation_retention_rules SET current_period_years=1 WHERE aggregation_id=%s',(root,))
            else:remove(c,root)
        assert statuses(c,root)==[6]*4


def test_no_direct_partial_resolution_or_content_removal(client):
    from backend.services.api.disposition.commands import execute_command
    with db() as c:
        job,root,mgr=physical_done(c);terminate(c,job)
        assert not admit(c,setup(c)['id'],[root])['items'][0]['success']
        with pytest.raises(psycopg.Error,match='recovery_command_required'),c.transaction():c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        with pytest.raises(psycopg.Error,match='recovery_command_required'),c.transaction():
            execute_command(c,command_id=uuid4(),operation='resolve_partial',payload={'job_id':job['id']},acting_role_id=1,reason='Cannot bypass scoped recovery',apply=lambda x:(x.execute('UPDATE aggregations SET disposition_status=2 WHERE id=%s',(root,)),{})[1])
        assert statuses(c,root)==[13]*4


def test_current_hold_allows_safe_termination_resolution_but_blocks_readmission(client):
    from backend.services.api.tests.test_disposition_eligibility import make_hold
    with db() as c:
        job,root,mgr=physical_done(c);hold=make_hold(c,'aggregation',root)
        assert statuses(c,root)==[6]*4
        terminate(c,job);assert statuses(c,root)==[13]*4
        resolve(c,job,root=root);assert statuses(c,root)==[2]*4
        new=setup(c);result=admit(c,new['id'],[root]);assert not result['items'][0]['success'] and result['items'][0]['code']=='disposition_admission_blocked'


def test_bulk_hidden_scope_authorization_failure_has_no_effect(client,monkeypatch):
    from backend.services.api.tests.test_disposition_workflow import person,role
    with db() as c:
        job,a,b,*_=mixed_done(c,monkeypatch);terminate(c,job)
        user=person(c,'Limited recovery IGU');role(c,'limited-recovery-igu','INFO_GOV_OFFICER',user=user)
        level=c.execute('SELECT id FROM security_levels ORDER BY level_number DESC LIMIT 1').fetchone()['id']
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(level,b))
        actor(c,user)
        with pytest.raises(psycopg.Error,match='recovery_access_required'),c.transaction():recovery.preview(c,job['id'])
        assert statuses(c,a)==[13]*4 and statuses(c,b)==[13]*4


def test_existing_completed_unit_keeps_exact_final_metadata_when_job_terminates(client,monkeypatch):
    from backend.services.api.disposition.commands import execute_command
    with db() as c:
        job,a,b,done,untouched,mgr=mixed_done(c,monkeypatch)
        # Simulate an already successful unit through the protected, scoped
        # primitive in this owned disposable DB; no digital execution is enabled.
        key=uuid4()
        def completed(x):
            x.execute('INSERT INTO disposition_private.recovery_context VALUES(txid_current(),pg_backend_pid(),%s,%s,%s,10)',(key,job['id'],done))
            x.execute('SELECT disposition_private.transition_unit(%s,%s,10)',(done,x.execute('SELECT version FROM aggregations WHERE id=%s',(done,)).fetchone()['version']))
            x.execute('DELETE FROM disposition_private.recovery_context WHERE transaction_id=txid_current()');return {'root_id':done}
        execute_command(c,command_id=key,operation='job_terminate',payload={'job_id':job['id']},acting_role_id=1,reason='Seed a verified successful physical-only unit',apply=completed)
        before=c.execute('SELECT * FROM aggregations WHERE id=%s',(done,)).fetchone()
        terminate(c,job)
        assert c.execute('SELECT * FROM aggregations WHERE id=%s',(done,)).fetchone()==before
        assert statuses(c,a)==[13]*4 and statuses(c,untouched)==[2]*4


def test_http_bulk_requires_preview_count_confirmation_reason_and_current_actor(client):
    with db() as c:
        job,root,mgr=physical_done(c);terminate(c,job);preview=recovery.preview(c,job['id']);v=job_version(c,job['id'])
    path=f"/api/v1/disposition/jobs/{job['id']}/partial-recovery"
    payload={'command_id':str(uuid4()),'acting_role_id':1,'target_status':3,'confirmed':True,**preview}
    csrf={'X-CSRF-Token':client.cookies.get('erms_csrf')}
    assert client.post(path,json=payload,headers=csrf).status_code==422
    assert client.post(path,json={**payload,'target_status':13},headers={**csrf,'X-Change-Reason':'Choose a new eligible status'}).status_code==422
    response=client.post(path,json=payload,headers={**csrf,'X-Change-Reason':'Preserve remaining digital material for transfer'})
    assert response.status_code==200,response.text
    assert response.json()['affected_count']==1
    assert client.post(path,json=payload,headers={**csrf,'X-Change-Reason':'Preserve remaining digital material for transfer'}).json()==response.json()


def test_concurrent_resolutions_have_one_winner(client):
    from concurrent.futures import ThreadPoolExecutor
    with db() as c:
        job,root,mgr=physical_done(c);terminate(c,job);preview=recovery.preview(c,job['id'])
    def attempt(status):
        with db() as c:
            actor(c)
            try:return recovery.resolve(c,job_id=job['id'],target_status=status,confirmed=True,acting_role_id=1,command_id=uuid4(),reason='Concurrent explicit recovery',**preview)
            except psycopg.Error as error:return error.diag.message_primary
    with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(attempt,[2,3]))
    assert sum(isinstance(r,dict) for r in out)==1
    assert next(r for r in out if isinstance(r,str))=='disposition_recovery_stale'


def test_retained_content_cannot_be_deleted_and_historical_links_remain(client,monkeypatch):
    with db() as c:
        job,a,b,done,untouched,mgr=mixed_done(c,monkeypatch)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' LIMIT 1").fetchone()['id']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(a,done,kind))
        # These links are within the original active job and precede termination.
        physical=c.execute('SELECT * FROM disposition_physical_confirmations WHERE job_id=%s',(job['id'],)).fetchone()
        content=content_rows(c);terminate(c,job)
        component=c.execute('SELECT d.id FROM digital_components d JOIN records r ON r.id=d.record_id WHERE r.aggregation_id IN (SELECT disposition_private.unit_ids(%s)) LIMIT 1',(a,)).fetchone()['id']
        with pytest.raises(psycopg.Error),c.transaction():c.execute('DELETE FROM digital_components WHERE id=%s',(component,))
        with pytest.raises(psycopg.Error),c.transaction():c.execute('DELETE FROM digital_component_blobs WHERE digital_component_id=%s',(component,))
        assert content_rows(c)==content and statuses(c,a)==[13]*4
        resolve(c,job,root=a)
        new=setup(c);assert admit(c,new['id'],[a])['items'][0]['success']
        assert not c.execute('SELECT blocks_final FROM disposition_private.relationship_scope(%s) WHERE target_id=%s',(a,done)).fetchone()['blocks_final']
        c.execute('INSERT INTO aggregation_relationships(source_id,target_id,relationship_type_id) VALUES(%s,%s,%s)',(a,b,kind))
        assert c.execute('SELECT blocks_final FROM disposition_private.relationship_scope(%s) WHERE target_id=%s',(a,b)).fetchone()['blocks_final']
        assert c.execute('SELECT * FROM disposition_physical_confirmations WHERE job_id=%s',(job['id'],)).fetchone()==physical


def test_recovery_event_hides_preserved_identifiers_when_descendant_is_hidden(client,monkeypatch):
    from backend.services.api.tests.test_disposition_workflow import person,role
    with db() as c:
        job,a,*_=mixed_done(c,monkeypatch,private_child=True);terminate(c,job);resolve(c,job,root=a)
        event=c.execute("SELECT id FROM event_history WHERE entity_id=%s AND operation='DISPOSITION_PARTIAL_RESOLVED' AND entity_type='aggregation'",(a,)).fetchone()['id']
        uid=person(c,'Recovery history observer');rid=role(c,'recovery-history-observer','ALL_PRIVS',user=uid)
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=%s',(rid,))
        c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id) SELECT %s,'role',%s,id FROM permissions WHERE code='aggregation.view'",(a,rid))
        # The child had an explicit private ACL before closure; root stays visible.
        actor(c,uid)
        assert c.execute('SELECT current_user_can_view_aggregation(%s) allowed',(a,)).fetchone()['allowed']
        assert not c.execute('SELECT disposition_private.recovery_unit_visible(%s) allowed',(a,)).fetchone()['allowed']
        assert c.execute('SELECT metadata FROM authorized_event_history WHERE id=%s',(event,)).fetchone()['metadata']=={'redacted':True,'reason':'resource_access_denied'}
