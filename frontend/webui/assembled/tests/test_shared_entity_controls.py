"""Accepted editor writes use the real root, shared controls and disposable API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import (
    assembled, disposable_only, login, current_page, drawer_buttons, click_one, plain as original_plain, eventually,
)
from frontend.webui.i18n_catalogue import render_message_plain, strip_diagnostic_metadata

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def visible_text(value):
    return strip_diagnostic_metadata(str(value)).replace('\u2068','').replace('\u2069','')

def plain(element):
    return visible_text(original_plain(element))


@pytest.mark.parametrize('resource,label',[('profiles','Profiles'),('org-units','Organization units'),('security-levels','Security levels')])
async def test_collection_create_update_and_translation_keep_filtered_results(assembled,resource,label):
    user=assembled;await login(user)
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==label])
    await eventually(lambda:current_page(user)==resource and user.pending_requests==0)
    code='PHASE6C_'+resource.replace('-','_').upper()
    filter_control=next(i for i in user.find(ui.input).elements if plain(i).startswith('Filter '))
    with user:filter_control.value=code
    await user.should_see('No matching items.',retries=100)
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)=='Add'])
    await eventually(lambda:any(d.value for d in user.find(ui.dialog).elements))
    dialog=next(d for d in user.find(ui.dialog).elements if d.value)
    def fields():return {plain(e).removesuffix(' *'):e for e in dialog.descendants() if isinstance(e,(ui.input,ui.number,ui.select))}
    def save():click_one(user,[b for b in dialog.descendants() if isinstance(b,ui.button) and plain(b)=='Save'])
    save()
    await eventually(lambda:any(visible_text(message)=='Code is required' for message in user.notify.messages))
    assert dialog.value
    with user:
        fields()['Code'].value=code
        fields()['Name'].value='Shared control fixture'
        if resource=='security-levels':fields()['Level number'].value=25
    save();await eventually(lambda:not dialog.value and user.pending_requests==0)
    await user.should_see('Shared control fixture',retries=100)
    cards=[e for e in user.find(ui.card).elements if 'governance-list-card' in e.classes]
    assert len(cards)==1
    click_one(user,[b for b in cards[0].descendants() if isinstance(b,ui.button) and b.props.get('icon')=='edit'])
    await eventually(lambda:any(d.value for d in user.find(ui.dialog).elements))
    dialog=next(d for d in user.find(ui.dialog).elements if d.value)
    expansion=next(e for e in dialog.descendants() if isinstance(e,ui.expansion))
    with user:expansion.open()
    language=next(e for e in expansion.descendants() if isinstance(e,ui.select))
    with user:language.value='ar'
    await user.should_see(render_message_plain('entity_translation_editor.status.loaded'),retries=100)
    canonical_name=next(e for e in dialog.descendants() if isinstance(e,ui.input) and plain(e)=='Name *')
    translated_name=next(e for e in expansion.descendants() if isinstance(e,ui.input) and plain(e)=='Name')
    reason=next(e for e in dialog.descendants() if isinstance(e,ui.input) and plain(e).startswith('Reason for'))
    with user:
        canonical_name.value='Updated shared fixture'
        translated_name.value='اسم الاختبار'
        reason.value='Disposable regression'
    save();await eventually(lambda:not dialog.value and user.pending_requests==0)
    await user.should_see('Updated shared fixture',retries=100)
    assert next(i for i in user.find(ui.input).elements if plain(i).startswith('Filter ')).value==code
    assert not user.api_failures
    # Assert one canonical creation, one update and one translation write.
    writes=[r for r in user.api_requests if r['method'] in {'POST','PATCH'} and (r['path'].startswith('/api/v1/'+resource) or r['path'].startswith('/api/v1/entity-translations/'+resource))]
    assert sum(r['method']=='POST' and r['path']=='/api/v1/'+resource for r in writes)==1
    assert sum(r['method']=='PATCH' for r in writes)==2
