"""Bilingual compact proposals, distinct effects, revision metadata and redaction."""
from copy import deepcopy
import asyncio
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api,form
from frontend.webui.disposition.proposal_presenter import proposed_change
from frontend.webui.disposition.messages import text


def proposal(**values):
    return dict(id=1,version=1,redacted=False,proposal_type='make_vital',proposal_state='active',
      target_aggregation_id=10,target_record_id=None,current_values={'aggregation_number':'AGG-10','title':'Target'},
      proposed_values={},proposer_name='Original author',proposer_role_name='Records Officer',
      proposer_stage='officer_preparation',review_round=2,proposed_at='2026-10-29T07:00:00Z',
      last_revised_at=None,editor_name=None,reason='Authored reason',in_current_membership=True,**values)


def test_summaries_distinguish_effects_endpoints_and_preserve_redaction(host):
    with host:
        base=proposal()
        security={**base,'proposal_type':'blocking_security','proposed_security_name':'Top secret'}
        assert 'Top secret' in proposed_change(security)
        retention={**base,'proposal_type':'local_retention_override','proposed_values':dict(current_period_years=0,intermediate_period_years=3,final_disposition='destruction')}
        assert all(value in proposed_change(retention) for value in ('0','3',text('destruction')))
        holds={**base,'proposal_type':'add_to_holds','current_values':{'holds':[{'code':f'HOLD-{i}','name':'Review'} for i in range(1,5)]}}
        assert 'HOLD-3' in proposed_change(holds) and 'HOLD-4' not in proposed_change(holds)
        assert text('summary_more',count=1) in proposed_change(holds)
        relation={**base,'proposal_type':'remove_aggregation_relationship','relationship_display_name':'Related to','current_values':{'relationship':{'source_id':10,'target_id':20}},'relationship_source_label':'AGG-10','relationship_target_label':'AGG-20'}
        other={**relation,'relationship_target_label':'AGG-30'}
        assert proposed_change(relation)!=proposed_change(other) and 'AGG-20' in proposed_change(relation)
        incoming={**relation,'target_record_id':7,'proposal_type':'remove_record_relationship','relationship_source_label':'REC-99','relationship_target_label':'REC-7','current_values':{'relationship':{'source_id':99,'target_id':7}}}
        assert 'REC-99' in proposed_change(incoming) and 'REC-7' not in proposed_change(incoming)
        creation={**relation,'proposal_type':'create_aggregation_relationship'}
        assert proposed_change(creation)!=proposed_change(relation)
        for kind in ('make_vital','remove_from_job'):assert proposed_change({**base,'proposal_type':kind})==text(kind)
        for partial in (True,False):
            hidden={**security,'redacted':True,'partial':partial,'proposed_security_name':'DO NOT DISCLOSE'}
            assert 'DO NOT DISCLOSE' not in proposed_change(hidden)


@pytest.mark.parametrize('revised',[False,True])
@pytest.mark.asyncio
async def test_six_columns_round_caption_and_clear_revision_details(host,monkeypatch,revised):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    row=proposal()
    if revised:row.update(editor_name='Later editor',editor_role_name='Records Manager',last_revised_at='2026-10-29T08:00:00Z')
    class ProposalApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/proposals'):
                self.reads.append((path,params));return {'items':[deepcopy(row)],'total':1}
            return await super().disposition_page(path,**params)
    f,api,_=await form(host,ProposalApi())
    table=f.proposals.table
    assert [c['name'] for c in table.columns]==['target_label','change_label','state_label','proposer_label','reason_label','actions']
    assert table.rows[0]['proposer_name']=='Original author' and table.rows[0]['proposer_role_name']=='Records Officer'
    assert any(isinstance(e,ui.label) and e.text==text('tracker_round',number=2) for e in f.body.descendants())
    assert table.rows[0]['reason_label']=='Authored reason'
    with host:
        await f.details(table.rows[0])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        labels=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert text('proposed_at') in labels and row['proposed_at'] in labels
        assert text('stage') in labels
        if revised:
            assert any('Later editor' in value and 'Records Manager' in value for value in labels)
            assert text('revised_at') in labels and row['last_revised_at'] in labels
        else:assert text('last_editor') in labels and text('not_revised') in labels
    assert not api.writes


@pytest.mark.asyncio
async def test_withdrawal_comment_shown_for_every_row_separate_from_original_reason(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    rows=[proposal(),proposal()]
    for index,row in enumerate(rows):
        row.update(id=index+1,proposal_state='withdrawn',withdrawal_reason='One comment for both proposals',reason='Original proposal reason' if index==0 else None)
    class ProposalApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/proposals'):return {'items':deepcopy(rows),'total':len(rows)}
            return await super().disposition_page(path,**params)
    f,api,_=await form(host,ProposalApi())
    assert [r['reason_label'] for r in f.proposals.table.rows]==[text('withdrawal_comment')+' · One comment for both proposals']*2
    with host:
        for index,row in enumerate(f.proposals.table.rows):
            await f.details(row)
            dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
            labels=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
            assert text('withdrawal_comment') in labels and 'One comment for both proposals' in labels
            assert text('proposal_reason') in labels
            assert ('Original proposal reason' in labels)==(index==0)
            dialog.close()
    assert not api.writes


@pytest.mark.asyncio
async def test_withdrawal_comment_redaction_and_empty_comment(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    rows=[]
    for identity,redacted,partial in [(1,False,False),(2,True,True),(3,True,False)]:
        row=proposal();row.update(id=identity,proposal_state='withdrawn',withdrawal_reason='Secret withdrawal comment' if redacted else None,redacted=redacted,partial=partial)
        if partial:row['target_summary']={'number':'AGG-10','title':'Visible target'}
        rows.append(row)
    class ProposalApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/proposals'):return {'items':deepcopy(rows),'total':len(rows)}
            return await super().disposition_page(path,**params)
    f,_,_=await form(host,ProposalApi())
    assert [r['reason_label'] for r in f.proposals.table.rows]==['—',text('restricted_text'),'—']
    with host:
        await f.details(f.proposals.table.rows[1])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert 'Secret withdrawal comment' not in [e.text for e in dialog.descendants() if isinstance(e,ui.label)]
