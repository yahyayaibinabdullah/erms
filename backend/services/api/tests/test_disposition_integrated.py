"""Phase 23 journeys across review, evidence, execution and completion boundaries.

Run through tools/run_disposable_acl_tests.py on either a canonical database or
the explicit upgrade path. Release overrides affect that disposable DB only.
"""
import json
from uuid import uuid4

import pytest
import psycopg

from backend.services.api.disposition import completion, destruction, documents, email
from backend.services.api.tests import test_disposition_workflow as fixtures
from backend.services.api.tests.test_disposition_approval import approve
from backend.services.api.tests.test_disposition_artifacts import configure, root as destination
from backend.services.api.tests.test_disposition_communications import smtp, enqueue
from backend.services.api.tests.test_disposition_external import generate, decision
from backend.services.api.tests.test_disposition_membership import actor, db, job_version
from backend.services.api.tests.test_disposition_physical import report, confirmation
from backend.services.api.tests.test_disposition_recovery import make_unit
from backend.services.api.tests.test_disposition_review import (
    seeded, save, create, submit, claim, decide, task, officer, version,
)
from backend.services.api.tests.test_disposition_destruction import request


def reach_manager(c, job, route):
    if route == 'records_manager_only':
        return
    submit(c, job)
    while task(c, job['id'])['workflow_stage'] != 'records_manager_review':
        claim(c, job)
        decide(c, job)
    claim(c, job)


@pytest.fixture(autouse=True)
def isolated_journey(monkeypatch):
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine, 'render', lambda *args: (preview_pdf(), {'renderer': 'integrated-fixture'}))
    yield


@pytest.mark.parametrize('route,file_admin', [
    ('standard', 'direct'), ('standard', 'inherited'), ('standard', 'none'),
    ('simplified', 'none'), ('records_manager_only', 'none'),
])
@pytest.mark.parametrize('medium', ['physical', 'digital', 'mixed'])
def test_complete_journey_repeated_corrections_saved_policy_and_final_evidence(client, monkeypatch, route, file_admin, medium):
    monkeypatch.setattr(fixtures, 'ready', lambda c: make_unit(c, medium))
    with db() as c:
        job, root, um, fa, mgr = seeded(c, route, fa=file_admin != 'none')
        if file_admin == 'inherited':
            # The owner inherits its File Administrator from its parent; its
            # own Unit Manager remains the nearest designated reviewer.
            parent = c.execute("INSERT INTO org_units(code,name) VALUES(%s,'Inherited review ancestor') RETURNING id", (uuid4().hex,)).fetchone()['id']
            c.execute('UPDATE org_units SET parent_org_unit_id=%s,file_administrator_role_id=NULL WHERE id=1', (parent,))
            ancestor_role = fixtures.role(c, 'ancestor-file-admin', owner=parent)
            c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s', (ancestor_role, parent))
        configure(c)
        destination(c)
        smtp(c)
        acting = mgr if route == 'records_manager_only' else officer(c)
        proposal = create(c, root, 'local_retention_override', {
            'current_period_years': 6, 'intermediate_period_years': 0,
            'final_disposition': 'destruction', 'instructions': None,
        })
        saved = save(c, job, acting=acting, changes=[proposal], review_notes='Partial draft', note_version=0, overall_reason='')
        pid = saved['changes'][0]['id']
        save(c, job, acting=acting, changes=[{
            'action': 'revise', 'proposal_id': pid, 'expected_version': 1,
            'target_version': version(c, root), 'proposed_values': proposal['proposed_values'],
            'reason': 'Clarify the approved retention review',
        }])
        stage = task(c, job['id'])['workflow_stage']
        # A later global route change must not rewrite this job's route.
        fixtures.set_route(c, 'simplified' if route != 'simplified' else 'standard')
        c.commit()
    # New connection models navigation/restart: Save neither approves nor
    # executes the proposal, and a partially written overall reason persists.
    with db() as c:
        actor(c)
        assert task(c, job['id'])['workflow_stage'] == stage
        assert c.execute('SELECT current_period_years FROM aggregation_retention_rules WHERE aggregation_id=%s', (root,)).fetchone()['current_period_years'] == 5
        assert c.execute('SELECT proposal_state,version FROM disposition_review_proposals WHERE id=%s', (pid,)).fetchone() == {'proposal_state': 'active', 'version': 2}
        if route != 'records_manager_only':
            for cycle in range(2):
                reach_manager(c, job, route)
                decide(c, job, 'rejected', f'Internal correction {cycle + 1}')
                assert task(c, job['id'])['workflow_stage'] == 'officer_correction'
        request_ids = []
        for cycle in range(3):
            reach_manager(c, job, route)
            result = approve(c, job, mgr, **({'overall_reason': 'Review complete membership'} if route == 'records_manager_only' else {}))
            generated = generate(c, job, mgr, result['round_id'])
            request_ids.append(generated['request_document_id'])
            if cycle < 2:
                decision(c, job, outcome='rejected', notes=f'External correction {cycle + 1}', acting=acting)
        assert len(set(request_ids)) == 3
        assert c.execute('SELECT review_route FROM disposition_jobs WHERE id=%s', (job['id'],)).fetchone()['review_route'] == route
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE job_id=%s AND proposal_state='executed'", (job['id'],)).fetchone()['n'] >= 1
        assert c.execute('SELECT current_period_years FROM aggregation_retention_rules WHERE aggregation_id=%s', (root,)).fetchone()['current_period_years'] == 6
        enqueue(c, job, request_ids[-1], acting)
        c.commit()
    sent = []
    def transport(settings, message):
        sent.append((settings['recipient'], list(message.iter_attachments())[0].get_payload(decode=True)))
        return 'smtp_accepted', None, 250, 'INTEGRATED_FIXTURE'
    assert email.process_one(db, transport=transport)
    with db() as c:
        actor(c)
        decision(c, job, number='INTEGRATED/' + uuid4().hex[:9], acting=acting)
        if medium != 'digital':
            report(c, job, mgr)
            claim(c, job)

            c.commit()
            actor(c)
            confirmation(c, job, mgr, ref='PHYSICAL/' + uuid4().hex[:10])
            c.commit()
            actor(c)
        if medium != 'physical':
            claim(c, job)

            request(c, job, mgr)
    if medium != 'physical':
        assert destruction.process_one(db)
        assert completion.process_one(db)
    with db() as c:
        actor(c)
        assert c.execute('SELECT lifecycle_state FROM disposition_jobs WHERE id=%s', (job['id'],)).fetchone()['lifecycle_state'] == 'completed'
        assert c.execute('SELECT disposition_status FROM aggregations WHERE id=%s', (root,)).fetchone()['disposition_status'] == 10
        snapshots = c.execute('SELECT membership_snapshot,proposal_snapshot FROM disposition_review_decisions WHERE job_id=%s', (job['id'],)).fetchall()
        assert snapshots and 'Recovery root' not in json.dumps(snapshots, default=str) and 'Remaining material' not in json.dumps(snapshots, default=str)
        assert c.execute("SELECT membership_state FROM disposition_job_memberships WHERE job_id=%s", (job['id'],)).fetchone()['membership_state'] == 'completed_history'
        digital = c.execute("SELECT * FROM disposition_job_documents WHERE job_id=%s AND document_type='digital_destruction_certificate'", (job['id'],)).fetchall()
        assert len(digital) == (0 if medium == 'physical' else 1)
        assert c.execute('SELECT count(*) n FROM disposition_external_approvals WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 3
        with pytest.raises(psycopg.Error, match='disposition_.*required|disposition_command_scope_invalid'), c.transaction():
            c.execute("UPDATE disposition_review_decisions SET proposal_snapshot='[]' WHERE job_id=%s", (job['id'],))
        if medium != 'physical':
            enqueue(c, job, digital[0]['id'], mgr)
    if medium != 'physical':
        assert email.process_one(db, transport=transport)
        response = client.get(f"/api/v1/disposition/jobs/{job['id']}/documents/{digital[0]['id']}/content")
        assert response.status_code == 200
        assert sent[-1][1] == response.content
        with db() as c:
            assert c.execute("SELECT task_state FROM disposition_tasks WHERE job_id=%s AND task_type='certificate_download'", (job['id'],)).fetchone()['task_state'] == 'completed'
    assert len(sent) == (1 if medium == 'physical' else 2)
