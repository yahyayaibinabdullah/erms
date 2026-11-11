"""Saved component controls retain permissions, paging, writes and failure recovery."""
import ast,asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def build(values):
    from frontend.webui.components import build_components
    return build_components(**values,error_message=host.error_message,render_component_cards=host.render_component_cards)

async def setup(user,*,closed=False,medium='digital',allowed=True):
    rows=[dict(id=i,version=3,file_name=f'Fixture {i}.png',mime_type='image/png',content_status='available',component_order=i,size_in_bytes=1) for i in (1,2)]
    caps={k:allowed for k in ('add_component','view_component','download_component','print_component','reindex_components','reorder_components','remove_component')}
    api=SimpleNamespace(effective_aggregation_closure=AsyncMock(return_value={'aggregation_number':'CLOSED','title':'Closed fixture'} if closed else None),resource_capabilities=AsyncMock(return_value=caps),component_page=AsyncMock(side_effect=lambda *a,**kw:{'items':list(rows),'total':len(rows)}),component_indexing_status=AsyncMock(return_value={'status':'indexed'}),move_component=AsyncMock(),delete_component=AsyncMock(),download_component=AsyncMock(return_value=b'fixture bytes'),reindex_component=AsyncMock(return_value={'status':'queued'}),upload_component=AsyncMock())
    values=dict(api=api,show_entity_history=AsyncMock(),preview_record_components=AsyncMock())
    record={'id':11,'aggregation_id':9,'record_number':'FIX','medium':medium}
    @ui.page('/component-feature')
    async def page():values['show']=build(values);await values['show'](record)
    await user.open('/component-feature')
    d=max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
    return api,values,rows,record,d

def buttons(d,icon):return [e for e in d.descendants() if isinstance(e,ui.button) and e.props.get('icon')==icon]
def click(user,b):b.mark(f'component-{b.id}');user.find(marker=f'component-{b.id}').click()
async def settle():await asyncio.sleep(.15)

@pytest.mark.parametrize('closed,medium,allowed',[(False,'digital',True),(True,'digital',True),(False,'physical',True),(False,'digital',False)])
async def test_component_permission_closure_and_physical_upload_rules(user,closed,medium,allowed):
    api,v,rows,record,d=await setup(user,closed=closed,medium=medium,allowed=allowed)
    assert bool([e for e in d.descendants() if isinstance(e,ui.upload)])==(not closed and medium=='digital' and allowed)
    assert bool(buttons(d,'delete_outline')[0].props.get('disable'))==(closed or not allowed)
    assert bool(buttons(d,'visibility')[0].props.get('disable'))==(not allowed)
    assert bool(buttons(d,'manage_search'))==allowed
    api.component_page.assert_awaited_once_with(11,limit=25,offset=0)
    assert api.component_indexing_status.await_count==(2 if allowed else 0)

@pytest.mark.parametrize('failure',[False,True])
async def test_component_delete_version_and_optimistic_rollback(user,failure):
    api,v,rows,record,d=await setup(user)
    if failure:api.delete_component.side_effect=ApiError(409,'Conflict')
    else:api.delete_component.side_effect=lambda *args:rows.pop(0)
    click(user,buttons(d,'delete_outline')[0]);await settle()
    api.delete_component.assert_awaited_once_with(1,3)
    assert len(buttons(d,'delete_outline'))==(2 if failure else 1)
    assert api.component_page.await_count==(1 if failure else 2)

@pytest.mark.parametrize('failure',[False,True])
async def test_move_refresh_history_preview_download_and_reindex(user,failure,monkeypatch):
    api,v,rows,record,d=await setup(user)
    if failure:api.move_component.side_effect=ApiError(409,'Conflict')
    click(user,buttons(d,'arrow_downward')[0]);await settle();api.move_component.assert_awaited_once_with(11,1,1)
    assert api.component_page.await_count==(1 if failure else 2)
    click(user,buttons(d,'history')[0]);await settle();v['show_entity_history'].assert_awaited_once_with('digital-components',rows[0])
    click(user,buttons(d,'visibility')[0]);await settle();v['preview_record_components'].assert_awaited_once_with(record,1)
    download=Mock();monkeypatch.setattr(user,'download',download)
    click(user,buttons(d,'download')[0]);await settle();download.assert_called_once_with(b'fixture bytes','Fixture 1.png','image/png')
    click(user,buttons(d,'manage_search')[0]);await settle();api.reindex_component.assert_awaited_once_with(1)
    assert rows[0]['_indexing']['status']=='queued'

async def test_upload_batch_uses_current_total_and_refreshes_each_accepted_file(user):
    api,v,rows,record,d=await setup(user)
    def uploaded(identity,position,name,content,mime):
        rows.append(dict(id=position,version=1,file_name=name,mime_type=mime,content_status='pending',component_order=position,size_in_bytes=len(content)))
    api.upload_component.side_effect=uploaded
    uploader=next(e for e in d.descendants() if isinstance(e,ui.upload))
    with user:uploader._multi_upload_handlers[0](SimpleNamespace(contents=[BytesIO(b'a'),BytesIO(b'b')],names=['a.png','b.png'],types=['image/png','image/png']))
    await settle()
    assert [c.args for c in api.upload_component.await_args_list]==[(11,3,'a.png',b'a','image/png'),(11,4,'b.png',b'b','image/png')]
    assert api.component_page.await_count==4 and len(buttons(d,'delete_outline'))==4

async def test_last_page_deletion_returns_to_the_remaining_page(user):
    api,v,rows,record,d=await setup(user)
    page_calls=[]
    def page(identity,**kw):
        page_calls.append(kw['offset'])
        return {'items':list(rows) if kw['offset']==0 else [],'total':len(rows)}
    api.component_page.side_effect=page
    # Invoke the current pager callback: a concurrent removal has shortened the result.
    next_button=buttons(d,'chevron_right')[0]
    next_button.enable()
    click(user,next_button);await settle()
    assert page_calls==[25,0]
    assert len(buttons(d,'delete_outline'))==2

async def test_failed_upload_preserves_existing_cards_and_stops_the_batch(user):
    api,v,rows,record,d=await setup(user)
    api.upload_component.side_effect=ApiError(409,'Upload rejected')
    uploader=next(e for e in d.descendants() if isinstance(e,ui.upload))
    with user:uploader._multi_upload_handlers[0](SimpleNamespace(contents=[BytesIO(b'a'),BytesIO(b'b')],names=['a.png','b.png'],types=['image/png','image/png']))
    await settle()
    assert api.upload_component.await_count==1
    assert len(buttons(d,'delete_outline'))==2 and api.component_page.await_count==2
