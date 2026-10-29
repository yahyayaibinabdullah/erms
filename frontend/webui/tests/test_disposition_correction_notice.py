"""Show the actual rejection separately from the officer's editable comments."""
from copy import deepcopy
import pytest
from nicegui import ui
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.disposition.messages import text


@pytest.mark.asyncio
@pytest.mark.parametrize('redacted',[False,True])
async def test_correction_notice_is_visible_at_task_entry_without_extra_requests_or_editing_author_text(host,redacted):
    workspace=view();workspace['job']['workflow_stage']='officer_correction'
    reason='Please correct the job.\nيرجى تصحيح العملية. <Authored text>'
    class CorrectionApi(Api):
        async def disposition_page(self,path,**params):
            result=await super().disposition_page(path,**params)
            if path.endswith('/review-work'):
                result['return_context']={'redacted':True} if redacted else dict(round_number=2,decisions=[dict(review_stage='records_manager_review',decision='rejected',reason=reason,actor_name='Records Manager',decided_at='2026-10-29T08:00:00Z')])
            return result
    api=CorrectionApi()
    async def noop(*args):pass
    with host:
        form=ReviewForm(api=api,workspace=deepcopy(workspace),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=noop,format_timestamp=str,open_resource=None)
        await form.load()
        labels=[e.text for e in form.body.descendants() if isinstance(e,ui.label)]
        assert (reason in labels) is not redacted
        if redacted:assert text('history_unavailable') in labels
        else:
            assert text('tracker_returned',stage=text('records_manager_review'),number=2) in labels
            label=next(e for e in form.body.descendants() if isinstance(e,ui.label) and e.text==reason)
            assert label.props['dir']=='auto' and 'whitespace-pre-wrap' in label.classes
        assert reason not in form.comments.value
        assert not form.dirty() and not api.writes
        assert [path for path,_ in api.reads]==['tasks/8/review-work','jobs/5/proposals']
