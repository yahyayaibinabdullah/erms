"""Phase 19: canonical disposable database; workflow authorization and confirmations remain required."""
from uuid import uuid4
import pytest
import psycopg
from fastapi import HTTPException
from backend.services.api.disposition import physical,documents,artifacts
from backend.services.api.application_settings import load_snapshot
from backend.services.api.content_storage import stage_governed_upload
from backend.services.api.tests.test_disposition_external import prepared,generate,decision
from backend.services.api.tests.test_disposition_review import db,task,claim
from backend.services.api.tests.test_disposition_membership import actor,job_version
from backend.services.api.tests.test_disposition_artifacts import uploaded

@pytest.fixture(autouse=True)
def renderer(monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{'renderer':'test'}))
    with db() as c:security=c.execute('SELECT id,prevents_disposition FROM security_levels').fetchall()
    try:yield
    finally:
        with db() as c:
            for row in security:c.execute('UPDATE security_levels SET prevents_disposition=%s WHERE id=%s',(row['prevents_disposition'],row['id']))


def approved(c):
    job,root,mgr,rid=prepared(c);generate(c,job,mgr,rid);result=decision(c,job)
    c.commit();actor(c)
    return job,root,mgr,result


def report(c,job,mgr,key=None):
    return physical.generate_report(c,job_id=job['id'],expected_version=job_version(c,job['id']),command_id=key or uuid4(),acting_role_id=mgr,settings=load_snapshot(c),connection_factory=db)


def confirmation(c,job,mgr,key=None,ref='PHYS/2026/1',successful=True):
    t=task(c,job['id']);key=key or uuid4()
    with stage_governed_upload(uploaded(b'Physical certificate'),load_snapshot(c),connection_factory=db) as staged:
        return physical.confirm(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],successful=successful,certificate_reference=ref,staged=staged,preview=artifacts.destination_token(artifacts.destination(c,job['id'],'physical_destruction_certificate')),acting_role_id=mgr,command_id=key)


def test_routes_all_hierarchy_and_report_versions_keep_snapshots(client):
    with db() as c:
        job,root,mgr,result=approved(c)
        assert result['workflow_stage']=='physical_destruction'
        assert task(c,job['id'])['task_type']=='physical_destruction'
        first=report(c,job,mgr);c.commit();actor(c)
        old=artifacts.document(c,job['id'],first['id']);assert old['origin']=='generated'
        key=uuid4();second=report(c,job,mgr,key);assert report(c,job,mgr,key)==second
        new=artifacts.document(c,job['id'],second['id'])
        assert old['provenance']['snapshot']['fields']['report.version']==1
        assert new['provenance']['snapshot']['fields']['report.version']==2
        assert new['classification_id']==old['classification_id']
        listed=artifacts.page(c,job['id'],limit=25,offset=0,sort='evidence_version')['items']
        reports=[d for d in listed if d['document_type']=='physical_preparation_report']
        assert [d['evidence_version'] for d in reports]==[2,1] and reports[0]['is_current'] and not reports[1]['is_current']
        assert c.execute("SELECT to_regprocedure('disposition_private.physical_execution_released()') IS NULL yes").fetchone()['yes']


def test_release_gate_missing_confirmation_and_exact_retry(client):
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        c.commit();actor(c)
        with pytest.raises(HTTPException),c.transaction():confirmation(c,job,mgr,successful=False)
        t=task(c,job['id']);version=job_version(c,job['id']);key=uuid4();dest=artifacts.destination_token(artifacts.destination(c,job['id'],'physical_destruction_certificate'))
        args=dict(task_id=t['id'],expected_version=version,task_version=t['version'],successful=True,certificate_reference='REF / ١',preview=dest,acting_role_id=mgr,command_id=key)
        for _ in range(2):
            with stage_governed_upload(uploaded(b'certificate'),load_snapshot(c),connection_factory=db) as staged:out=physical.confirm(c,staged=staged,**args)
        row=c.execute('SELECT * FROM disposition_physical_confirmations WHERE id=%s',(out['id'],)).fetchone()
        assert row['confirmed_by_user_id']==1 and row['confirmation_version']==1 and row['successful']
        assert row['physical_scope']['aggregations'] or row['physical_scope']['records']
        assert c.execute('SELECT count(*) n FROM disposition_physical_confirmations').fetchone()['n']==1
        with pytest.raises(psycopg.Error,match='physical_immutable|protected_operation_required'),c.transaction():c.execute("UPDATE disposition_physical_confirmations SET certificate_reference='wrong'")

@pytest.mark.parametrize('mode,stage',[('digital','digital_destruction'),('physical','physical_destruction'),('mixed','physical_destruction'),('physical_descendant','physical_destruction'),('physical_record','physical_destruction')])
def test_routing_uses_every_item_not_just_roots(client,monkeypatch,mode,stage):
    from backend.services.api.tests.test_disposition_approval import manager,reach_manager,approve
    from backend.services.api.tests.test_disposition_artifacts import configure,root as destination_root
    from backend.services.api.tests import test_disposition_workflow as fixtures
    from backend.services.api.disposition.eligibility import worker_actor,evaluate_root
    def media_ready(c):
        medium=mode if mode in ('digital','physical','mixed') else 'digital'
        root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened,medium) VALUES(%s,'Media root',1,1,'1900-01-01',%s) RETURNING id",(str(uuid4()),medium)).fetchone()['id']
        child_medium='physical' if mode=='physical_descendant' else medium
        if mode=='physical_descendant':
            # Legacy import fixture only; current capture disallows this mix.
            c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ALTER TABLE aggregations DISABLE TRIGGER aggregations_enforce_medium_hierarchy')
        try:child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,medium) VALUES(%s,%s,'Descendant',%s) RETURNING id",(root,str(uuid4()),child_medium)).fetchone()['id']
        finally:
            if mode=='physical_descendant':c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ALTER TABLE aggregations ENABLE TRIGGER aggregations_enforce_medium_hierarchy')
        record_medium='physical' if mode=='physical_record' else child_medium
        if mode=='physical_record':c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ALTER TABLE records DISABLE TRIGGER records_enforce_medium_hierarchy')
        try:record=c.execute("INSERT INTO records(aggregation_id,record_number,title,medium) VALUES(%s,%s,'Record',%s) RETURNING id",(child,str(uuid4()),record_medium)).fetchone()['id']
        finally:
            if mode=='physical_record':c.execute('SET CONSTRAINTS ALL IMMEDIATE');c.execute('ALTER TABLE records ENABLE TRIGGER records_enforce_medium_hierarchy')
        c.execute('SET CONSTRAINTS ALL DEFERRED')
        c.execute("INSERT INTO aggregation_retention_rules(aggregation_id,current_period_years,intermediate_period_years,final_disposition,justification) VALUES(%s,5,0,'destruction','Isolated medium acceptance')",(root,))
        c.execute("UPDATE aggregations SET date_closed='2020-01-01' WHERE id=%s",(root,));worker_actor(c);evaluate_root(c,root);actor(c)
        return root,child,record
    monkeypatch.setattr(fixtures,'ready',media_ready)
    with db() as c:
        job,root,mgr=manager(c,'simplified');configure(c);destination_root(c)
        reach_manager(c,job,'simplified');rid=approve(c,job,mgr)['round_id'];generate(c,job,mgr,rid)
        out=decision(c,job);assert out['workflow_stage']==stage
        scope=c.execute('SELECT disposition_private.physical_scope(%s) s',(job['id'],)).fetchone()['s']
        if mode.startswith('physical_'):assert not any(x['id']==root for x in scope['aggregations'])
        assert c.execute('SELECT disposition_private.has_digital_material(%s) yes',(job['id'],)).fetchone()['yes']==(mode!='physical')


@pytest.mark.parametrize('kind',['vital','aggregation_link','record_link'])
def test_prework_check_rechecks_blockers_even_on_retried_check(client,kind):
    from backend.services.api.tests.test_disposition_eligibility import link,unit
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        t=task(c,job['id']);args=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],acting_role_id=mgr,command_id=uuid4())
        assert physical.check_work(c,**args)['authorized'];c.commit();actor(c)
        if kind=='vital':
            c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
            c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(root,))
        else:
            outside,*_,record=unit(c)
            if kind=='aggregation_link':link(c,'aggregation',root,outside)
            else:
                own=c.execute('SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s)) LIMIT 1',(root,)).fetchone()['id']
                link(c,'record',own,record)
        c.commit();actor(c)
        with pytest.raises(psycopg.Error,match='physical_blocked'),c.transaction():physical.check_work(c,**args)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        with pytest.raises(psycopg.Error,match='physical_blocked'),c.transaction():confirmation(c,job,mgr)
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert not c.execute('SELECT 1 FROM disposition_physical_confirmations').fetchone()


def test_confirmation_correction_preserves_original_and_later_failure_rolls_everything_back(client):
    from backend.services.api.disposition.commands import execute_command
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        with pytest.raises(RuntimeError),c.transaction():
            confirmation(c,job,mgr);raise RuntimeError('Simulated final outcome failure')
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert not c.execute('SELECT 1 FROM disposition_physical_confirmations').fetchone()
        out=confirmation(c,job,mgr);c.commit();actor(c)
        original=c.execute('SELECT * FROM disposition_physical_confirmations').fetchone()
        with stage_governed_upload(uploaded(b'Corrected certificate'),load_snapshot(c),connection_factory=db) as staged:
            result=artifacts.correct(c,job_id=job['id'],document_id=out['certificate_document_id'],expected_version=job_version(c,job['id']),command_id=uuid4(),acting_role_id=mgr,reason='Correct an attachment without rewriting physical truth',staged=staged,preview=artifacts.destination(c,job['id'],'physical_destruction_certificate'))
        assert result['evidence_version']==2 and c.execute('SELECT * FROM disposition_physical_confirmations').fetchone()==original
        with pytest.raises(psycopg.Error,match='physical_recovery_required|invalid_stage_transition'),c.transaction():
            execute_command(c,command_id=uuid4(),operation='review_decide',payload={'job_id':job['id'],'decision':'rejected'},acting_role_id=mgr,reason='Must not reopen destroyed physical scope',apply=lambda x:(x.execute("UPDATE disposition_jobs SET workflow_stage='officer_correction' WHERE id=%s",(job['id'],)),{})[1])


def test_duplicate_reference_is_global_and_does_not_save_second_evidence(client):
    with db() as c:
        first,*_=approved(c)
        mgr=c.execute("SELECT id FROM roles WHERE profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_MGR') ORDER BY id LIMIT 1").fetchone()['id']
        report(c,first,mgr);claim(c,first);c.commit();actor(c);confirmation(c,first,mgr);c.commit();actor(c)
        from backend.services.api.tests.test_disposition_membership import setup,ready,admit
        from backend.services.api.tests.test_disposition_approval import reach_manager,approve
        second=setup(c);new_root,*_=ready(c);admit(c,second['id'],[new_root]);reach_manager(c,second,'simplified');rid=approve(c,second,mgr)['round_id'];generate(c,second,mgr,rid);decision(c,second,number='External 2');c.commit();actor(c)
        report(c,second,mgr);claim(c,second);c.commit();actor(c)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        with pytest.raises(psycopg.Error,match='physical_reference_used'),c.transaction():confirmation(c,second,mgr)
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert c.execute('SELECT count(*) n FROM disposition_physical_confirmations').fetchone()['n']==1


def test_concurrent_relationship_commit_is_seen_before_authorizing_work(client):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from backend.services.api.tests.test_disposition_eligibility import unit,link,wait_for_waiter
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job)
        outside,*_=unit(c);t=task(c,job['id']);v=job_version(c,job['id'])
    started=Queue()
    def check():
        with db() as c:
            actor(c);started.put(c.info.backend_pid)
            try:physical.check_work(c,task_id=t['id'],expected_version=v,task_version=t['version'],acting_role_id=mgr,command_id=uuid4())
            except psycopg.Error as error:return error.diag.message_primary
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db() as mutation:
            actor(mutation);link(mutation,'aggregation',root,outside)
            future=pool.submit(check);wait_for_waiter(mutation,started.get(timeout=5));mutation.commit()
        assert future.result(timeout=10)=='disposition_physical_blocked'


def test_location_change_during_render_rejects_stale_report_without_record(client,monkeypatch):
    from tools.preview_disposition import preview_pdf
    with db() as c:
        job,root,mgr,_=approved(c)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n'];c.commit();actor(c)
        def render(*args):
            with db() as other:
                actor(other);other.execute("SELECT set_config('app.location_change_authorized','authorized',true)")
                other.execute("UPDATE aggregations SET assigned_location='Shelf B' WHERE id=%s",(root,))
            return preview_pdf(),{}
        monkeypatch.setattr(documents.engine,'render',render)
        with pytest.raises(HTTPException) as error,c.transaction():report(c,job,mgr)
        assert error.value.detail['code']=='disposition_physical_report_stale'
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert not c.execute("SELECT 1 FROM disposition_job_documents WHERE document_type='physical_preparation_report'").fetchone()


def test_deep_hierarchy_counts_are_nonrecursive_and_nonoverlapping():
    from backend.services.api.disposition.document_snapshots import physical_rows
    aggs=[dict(id=i,parent_aggregation_id=i-1 if i>1 else None,classification_id=1,classification_code='A',classification_title='Class',aggregation_number=str(i),title='Nested',medium='physical',owner='Unit',assigned_location=None,current_location=None) for i in range(1,3001)]
    rows,totals,_=physical_rows({'aggregations':aggs,'records':[{'id':1,'aggregation_id':3000,'medium':'mixed'}]})
    assert len(rows)==3000 and totals['physical_aggregations']==3000 and totals['mixed_records']==1
    root=next(r for r in rows if r['aggregation.identifier']=='1')
    assert root['aggregation.descendants.physical_aggregations']==2999 and root['aggregation.descendants.mixed_records']==1


def test_every_eligible_manager_queue_receives_one_task_and_confirm_closes_siblings(client):
    from backend.services.api.tests.test_disposition_workflow import role
    with db() as c:
        job,root,mgr,rid=prepared(c);other=role(c,'other-physical-manager','INFO_GOV_MGR');generate(c,job,mgr,rid);decision(c,job);c.commit();actor(c)
        tasks=c.execute("SELECT * FROM disposition_tasks WHERE job_id=%s AND task_type='physical_destruction' ORDER BY id",(job['id'],)).fetchall()
        assert {t['destination_role_id'] for t in tasks}=={mgr,other}
        report(c,job,mgr)
        # claim() chooses the newest offered queue; use its actual Manager role.
        claim(c,job);c.commit();actor(c)
        confirmation(c,job,other)
        states=[r['task_state'] for r in c.execute("SELECT task_state FROM disposition_tasks WHERE job_id=%s AND task_type='physical_destruction' ORDER BY id",(job['id'],))]
        assert sorted(states)==['cancelled','completed']
        assert c.execute('SELECT count(*) n FROM disposition_physical_confirmations').fetchone()['n']==1


def test_report_and_certificate_use_different_current_governed_destinations(client):
    from backend.services.api.tests.test_disposition_artifacts import configure,root as destination_root
    with db() as c:
        job,root,mgr,_=approved(c)
        other=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'REPORTS','Generated reports',true) RETURNING id").fetchone()['id']
        dest=destination_root(c,other);configure(c,evidence=1,reports=other);c.commit();actor(c)
        report_doc=artifacts.document(c,job['id'],report(c,job,mgr)['id'])
        assert report_doc['classification_id']==other and report_doc['aggregation_id']==dest
        claim(c,job);c.commit();actor(c)
        cert=artifacts.document(c,job['id'],confirmation(c,job,mgr)['certificate_document_id'])
        assert cert['classification_id']==1 and cert['aggregation_id']!=dest and cert['origin']=='uploaded'


def test_http_operational_release_and_missing_file_never_save_evidence(client):
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);t=task(c,job['id']);v=job_version(c,job['id'])
        token=artifacts.destination_token(artifacts.destination(c,job['id'],'physical_destruction_certificate'))
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
    path=f"/api/v1/disposition/tasks/{t['id']}/physical-confirmation"
    data={'command_id':str(uuid4()),'acting_role_id':str(mgr),'task_version':str(t['version']),'successful':'true','certificate_reference':'REF','destination_token':token}
    headers={'If-Match':str(v),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    assert client.post(path,data=data,headers=headers).status_code==422
    response=client.post(path,data=data,files={'file':('certificate.pdf',b'Certificate','application/pdf')},headers=headers)
    assert response.status_code==200,response.text
    with db() as c:
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before+1
        assert c.execute('SELECT 1 FROM disposition_physical_confirmations').fetchone()


def test_real_inherited_locations_and_report_totals_are_frozen(client):
    from backend.services.api.disposition.document_snapshots import NOT_SPECIFIED
    with db() as c:
        job,root,mgr,_=approved(c)
        c.execute("SELECT set_config('app.location_change_authorized','authorized',true)")
        c.execute("UPDATE aggregations SET assigned_location='Shelf A' WHERE id=%s",(root,))
        child=c.execute('SELECT id FROM aggregations WHERE parent_aggregation_id=%s',(root,)).fetchone()['id']
        c.execute("UPDATE aggregations SET current_location='Shelf B' WHERE id=%s",(child,));c.commit();actor(c)
        saved=artifacts.document(c,job['id'],report(c,job,mgr)['id']);snapshot=saved['provenance']['snapshot']
        assert all(r['aggregation.assigned_location']=='Shelf A' for r in snapshot['aggregations'])
        assert [r['aggregation.current_location'] for r in snapshot['aggregations']].count('Shelf B')==2
        assert [r['aggregation.current_location'] for r in snapshot['aggregations']].count(NOT_SPECIFIED)==1
        assert snapshot['fields']['totals.mixed_aggregations']==3 and snapshot['fields']['totals.mixed_records']==1


@pytest.mark.parametrize('kind',['hold','record_hold','security'])
def test_current_holds_and_security_block_before_offline_work(client,kind):
    from backend.services.api.tests.test_disposition_eligibility import make_hold
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);claim(c,job);c.commit();actor(c)
        if kind=='hold':make_hold(c,'aggregation',root)
        elif kind=='record_hold':
            record=c.execute('SELECT id FROM records WHERE aggregation_id IN (SELECT disposition_private.unit_ids(%s)) LIMIT 1',(root,)).fetchone()['id'];make_hold(c,'record',record)
        else:c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM aggregations WHERE id=%s)',(root,))
        c.commit();actor(c);t=task(c,job['id'])
        with pytest.raises(psycopg.Error,match='physical_blocked'),c.transaction():physical.check_work(c,task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],acting_role_id=mgr,command_id=uuid4())


def test_confirmation_requires_real_manager_and_own_claim(client):
    from backend.services.api.tests.test_disposition_review import officer
    with db() as c:
        job,root,mgr,_=approved(c);report(c,job,mgr);c.commit();actor(c)
        with pytest.raises(HTTPException) as error,c.transaction():confirmation(c,job,officer(c))
        assert error.value.status_code==403
        with pytest.raises(psycopg.Error,match='task_claim_required'),c.transaction():confirmation(c,job,mgr)
