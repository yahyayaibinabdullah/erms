"""Bulk actions reuse existing gates, with atomicity and exact-payload retries."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
import psycopg
from backend.services.api.disposition import membership, proposals
from backend.services.api.tests.test_disposition_membership import db, actor, ready, admit, job_version, kwargs, member
from backend.services.api.tests.test_disposition_workflow import seeded, task
from backend.services.api.tests.test_disposition_review import create, save, officer, submit
from backend.services.api.tests.test_disposition_foundation import version


def selection(c,roots):
    return [dict(membership_id=member(c,root)['id'],expected_version=member(c,root)['version'],root_version=version(c,root)) for root in roots]


def fixture(c):
    job,first,*_=seeded(c)
    second,*_=ready(c);admit(c,job['id'],[second])
    return job,[first,second]


def test_bulk_removal_status_history_and_same_receipt_retry(client):
    with db() as c:
        job,roots=fixture(c);items=selection(c,roots)
        args=kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=items)
        before=c.execute('SELECT count(*) n FROM records').fetchone()['n']
        result=membership.remove_many(c,**args)
        assert len(result['items'])==2
        assert not c.execute("SELECT 1 FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'",(job['id'],)).fetchone()
        assert c.execute('SELECT count(*) n FROM records').fetchone()['n']==before
        assert {r['disposition_status'] for r in c.execute('SELECT disposition_status FROM aggregations WHERE id=ANY(%s)',(roots,))}=={2}
        events=c.execute("SELECT entity_id,metadata FROM event_history WHERE operation='MEMBERSHIP_REMOVE' AND metadata->>'command_id'=%s",(str(args['command_id']),)).fetchall()
        assert {r['entity_id'] for r in events if 'root_aggregation_id' in (r['metadata'].get('after') or {})}=={i['membership_id'] for i in items}
        event_count=c.execute("SELECT count(*) n FROM event_history WHERE metadata->>'command_id'=%s",(str(args['command_id']),)).fetchone()['n']
        assert membership.remove_many(c,**args)==result
        assert c.execute("SELECT count(*) n FROM event_history WHERE metadata->>'command_id'=%s",(str(args['command_id']),)).fetchone()['n']==event_count


@pytest.mark.parametrize('invalid',['stale_root','stale_member','foreign_job','duplicate'])
def test_bulk_removal_rejects_complete_selection_without_side_effects(client,invalid):
    with db() as c:
        job,roots=fixture(c);items=selection(c,roots)
        if invalid=='stale_root':items[1]['root_version']-=1
        if invalid=='stale_member':items[1]['expected_version']+=1
        if invalid=='foreign_job':items[1]['membership_id']=999999
        if invalid=='duplicate':items[1]=dict(items[0])
        current=job_version(c,job['id']);key=uuid4()
        with pytest.raises(HTTPException) as error:
            membership.remove_many(c,**{**kwargs(job_id=job['id'],expected_version=current,items=items),'command_id':key})
        assert error.value.status_code in (409,422)
        assert job_version(c,job['id'])==current
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'",(job['id'],)).fetchone()['n']==2
        assert not c.execute('SELECT 1 FROM disposition_private.command_receipts WHERE command_id=%s',(key,)).fetchone()


def test_bulk_removal_rolls_back_late_sql_failure(client,monkeypatch):
    with db() as c:
        job,roots=fixture(c);items=selection(c,roots);before=job_version(c,job['id']);original=c.execute;calls=[]
        def execute(query,params=None,*args,**kw):
            if query.startswith('SELECT disposition_private.remove_member('):
                calls.append(params)
                if len(calls)==2:raise RuntimeError('late removal failure')
            return original(query,params,*args,**kw)
        monkeypatch.setattr(c,'execute',execute)
        with pytest.raises(RuntimeError,match='late removal failure'):
            membership.remove_many(c,**kwargs(job_id=job['id'],expected_version=before,items=items))
        assert len(calls)==2 and job_version(c,job['id'])==before
        assert original("SELECT count(*) n FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active'",(job['id'],)).fetchone()['n']==2


def test_bulk_removal_forbidden_during_review_and_reason_required(client):
    with db() as c:
        job,roots=fixture(c);items=selection(c,roots)
        with pytest.raises(HTTPException):membership.remove_many(c,**{**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=items),'reason':''})
        submit(c,job)
        with pytest.raises(psycopg.Error,match='membership_stage|task'):
            membership.remove_many(c,**kwargs(job_id=job['id'],expected_version=job_version(c,job['id']),items=items))


@pytest.mark.parametrize('comment',[None,'One comment for both proposals','تعليق سحب المقترحين'])
def test_bulk_proposal_creation_withdrawal_history_and_rollback(client,comment):
    with db() as c:
        job,roots=fixture(c);t=task(c,job['id'])
        args=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],acting_role_id=officer(c),command_id=uuid4(),
                  changes=[create(c,root,'remove_from_job',reason='Original proposal reason' if index==0 else None) for index,root in enumerate(roots)],bulk=True)
        added=proposals.save(c,**args)
        assert len(added['changes'])==2 and proposals.save(c,**args)==added
        assert c.execute("SELECT count(*) n FROM disposition_job_memberships WHERE membership_state='active' AND job_id=%s",(job['id'],)).fetchone()['n']==2
        selected=[dict(action='withdraw',proposal_id=row['id'],expected_version=row['version'],reason=comment) for row in added['changes']]
        selected[1]['expected_version']+=1
        with pytest.raises(HTTPException) as error:save(c,job,changes=selected,bulk=True)
        assert error.value.detail['code']=='disposition_bulk_selection_changed'
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE proposal_state='active' AND job_id=%s",(job['id'],)).fetchone()['n']==2
        selected[1]['expected_version']-=1
        t=task(c,job['id']);key=uuid4()
        withdrawal=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],acting_role_id=officer(c),command_id=key,changes=selected,bulk=True)
        result=proposals.save(c,**withdrawal)
        assert all(row['proposal_state']=='withdrawn' for row in result['changes'])
        stored=c.execute('SELECT reason,withdrawal_reason FROM disposition_review_proposals WHERE job_id=%s ORDER BY id',(job['id'],)).fetchall()
        assert [row['reason'] for row in stored]==['Original proposal reason',None]
        assert all(row['withdrawal_reason']==comment for row in stored)
        projected=proposals.page(c,job['id'],limit=25,offset=0,state='withdrawn')['items']
        assert len(projected)==2 and all(row['withdrawal_reason']==comment for row in projected)
        assert proposals.save(c,**withdrawal)==result
        events=c.execute("SELECT count(*) n FROM event_history WHERE entity_type='disposition_review_proposal' AND metadata->>'command_id'=%s",(str(key),)).fetchone()['n']
        assert events==2


def test_bulk_proposal_rejects_mixed_operation_and_duplicate_roots(client):
    with db() as c:
        job,roots=fixture(c)
        for changes in ([],[create(c,roots[0],'remove_from_job')]*2,[create(c,roots[0],'make_vital')]):
            with pytest.raises(HTTPException) as error:save(c,job,changes=changes,bulk=True)
            assert error.value.status_code==422
        assert not c.execute('SELECT 1 FROM disposition_review_proposals').fetchone()


def test_bulk_http_membership_removal_one_winner_and_safe_retry(client):
    from concurrent.futures import ThreadPoolExecutor
    with db() as c:
        job,roots=fixture(c);items=selection(c,roots);expected=job_version(c,job['id'])
    path=f"/api/v1/disposition/jobs/{job['id']}/memberships/remove"
    payloads=[{'items':items,'acting_role_id':1,'command_id':str(uuid4())} for _ in range(2)]
    headers={'If-Match':str(expected),'X-Change-Reason':'Separate job preparation'}
    assert client.post(path,json=payloads[0],headers={'X-Change-Reason':'Missing version'}).status_code==428
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda payload:client.post(path,json=payload,headers=headers),payloads))
    assert sorted(response.status_code for response in responses)==[200,409],[r.text for r in responses]
    winner=next(index for index,response in enumerate(responses) if response.status_code==200)
    assert client.post(path,json=payloads[winner],headers=headers).json()==responses[winner].json()


def test_bulk_audit_upgrade_preserves_history_and_matches_canonical(client):
    from pathlib import Path
    with db() as c:
        job,roots=fixture(c);save(c,job,changes=[create(c,roots[0])])
        canonical=c.execute("SELECT pg_get_functiondef('disposition_private.audit_review_work()'::regprocedure) value").fetchone()['value']
        # Recreate the immediately preceding function body, then upgrade occupied data.
        former=canonical.replace("'command_id',(SELECT command_id FROM disposition_private.command_context WHERE transaction_id=txid_current()),",'')
        assert former!=canonical;c.execute(former)
        before=c.execute('SELECT to_jsonb(e) value FROM event_history e ORDER BY id').fetchall()
        migration=Path('database/migrations/097_bulk_disposition_audit_link.sql').read_text().replace('BEGIN;\n','',1).removesuffix('COMMIT;\n')
        for _ in range(2):
            c.execute(migration,prepare=False)
            assert c.execute('SELECT to_jsonb(e) value FROM event_history e ORDER BY id').fetchall()==before
            assert c.execute("SELECT pg_get_functiondef('disposition_private.audit_review_work()'::regprocedure) value").fetchone()['value']==canonical


def test_bulk_withdrawal_rechecks_related_visibility_and_rolls_back_visible_peer(client):
    from backend.services.api.tests.test_disposition_review import claim
    with db() as c:
        job,root,*_=seeded(c,'simplified');other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        changes=[create(c,root),create(c,root,'create_aggregation_relationship',dict(direction='outgoing',related_aggregation_id=other,relationship_type_id=kind))]
        added=save(c,job,changes=changes)['changes'];submit(c,job);claim(c,job)
        level=c.execute("INSERT INTO security_levels(level_number,code,name) SELECT max(level_number)+1,%s,'Restricted related resource' FROM security_levels RETURNING id",('BULK-'+uuid4().hex,)).fetchone()['id']
        c.execute("SELECT set_config('app.security_level_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(level,other))
        c.execute("SELECT set_config('app.security_level_change_authorized','',true)")
        selected=[dict(action='withdraw',proposal_id=r['id'],expected_version=r['version']) for r in added]
        with pytest.raises(HTTPException) as error:save(c,job,changes=selected,bulk=True)
        assert error.value.detail['item_ids']==[added[1]['id']]
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE job_id=%s AND proposal_state='active'",(job['id'],)).fetchone()['n']==2
        assert save(c,job,changes=[selected[0]],bulk=True)['changes'][0]['proposal_state']=='withdrawn'


def test_bulk_task_claim_and_revoked_role_are_enforced(client):
    from backend.services.api.tests.test_disposition_workflow import role,person,act
    from backend.services.api.tests.test_disposition_review import claim
    with db() as c:
        job,root,*_=seeded(c);limited=role(c,'bulk-review-only','FILE_ADMIN');other=person(c)
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(other,limited))
        c.execute('UPDATE org_units SET managing_role_id=%s WHERE id=1',(limited,))
        submit(c,job);claim(c,job);actor(c,other)
        with pytest.raises(psycopg.Error,match='disposition_task_claim_required'):
            save(c,job,acting=limited,changes=[create(c,root,'remove_from_job')],bulk=True)
        actor(c);act(c,task(c,job['id']),'release',limited);actor(c,other);claim(c,job)
        added=save(c,job,acting=limited,changes=[create(c,root,'remove_from_job')],bulk=True)['changes'][0]
        c.execute('DELETE FROM user_role_assignments WHERE user_id=%s AND role_id=%s',(other,limited))
        with pytest.raises(psycopg.Error):
            save(c,job,acting=limited,changes=[dict(action='withdraw',proposal_id=added['id'],expected_version=added['version'])],bulk=True)
        assert c.execute('SELECT proposal_state FROM disposition_review_proposals WHERE id=%s',(added['id'],)).fetchone()['proposal_state']=='active'
