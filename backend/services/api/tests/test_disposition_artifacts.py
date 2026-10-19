"""Phase 11 acceptance: disposable PostgreSQL only (enforced by conftest)."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4
import hashlib
import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from backend.services.api.application_settings import load_snapshot, apply_changes, destination_warnings
from backend.services.api.content_storage import stage_governed_upload
from backend.services.api.disposition import artifacts
from backend.services.api.disposition.commands import execute_command
from backend.services.api.application_settings_routes import SettingChange
from backend.services.api.tests.test_disposition_membership import db, setup, actor


def configure(c, evidence=1, reports=1, scheme=1):
    changes=[]
    for key,value in [('DISPOSITION_CLASSIFICATION_SCHEME_ID',scheme),('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID',evidence),('DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID',reports)]:
        version=c.execute('SELECT version FROM application_settings WHERE key=%s',(key,)).fetchone()['version']
        changes.append(SettingChange(key=key,value=value,expected_version=version))
    apply_changes(c,changes,'Configure isolated evidence destinations')


def root(c, classification=1, *, opened='2024-01-01', parent=None):
    if parent is None:
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) SELECT %s,5,0,'destruction' WHERE NOT EXISTS(SELECT 1 FROM classification_retention_rules WHERE classification_id=%s)",(classification,classification))
    return c.execute('''INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened,parent_aggregation_id)
      VALUES(%s,'Evidence root',%s,1,%s,%s) RETURNING id''',(str(uuid4()),classification if parent is None else None,opened,parent)).fetchone()['id']


def uploaded(content=b'original evidence',name='evidence.pdf'):
    return UploadFile(BytesIO(content),filename=name,headers=Headers({'content-type':'application/pdf'}))


def officer(c):
    return c.execute("SELECT id FROM roles WHERE code='fixture-records-officer'").fetchone()['id']


def seed_document(c, job, kind='external_approval_letter', *, content=b'original evidence', preview=None, acting_role_id=None):
    settings=load_snapshot(c)
    with stage_governed_upload(uploaded(content),settings,connection_factory=db) as staged:
        return artifacts.register(c,command_id=uuid4(),job_id=job['id'],expected_version=job['version'],document_type=kind,
          acting_role_id=acting_role_id or officer(c),reason='Save governed evidence in isolated acceptance',staged=staged,
          preview=preview or artifacts.destination(c,job['id'],kind),provenance={'source':'phase11 acceptance'})


def fixture(c):
    job=setup(c);configure(c);dest=root(c)
    return job,dest


def test_latest_root_order_ties_closed_child_wrong_classification_and_digital_certificate():
    with db() as c:
        job,dest=fixture(c)
        newer=root(c,opened='2025-01-01');tie=root(c,opened='2025-01-01')
        closed=root(c,opened='2026-01-01');c.execute("UPDATE aggregations SET date_closed='2026-02-01' WHERE id=%s",(closed,))
        child=root(c,opened='2026-03-01',parent=tie)
        other=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'OTHER','Other',true) RETURNING id").fetchone()['id']
        wrong=root(c,other,opened='2026-04-01')
        assert artifacts.destination(c,job['id'],'external_approval_letter',locked=True)['aggregation_id']==tie
        configure(c,reports=other)
        assert artifacts.destination(c,job['id'],'destruction_request',locked=True)['aggregation_id']==wrong
        assert artifacts.destination(c,job['id'],'digital_destruction_certificate',locked=True)['aggregation_id']==tie
        assert child!=tie and newer!=tie


def test_missing_destination_warns_and_rechecks_without_substitution():
    with db() as c:
        job=setup(c)
        p=artifacts.public_destination(c,job['id'],'external_approval_letter')
        assert not p['ready'] and p['warning']=='disposition_destination_unset'
        configure(c)
        p=artifacts.public_destination(c,job['id'],'external_approval_letter')
        assert p['warning']=='disposition_destination_open_root_missing'
        assert any(w['code']=='destination_open_root_missing' for w in destination_warnings(c))
        with pytest.raises(psycopg.Error,match='disposition_destination_open_root_missing'),c.transaction():seed_document(c,job)
        dest=root(c)
        assert artifacts.public_destination(c,job['id'],'external_approval_letter')['ready']
        saved=seed_document(c,job)
        assert c.execute('SELECT aggregation_id FROM records WHERE id=%s',(saved['record_id'],)).fetchone()['aggregation_id']==dest


def test_correction_append_preserves_original_confirmation_and_retry_is_exact():
    with db() as c:
        job,dest=fixture(c);original=seed_document(c,job)
        before=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        preview=artifacts.public_destination(c,job['id'],'external_approval_letter')['token']
        key=uuid4();settings=load_snapshot(c)
        for attempt in range(2):
            with stage_governed_upload(uploaded(b'corrected'),settings,connection_factory=db) as staged:
                result=artifacts.correct(c,job_id=job['id'],document_id=original['id'],expected_version=job['version'],
                  command_id=key,acting_role_id=officer(c),reason='Correct mistaken evidence',staged=staged,preview=preview)
                assert result['evidence_version']==2
        assert c.execute('SELECT count(*) count FROM disposition_job_documents').fetchone()['count']==2
        assert c.execute('SELECT count(*) count FROM records').fetchone()['count']==2
        assert c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()==before
        old=c.execute('SELECT * FROM disposition_job_documents WHERE id=%s',(original['id'],)).fetchone()
        assert old['record_id']==original['record_id'] and old['checksum']==hashlib.sha256(b'original evidence').hexdigest()
        chunks=c.execute('''SELECT b.content FROM digital_component_blobs b JOIN digital_component_content_sets s ON s.id=b.content_set_id WHERE s.digital_component_id=%s ORDER BY b.segment_no''',(old['digital_component_id'],)).fetchall()
        assert b''.join(bytes(x['content']) for x in chunks)==b'original evidence'
        rows=artifacts.page(c,job['id'],limit=1,offset=0)
        assert rows['total']==2 and len(rows['items'])==1 and rows['items'][0]['is_current']
        event=c.execute("SELECT * FROM event_history WHERE operation='EVIDENCE_CORRECTED'").fetchone()
        assert event['actor_type']=='user' and event['actor_user_id']==1
        assert event['metadata']['acting_role_id']==officer(c)
        assert event['metadata']['previous_record_id']==original['record_id']
        assert event['metadata']['previous_evidence_version']==1
        with pytest.raises(psycopg.Error,match='evidence_version_preserved'),c.transaction():
            c.execute("UPDATE digital_components SET checksum_value='wrong' WHERE id=%s",(old['digital_component_id'],))


def test_changed_destination_warning_and_stale_preview_keeps_earlier_record():
    with db() as c:
        job,original_root=fixture(c);old=seed_document(c,job)
        previous=artifacts.public_destination(c,job['id'],'external_approval_letter')['token']
        cl=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'NEW','New evidence',true) RETURNING id").fetchone()['id']
        new=root(c,cl);configure(c,evidence=cl)
        preview=artifacts.public_destination(c,job['id'],'external_approval_letter')
        assert preview['changed'] and preview['destination']['id']==new and preview['previous_destination']['id']==original_root
        with pytest.raises(HTTPException) as error,c.transaction():seed_document(c,job,preview={'scheme_id':1,'classification_id':1,'aggregation_id':original_root})
        assert error.value.detail['code']=='disposition_destination_changed'
        fresh=seed_document(c,job)
        assert c.execute('SELECT aggregation_id FROM records WHERE id=%s',(old['record_id'],)).fetchone()['aggregation_id']==original_root
        assert c.execute('SELECT aggregation_id FROM records WHERE id=%s',(fresh['record_id'],)).fetchone()['aggregation_id']==new
        configure(c,evidence=1);seed_document(c,job)
        reverted=artifacts.public_destination(c,job['id'],'external_approval_letter')
        assert reverted['changed'] and reverted['previous_destination']['id']==new


def test_governed_record_component_link_history_and_outcome_rollback_together():
    with db() as c:
        job,dest=fixture(c)
        before=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        with pytest.raises(ValueError),c.transaction():
            seed_document(c,job)
            raise ValueError('Action-specific outcome failed')
        for table in ('records','digital_components','disposition_job_documents','digital_component_blobs'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==before


def test_generated_documents_cannot_be_corrected():
    with db() as c:
        job,dest=fixture(c);generated=seed_document(c,job,'destruction_request')
        with stage_governed_upload(uploaded(),load_snapshot(c),connection_factory=db) as staged:
            with pytest.raises(HTTPException) as error:
                artifacts.correct(c,job_id=job['id'],document_id=generated['id'],expected_version=job['version'],
                  command_id=uuid4(),acting_role_id=officer(c),reason='Forbidden generated replacement',staged=staged,preview={})
        assert error.value.detail['code']=='disposition_generated_correction_forbidden'


def test_only_assigned_officer_or_manager_role_can_correct_and_retries_recheck_assignment():
    with db() as c:
        job,dest=fixture(c);old=seed_document(c,job)
        assert not c.execute('SELECT disposition_private.can_correct_evidence(%s,1) allowed',(job['id'],)).fetchone()['allowed']
        assert c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job['id'],officer(c))).fetchone()['allowed']
        mgr=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance,profile_id) SELECT 1,'manager','Records Manager',true,id FROM profiles WHERE code='INFO_GOV_MGR' RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)',(mgr,))
        assert c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job['id'],mgr)).fetchone()['allowed']
        c.execute("UPDATE user_role_assignments SET valid_until=CURRENT_TIMESTAMP WHERE role_id=%s",(mgr,))
        assert not c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job['id'],mgr)).fetchone()['allowed']
        with stage_governed_upload(uploaded(b'changed'),load_snapshot(c),connection_factory=db) as staged:
            with pytest.raises(HTTPException) as error:
                artifacts.correct(c,job_id=job['id'],document_id=old['id'],expected_version=job['version'],command_id=uuid4(),acting_role_id=1,reason='Wrong role',staged=staged,preview={})
        assert error.value.status_code==403


def test_staging_is_invisible_bounded_and_removed_after_failure():
    from backend.services.api.content_storage import stage_governed_upload
    with db() as c:
        actor(c);settings=dict(load_snapshot(c).values);settings['CONTENT_SEGMENT_SIZE_BYTES']=4;settings['CONTENT_UPLOAD_SESSION_TTL_SECONDS']=120
    with pytest.raises(ValueError):
        with stage_governed_upload(uploaded(b'0123456789'),settings,connection_factory=db) as staged:
            with db() as c:
                assert c.execute("SELECT expires_at<=CURRENT_TIMESTAMP+interval '121 seconds' AS correct_ttl FROM content_upload_sessions WHERE draft_component_id=%s",(staged.component_id,)).fetchone()['correct_ttl']
                assert c.execute('SELECT owner_user_id FROM record_drafts WHERE id=%s',(staged.draft_id,)).fetchone()['owner_user_id'] is None
                assert c.execute('SELECT count(*) n FROM record_draft_component_blobs WHERE record_draft_component_id=%s',(staged.component_id,)).fetchone()['n']==3
                assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==0
            raise ValueError('Cancelled before finalization')
    with db() as c:
        assert c.execute('SELECT count(*) n FROM record_drafts WHERE owner_user_id IS NULL').fetchone()['n']==0


def test_http_upload_correction_preview_download_and_reason_warning(client):
    with db() as c:
        job,dest=fixture(c);old=seed_document(c,job);role=officer(c)
    base=f"/api/v1/disposition/jobs/{job['id']}"
    docs=client.get(base+'/documents?limit=1').json()
    assert docs['total']==1 and docs['items'][0]['can_correct']
    assert client.get(base+'/documents?limit=101').status_code==422
    token=client.get(base+'/artifact-destination',params={'document_type':'external_approval_letter'}).json()['token']
    data={'command_id':str(uuid4()),'acting_role_id':str(role),'destination_token':token}
    url=base+f"/documents/{old['id']}/corrections"
    assert client.post(url,data=data,files={'file':('corrected.pdf',b'new content','application/pdf')},headers={'If-Match':str(job['version'])}).status_code==422
    result=client.post(url,data=data,files={'file':('corrected.pdf',b'new content','application/pdf')},headers={'If-Match':str(job['version']),'X-Change-Reason':'Correct previous upload'})
    assert result.status_code==201,result.text
    retry=client.post(url,data=data,files={'file':('corrected.pdf',b'new content','application/pdf')},headers={'If-Match':str(job['version']),'X-Change-Reason':'Correct previous upload'})
    assert retry.status_code==201 and retry.json()==result.json()
    current=result.json()['id']
    assert client.get(base+f'/documents/{current}/content').content==b'new content'
    assert client.get(base+f"/documents/{old['id']}/content").content==b'original evidence'
    assert client.get(base+f"/documents/{old['id']}/preview").status_code==200
    with db() as c:
        assert c.execute('SELECT count(*) n FROM record_drafts WHERE owner_user_id IS NULL').fetchone()['n']==0


def test_current_authorization_hides_document_rows_and_destination_names(client):
    with db() as c:
        with c.transaction(force_rollback=True):
            job,dest=fixture(c);old=seed_document(c,job)
            # Keep the job assignment/role, withdraw the relevant content view
            # privilege from all current profiles. No role gets an implied grant.
            c.execute("DELETE FROM profile_privileges WHERE privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
            assert artifacts.page(c,job['id'],limit=25,offset=0)['items']==[]
            with pytest.raises(HTTPException) as error:artifacts.document(c,job['id'],old['id'])
            assert error.value.status_code==404
            c.execute("DELETE FROM profile_privileges WHERE privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
            public=artifacts.public_destination(c,job['id'],'external_approval_letter')
            assert public['ready'] and public['destination'] is None
            assert not any(k in public for k in ('aggregation_id','classification_id','scheme_id'))


def test_concurrent_closure_blocks_stale_save_and_rolls_back_governed_rows():
    from concurrent.futures import TimeoutError
    with db() as c:
        job,dest=fixture(c);preview=artifacts.destination(c,job['id'],'external_approval_letter')
    def attempt():
        with db() as c:
            actor(c)
            return seed_document(c,job,preview=preview)
    with db() as closing,ThreadPoolExecutor(max_workers=1) as executor:
        actor(closing)
        closing.execute('UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=%s',(dest,))
        future=executor.submit(attempt)
        try:
            with pytest.raises(TimeoutError):future.result(timeout=.15)
        finally:closing.commit()
        with pytest.raises(psycopg.Error,match='disposition_destination_open_root_missing'):future.result(timeout=10)
    with db() as c:
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==0
        assert c.execute("SELECT count(*) n FROM disposition_private.command_receipts WHERE operation='document_save'").fetchone()['n']==0


def test_concurrent_grouped_settings_change_never_mixes_scheme_and_destination():
    from concurrent.futures import TimeoutError
    with db() as c:
        job,dest=fixture(c);preview=artifacts.destination(c,job['id'],'external_approval_letter')
        scheme=c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES('NEXT','Next scheme',CURRENT_TIMESTAMP) RETURNING id").fetchone()['id']
        cl=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'NEXT','Next destination',true) RETURNING id",(scheme,)).fetchone()['id']
        other=root(c,cl)
    def attempt():
        with db() as c:
            actor(c);return seed_document(c,job,preview=preview)
    with db() as changing,ThreadPoolExecutor(max_workers=1) as executor:
        actor(changing);configure(changing,evidence=cl,reports=cl,scheme=scheme)
        future=executor.submit(attempt)
        try:
            with pytest.raises(TimeoutError):future.result(timeout=.15)
        finally:changing.commit()
        with pytest.raises(HTTPException) as error:future.result(timeout=10)
        assert error.value.detail['code']=='disposition_destination_changed'
    with db() as c:
        actor(c);snap=artifacts.destination(c,job['id'],'external_approval_letter')
        assert (snap['scheme_id'],snap['classification_id'],snap['aggregation_id'])==(scheme,cl,other)
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==0


def test_evidence_cannot_be_admitted_into_its_own_destroyed_unit():
    from backend.services.api.tests.test_disposition_membership import admit
    from backend.services.api.disposition.eligibility import evaluate_root,worker_actor
    with db() as c:
        job,dest=fixture(c);seed_document(c,job)
        c.execute("UPDATE aggregations SET date_closed='2026-01-01' WHERE id=%s",(dest,))
        # Due root's governing rule is 5 years, created in 2024; make it due
        # using the ordinary rule path, rather than overriding stored status.
        c.execute("UPDATE classification_retention_rules SET current_period_years=0 WHERE classification_id=1")
        worker_actor(c);evaluate_root(c,dest);actor(c)
        with pytest.raises(psycopg.Error,match='disposition_evidence_inside_job'),c.transaction():admit(c,job['id'],[dest])
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'",(job['id'],)).fetchone()['n']==0


def test_content_set_and_segment_mutations_cannot_remove_original_upload():
    with db() as c:
        job,dest=fixture(c);old=seed_document(c,job)
        content=c.execute('SELECT active_content_set_id FROM digital_components WHERE id=%s',(old['digital_component_id'],)).fetchone()['active_content_set_id']
        for sql,params in [
          ('DELETE FROM digital_component_content_sets WHERE id=%s',(content,)),
          ('DELETE FROM digital_component_blobs WHERE content_set_id=%s',(content,)),
          ("INSERT INTO digital_component_blobs(content_set_id,segment_no,segment_size,content) VALUES(%s,1,1,%s)",(content,b'x')),
          ("UPDATE digital_components SET content_status='deleted' WHERE id=%s",(old['digital_component_id'],))]:
            with pytest.raises(psycopg.Error,match='disposition_evidence_version_preserved'),c.transaction():c.execute(sql,params)


def test_manager_can_correct_in_later_task_and_previous_record_redacts_history():
    from backend.services.api.tests.test_disposition_foundation import command
    from backend.services.api.disposition import queries
    with db() as c:
        job,dest=fixture(c);old=seed_document(c,job)
        # Valid protected transitions build a later-stage fixture. These are
        # private foundation commands, never public review endpoints.
        for stage in ('records_manager_review','external_approval_pending'):
            command(c,'review_decide',lambda c,stage=stage:dict(c.execute('UPDATE disposition_jobs SET workflow_stage=%s WHERE id=%s RETURNING version',(stage,job['id'])).fetchone()))
        current_job=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
        other=c.execute("INSERT INTO users(name,email) VALUES('Other person','other@test.invalid') RETURNING id").fetchone()['id']
        mgr=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance,profile_id) SELECT 1,'manager-correction','Records Manager',true,id FROM profiles WHERE code='INFO_GOV_MGR' RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s),(%s,%s)',(other,mgr,other,officer(c)))
        actor(c,other)
        assert not c.execute('SELECT disposition_private.can_correct_evidence(%s,%s) allowed',(job['id'],officer(c))).fetchone()['allowed']
        with stage_governed_upload(uploaded(b'manager correction'),load_snapshot(c),connection_factory=db) as staged:
            corrected=artifacts.correct(c,job_id=job['id'],document_id=old['id'],expected_version=current_job['version'],command_id=uuid4(),acting_role_id=mgr,reason='Correct in later external approval task',staged=staged,preview=artifacts.public_destination(c,job['id'],'external_approval_letter')['token'])
        assert c.execute('SELECT workflow_stage FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()['workflow_stage']=='external_approval_pending'
        event=c.execute("SELECT * FROM event_history WHERE operation='EVIDENCE_CORRECTED'").fetchone()
        assert event['actor_user_id']==other and event['metadata']['acting_role_id']==mgr
        assert any(x['operation']=='EVIDENCE_CORRECTED' for x in queries.history(c,job['id'],limit=100,offset=0)['items'])
        actor(c)
        high=c.execute('SELECT id FROM security_levels ORDER BY level_number DESC LIMIT 1').fetchone()['id']
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,dest))
        c.execute('UPDATE records SET security_level_id=%s WHERE id=%s',(high,old['record_id']))
        actor(c,other)
        assert not c.execute('SELECT current_user_can_view_record(%s) allowed',(old['record_id'],)).fetchone()['allowed']
        # Both versions share the same destination in this fixture, but retain
        # individual record security. The current record remains G and visible.
        assert c.execute('SELECT current_user_can_view_record(%s) allowed',(corrected['record_id'],)).fetchone()['allowed']
        protected=c.execute('SELECT metadata FROM authorized_event_history WHERE id=%s',(event['id'],)).fetchone()['metadata']
        assert protected=={'redacted':True,'reason':'resource_access_denied'}


@pytest.mark.parametrize('queued',[False,True])
def test_task_recipient_can_preview_without_management_but_cannot_correct(queued):
    from backend.services.api.tests.test_disposition_foundation import make_task
    with db() as c:
        with c.transaction(force_rollback=True):
            job,dest=fixture(c);old=seed_document(c,job)
            make_task(c,job['id'],role=1 if queued else None,user=None if queued else 1)
            c.execute("DELETE FROM profile_privileges WHERE privilege_id=(SELECT id FROM privileges WHERE code='disposition.jobs.manage')")
            assert not c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']
            page=artifacts.page(c,job['id'],limit=25,offset=0)
            assert page['items'][0]['can_preview'] and not page['items'][0]['can_correct']
            assert artifacts.document(c,job['id'],old['id'])['record_id']==old['record_id']
            assert artifacts.correction_roles(c,job['id'])==[]


def test_document_sorting_is_server_bounded_and_whitelisted(client):
    with db() as c:
        job,dest=fixture(c);seed_document(c,job,'destruction_request');seed_document(c,job,'external_approval_letter')
        first=artifacts.page(c,job['id'],limit=1,offset=0,sort='type_label',descending=False)
        second=artifacts.page(c,job['id'],limit=1,offset=1,sort='type_label',descending=False)
        assert first['items'][0]['document_type']=='destruction_request'
        assert second['items'][0]['document_type']=='external_approval_letter'
        with pytest.raises(HTTPException):artifacts.page(c,job['id'],limit=1,offset=0,sort='DROP TABLE records')
    assert client.get(f"/api/v1/disposition/jobs/{job['id']}/documents",params={'sort':'not-a-column'}).status_code==422


def test_initial_artifact_retry_binds_bytes_type_and_provenance():
    with db() as c:
        job,dest=fixture(c);key=uuid4();settings=load_snapshot(c)
        preview=artifacts.public_destination(c,job['id'],'external_approval_letter')['token']
        results=[]
        for _ in range(2):
            with stage_governed_upload(uploaded(b'initial'),settings,connection_factory=db) as staged:
                results.append(artifacts.register(c,job_id=job['id'],expected_version=job['version'],document_type='external_approval_letter',command_id=key,
                  acting_role_id=officer(c),reason='Save original evidence',staged=staged,preview=preview,provenance={'source':'acceptance'}))
        assert results[0]==results[1] and c.execute('SELECT count(*) n FROM records').fetchone()['n']==1
        with stage_governed_upload(uploaded(b'different bytes'),settings,connection_factory=db) as staged:
            with pytest.raises(psycopg.Error,match='disposition_command_conflict'),c.transaction():
                artifacts.register(c,job_id=job['id'],expected_version=job['version'],document_type='external_approval_letter',command_id=key,
                  acting_role_id=officer(c),reason='Save original evidence',staged=staged,preview=preview,provenance={'source':'acceptance'})


def test_generated_report_and_digital_certificate_store_in_distinct_governed_destinations():
    with db() as c:
        job,evidence_root=fixture(c)
        cl=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'REPORTS','Generated reports',true) RETURNING id").fetchone()['id']
        report_root=root(c,cl);configure(c,reports=cl)
        report=seed_document(c,job,'destruction_request');certificate=seed_document(c,job,'digital_destruction_certificate')
        rows=c.execute('SELECT d.*,r.aggregation_id actual_root FROM disposition_job_documents d JOIN records r ON r.id=d.record_id ORDER BY d.id').fetchall()
        assert [(x['origin'],x['aggregation_id'],x['actual_root'],x['classification_id']) for x in rows]==[
          ('generated',report_root,report_root,cl),('generated',evidence_root,evidence_root,1)]
        assert all(x['classification_scheme_id']==1 and x['acting_role_id']==officer(c) and x['provenance']=={'source':'phase11 acceptance'} for x in rows)


def test_http_stale_job_version_returns_conflict_and_leaves_original_only(client):
    with db() as c:
        job,dest=fixture(c);old=seed_document(c,job);role=officer(c)
    base=f"/api/v1/disposition/jobs/{job['id']}"
    token=client.get(base+'/artifact-destination',params={'document_type':'external_approval_letter'}).json()['token']
    result=client.post(base+f"/documents/{old['id']}/corrections",data={'command_id':str(uuid4()),'acting_role_id':str(role),'destination_token':token},
      files={'file':('corrected.pdf',b'not saved','application/pdf')},headers={'If-Match':str(job['version']+1),'X-Change-Reason':'Stale correction should fail safely'})
    assert result.status_code==409 and result.json()['detail']['code']=='disposition_stale_version'
    with db() as c:
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM disposition_job_documents').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM record_drafts WHERE owner_user_id IS NULL').fetchone()['n']==0
