"""Correction tasks expose the recorded return, without altering authored work."""
import pytest
from backend.services.api.disposition import proposals
from backend.services.api.tests.test_disposition_review import db,seeded,submit,claim,decide,task


@pytest.mark.parametrize('route',['standard','simplified'])
def test_correction_work_contains_latest_manager_rejection_and_preserves_prior_round(client,route):
    with db() as c:
        job,*_=seeded(c,route)
        earlier_correction=None
        c.execute("UPDATE users SET translations=jsonb_build_object('ar',jsonb_build_object('name','مدير الوثائق')) WHERE id=1")
        for number in (1,2):
            submit(c,job,reason=f'Officer submission {number}')
            if route=='standard':claim(c,job);decide(c,job)
            claim(c,job)
            manager_task=task(c,job['id'])['id']
            reason=f'Correction {number}\nPlease revise these aggregations. <Keep authored text>'
            decide(c,job,'rejected',reason)
            correction=task(c,job['id'])
            result=proposals.work(c,correction['id'],language_tag='ar')
            latest=result['return_context']
            rejection=latest['decisions'][-1]
            assert latest['round_number']==number
            assert rejection['review_stage']=='records_manager_review'
            assert rejection['actor_name']=='مدير الوثائق'
            assert rejection['reason']==reason and rejection['decision']=='rejected'
            assert rejection['decided_at']
            assert result['submission_reason']==f'Officer submission {number}'
            assert result['own_notes'] is None
            assert not result['overall_reason']
            assert 'membership_snapshot' not in latest and 'proposal_snapshot' not in latest
            assert proposals.work(c,manager_task)['return_context'] is None
            if earlier_correction:assert proposals.work(c,earlier_correction)['return_context'] is None
            earlier_correction=correction['id']
        reasons=c.execute("SELECT reason FROM disposition_review_decisions WHERE job_id=%s AND decision='rejected' ORDER BY id",(job['id'],)).fetchall()
        assert [r['reason'] for r in reasons]==[f'Correction {n}\nPlease revise these aggregations. <Keep authored text>' for n in (1,2)]
    response=client.get(f"/api/v1/disposition/tasks/{correction['id']}/review-work")
    assert response.status_code==200,response.text
    assert response.json()['return_context']['decisions'][-1]['reason']==reason


def test_preparation_does_not_read_round_context(client,monkeypatch):
    from backend.services.api.disposition import progress
    with db() as c:
        job,*_=seeded(c)
        def unexpected(*a,**kw):raise AssertionError('Preparation must not load return history')
        monkeypatch.setattr(progress,'page',unexpected)
        assert proposals.work(c,task(c,job['id'])['id'])['return_context'] is None
