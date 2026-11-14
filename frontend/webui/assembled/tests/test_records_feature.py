"""Connected record draft/metadata lifecycle through the real UI and API."""
from io import BytesIO
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import opened
from frontend.webui.i18n_catalogue import render_message_plain as t, strip_diagnostic_metadata
from frontend.webui.tests.test_staged_component_preview import PNG

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('medium',['physical','digital'])
async def test_record_draft_validation_staging_commit_and_metadata(assembled,medium):
    user=assembled;await login(user);api=user.api_clients[0]
    parent=(await api.search_request('aggregations',{'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0}))['items'][0]
    if medium=='digital':parent=await api.create('aggregations',dict(aggregation_number='REC-DEST',title='Record destination',classification_id=parent['classification_id'],medium='digital'))
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Aggregations'])
    await eventually(lambda:current_page(user)=='aggregations' and user.pending_requests==0)
    with user:next(i for i in user.find(ui.input).elements if plain(i)==t('webui.index.input.search_by_number_title_or_description_e21ed520')).value=parent['aggregation_number']
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==t('webui.index.button.search_4d02b714') and 'unelevated' in b.props and 'dense' not in b.props])
    await eventually(lambda:any(b.props.get('aria-label')=='Open aggregation' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('aria-label')=='Open aggregation'])
    def buttons(label,root=None):return [b for b in (root.descendants() if root else user.client.elements.values()) if isinstance(b,ui.button) and plain(b)==label]
    def fields(d):return {plain(e).removesuffix(' *'):e for e in d.descendants() if isinstance(e,(ui.input,ui.select,ui.textarea,ui.number))}
    add=t('webui.index.button.add_record_fc8125c4')
    await eventually(lambda:current_page(user)=='aggregation-details' and any(b.visible for b in buttons(add)) and user.pending_requests==0)
    click_one(user,buttons(add));d=await opened(user);await eventually(lambda:user.pending_requests==0)
    f=fields(d);assert f['Aggregation'].value==parent['id'] and f['Aggregation'].props.get('readonly')
    assert f['Medium'].value==medium and not f['Medium'].enabled
    commit=t('webui.open_record_draft_editor.button.create_record_dd0193d6')
    before=len(user.api_requests); notices=len(user.notify.messages);click_one(user,buttons(commit,d))
    await eventually(lambda:len(user.notify.messages)>notices)
    assert t('entity_metadata.validation.required',field=t('entity_metadata.field.record_number')) in [strip_diagnostic_metadata(str(m)) for m in user.notify.messages[notices:]]
    await eventually(lambda:user.pending_requests==0)
    assert d.value and not any(r['method']=='POST' and r['path'].endswith('/commit') for r in user.api_requests[before:])
    with user:f['Record number'].value='DRAFT-'+medium;f['Title'].value='Created '+medium+' record'
    if medium=='digital':
        upload=next(e for e in d.descendants() if isinstance(e,ui.upload))
        with user:upload._multi_upload_handlers[0](SimpleNamespace(contents=[BytesIO(PNG)],names=['staged.png'],types=['image/png']))
        await eventually(lambda:any('component-card' in e.classes for e in d.descendants()) and user.pending_requests==0)
    click_one(user,buttons(commit,d));await eventually(lambda:not d.value and user.pending_requests==0)
    created=(await api.search_request('records',{'where':{'field':'record_number','operator':'eq','value':'DRAFT-'+medium},'limit':1,'offset':0}))['items'][0]
    assert created['aggregation_id']==parent['id'] and created['medium']==medium
    components=await api.component_page(created['id']);assert components['total']==(1 if medium=='digital' else 0)
    def created_rows():return [e for e in user.client.elements.values() if 'compact-result-item' in e.classes and any(getattr(c,'text',None)=='Created '+medium+' record' for c in e.descendants())]
    await eventually(lambda:bool(created_rows()) and user.pending_requests==0)
    row=created_rows()[0]
    click_one(user,[b for b in row.descendants() if isinstance(b,ui.button) and b.props.get('aria-label')=='Open record'])
    edit=t('webui.select_record_details.button.edit_metadata_d7742b94')
    await eventually(lambda:bool(buttons(edit)) and any('component-grid' in e.classes and e.id>buttons(edit)[0].id and list(e.descendants()) for e in user.client.elements.values()) and user.pending_requests==0)
    old=buttons(edit)[0].id;click_one(user,buttons(edit));d=await opened(user)
    with user:fields(d)['Title'].value='Updated '+medium+' record'
    click_one(user,buttons('Save',d));await eventually(lambda:not d.value and any(b.id!=old for b in buttons(edit)) and user.pending_requests==0)
    assert (await api.get('records',created['id']))['title']=='Updated '+medium+' record'
    assert not user.api_failures
