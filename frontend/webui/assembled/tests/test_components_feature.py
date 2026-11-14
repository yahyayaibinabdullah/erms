"""Component upload, ordering, preview, download and removal through the real UI/API."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import opened
from frontend.webui.i18n_catalogue import render_message_plain as t
from frontend.webui.tests.test_staged_component_preview import PNG

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_saved_component_upload_move_preview_download_and_delete(assembled,monkeypatch):
    user=assembled;await login(user);api=user.api_clients[0]
    parent=(await api.search_request('aggregations',{'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0}))['items'][0]
    aggregation=await api.create('aggregations',dict(aggregation_number='COMP-AGG',title='Component fixture',classification_id=parent['classification_id'],medium='digital'))
    record=await api.create('records',dict(aggregation_id=aggregation['id'],record_number='COMP-REC',title='Component fixture record',medium='digital'))
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Records'])
    await eventually(lambda:current_page(user)=='records' and user.pending_requests==0)
    with user:next(i for i in user.find(ui.input).elements if plain(i)==t('webui.index.input.search_by_number_title_or_description_e21ed520')).value='COMP-REC'
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==t('webui.index.button.search_4d02b714') and 'unelevated' in b.props and 'dense' not in b.props])
    await eventually(lambda:any(b.props.get('aria-label')=='Open record' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('aria-label')=='Open record'])
    await eventually(lambda:current_page(user)=='record-details' and any(isinstance(e,ui.upload) for e in user.find(ui.upload).elements))
    upload=next(e for e in user.find(ui.upload).elements)
    with user:upload._multi_upload_handlers[0](SimpleNamespace(contents=[BytesIO(PNG),BytesIO(PNG)],names=['a.png','b.png'],types=['image/png','image/png']))
    def cards():return sorted([e for e in user.find(ui.card).elements if 'component-card' in e.classes],key=lambda c:c.id)
    await eventually(lambda:len(cards())==2 and user.pending_requests==0)
    original=(await api.component_page(record['id']))['items'];assert [r['file_name'] for r in original]==['a.png','b.png']
    def button(card,icon):return next(b for b in card.descendants() if isinstance(b,ui.button) and b.props.get('icon')==icon)
    old=cards()[0].id;click_one(user,[button(cards()[0],'arrow_downward')])
    await eventually(lambda:len(cards())==2 and cards()[0].id!=old and user.pending_requests==0)
    assert [r['file_name'] for r in (await api.component_page(record['id']))['items']]==['b.png','a.png']
    click_one(user,[button(cards()[0],'visibility')]);d=await opened(user)
    await eventually(lambda:any(isinstance(e,ui.image) for e in d.descendants()))
    click_one(user,[b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='close'])
    await eventually(lambda:not d.value)
    download=Mock();monkeypatch.setattr(user,'download',download)
    click_one(user,[button(cards()[0],'download')]);await eventually(lambda:download.called)
    assert download.call_args.args==(PNG,'b.png','image/png')
    click_one(user,[button(cards()[0],'delete_outline')])
    await eventually(lambda:len(cards())==1 and user.pending_requests==0 and any(r['method']=='DELETE' and '/digital-components/' in r['path'] for r in user.api_requests))
    assert [r['file_name'] for r in (await api.component_page(record['id']))['items']]==['a.png']
    assert not user.api_failures
