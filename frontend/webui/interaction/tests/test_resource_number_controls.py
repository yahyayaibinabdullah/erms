"""Existing numbering feedback must preserve drafts and respect changed context."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.resource_number_controls import build_number_controls
from frontend.webui.resource_number_controls import generation_intent,numbers_busy,set_automatic_number
from frontend.webui.i18n_catalogue import render_message

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('lookup_fails',[False,True])
async def test_duplicate_feedback_preserves_draft_until_suggestion_is_chosen(user,lookup_fails):
    api=SimpleNamespace(request=AsyncMock(side_effect=ApiError(503,'Unavailable')) if lookup_fails else
                        AsyncMock(return_value={'suggested_number':'NEXT'}))
    holder={}
    @ui.page('/duplicate-number')
    def page():
        holder['input']=ui.input('Number',value='DUPLICATE')
        holder['owner']=build_number_controls(api,show_api_error=lambda error:ui.notify(str(error)))
    await user.open('/duplicate-number')
    with user:
        assert await holder['owner'].show_number_conflict(ApiError(409,{'code':'duplicate_resource_number'}),
            'aggregations',holder['input'],root=True)
    assert holder['input'].value=='DUPLICATE'
    api.request.assert_awaited_once_with('GET','/api/v1/number-suggestions/aggregations',params={'number':'DUPLICATE','root':True})
    if lookup_fails:
        await user.should_not_see(render_message('webui.number_conflict.use'))
        user.find(render_message('webui.number_conflict.close')).click()
    else:
        user.find(render_message('webui.number_conflict.use')).click()
        await user.should_see('NEXT')
        assert holder['input'].value=='NEXT'

@pytest.mark.parametrize('changed',['number','parent'])
async def test_late_suggestion_does_not_replace_changed_draft_or_parent(user,changed):
    started,release=asyncio.Event(),asyncio.Event()
    async def request(*args,**kwargs):
        started.set();await release.wait();return {'suggested_number':'NEXT'}
    holder={}
    @ui.page('/number-suggestion')
    def page():
        holder['input']=ui.input('Number',value='DRAFT')
        holder['parent']=ui.select({1:'First',2:'Second'},value=1)
        owner=build_number_controls(SimpleNamespace(request=request),show_api_error=lambda error:ui.notify(str(error)))
        owner.add_number_suggestion(holder['input'],'records',{'aggregation_id':holder['parent']})
    await user.open('/number-suggestion')
    user.find(render_message('webui.number_conflict.suggest')).click()
    await asyncio.wait_for(started.wait(),5)
    with user:
        if changed=='number':holder['input'].set_value('CHANGED')
        else:holder['parent'].set_value(2)
    release.set();await asyncio.sleep(.03)
    assert holder['input'].value==('CHANGED' if changed=='number' else 'DRAFT')


@pytest.mark.parametrize('changed',['edit_revert','save','closed','type','role'])
async def test_suggestion_cannot_arrive_after_edits_save_close_or_creation_context_changes(user,changed):
    started,release=asyncio.Event(),asyncio.Event()
    holder={'active':True,'type_id':7,'creator_acl_role_id':3}
    async def request(*args,**kwargs):
        assert kwargs['params']=={'parent_aggregation_id':1,'type_id':7,'creator_acl_role_id':3}
        started.set()
        await release.wait()
        return {'suggested_number':'R10','generation_intent':{'source':'generator','generator_id':12}}
    @ui.page('/stale-code')
    def page():
        control=holder['input']=ui.input('Number',value='DRAFT')
        parent=ui.select({1:'First'},value=1)
        holder['controls']={'record_number':control,'aggregation_id':parent}
        owner=build_number_controls(SimpleNamespace(request=request),show_api_error=lambda error:ui.notify(str(error)))
        owner.add_number_suggestion(control,'records',holder['controls'],
            creation_context=lambda:{'type_id':holder['type_id'],'creator_acl_role_id':holder['creator_acl_role_id']},
            active=lambda:holder['active'])
    await user.open('/stale-code')
    user.find(render_message('webui.number_conflict.suggest')).click()
    await asyncio.wait_for(started.wait(),5)
    with user:
        if changed=='edit_revert':
            holder['input'].set_value('EDITED')
            holder['input'].set_value('DRAFT')
        elif changed=='save':
            numbers_busy(holder['controls'],True)
            numbers_busy(holder['controls'],False)
        elif changed=='closed':holder['active']=False
        else:holder['type_id' if changed=='type' else 'creator_acl_role_id']=99
    release.set()
    await asyncio.sleep(.03)
    assert holder['input'].value=='DRAFT'
    assert generation_intent(holder['controls'])=={}


async def test_automatic_origin_survives_programmatic_fill_and_clears_on_manual_edit(user):
    holder={}
    @ui.page('/code-origin')
    def page():
        holder['input']=ui.input('Number')
    await user.open('/code-origin')
    controls={'record_number':holder['input']}
    with user:
        set_automatic_number(holder['input'],' R10 ',{'source':'generator','generator_id':12})
    assert generation_intent(controls)=={'record_number':{'source':'generator','generator_id':12}}
    with user:holder['input'].set_value('MANUAL')
    assert generation_intent(controls)=={}
