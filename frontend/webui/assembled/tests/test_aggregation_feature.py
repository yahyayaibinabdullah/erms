"""Aggregation creation, metadata and governed state writes through the real UI/API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import opened
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def open_seed_aggregation(user):
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Aggregations'])
    await eventually(lambda:current_page(user)=='aggregations' and user.pending_requests==0)
    with user:next(i for i in user.find(ui.input).elements if plain(i)==t('webui.index.input.search_by_number_title_or_description_e21ed520')).value='TEST-AGG'
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==t('webui.index.button.search_4d02b714') and 'unelevated' in b.props and 'dense' not in b.props])
    await eventually(lambda:any(b.props.get('aria-label')=='Open aggregation' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('aria-label')=='Open aggregation'])
    await eventually(lambda:current_page(user)=='aggregation-details' and any('aggregation-child-preview-grid' in e.classes for e in user.client.elements.values()) or any(isinstance(b,ui.button) and plain(b)==t('webui.open_aggregation.button.edit_metadata_3ee4d255') for b in user.client.elements.values()))
    await eventually(lambda:user.pending_requests==0)

async def test_aggregation_child_metadata_location_vital_review_close_and_reopen(assembled):
    user=assembled;await login(user);api=user.api_clients[0];await open_seed_aggregation(user)
    edit_key='webui.open_aggregation.button.edit_metadata_3ee4d255'
    def buttons(label,root=None):return [b for b in (root.descendants() if root else user.client.elements.values()) if isinstance(b,ui.button) and plain(b)==label]
    def click(label,root=None):click_one(user,buttons(label,root))
    def fields(d):return {plain(e).removesuffix(' *'):e for e in d.descendants() if isinstance(e,(ui.input,ui.select,ui.number,ui.textarea))}
    async def refreshed(old):await eventually(lambda:any(b.id!=old for b in buttons(t(edit_key))) and user.pending_requests==0)
    old=buttons(t(edit_key))[0].id
    click(t('webui.open_aggregation.text.add_child_aggregation_13879ca9'));d=await opened(user);f=fields(d)
    assert f['Parent aggregation'].value==1 and not f['Parent aggregation'].enabled
    assert f['Medium'].value=='physical' and not f['Medium'].enabled
    assert f['Classification'].value is None and not f['Classification'].enabled
    with user:f['Aggregation number'].value='AGG-CHILD';f['Title'].value='Aggregation child fixture'
    click('Save',d);await eventually(lambda:not d.value);await refreshed(old)
    child=(await api.search_request('aggregations',{'where':{'field':'aggregation_number','operator':'eq','value':'AGG-CHILD'},'limit':1,'offset':0}))['items'][0]
    assert child['parent_aggregation_id']==1 and child['medium']=='physical'
    child_card=next(e for e in user.client.elements.values() if 'aggregation-child-preview' in e.classes and any(getattr(x,'text',None)=='Aggregation child fixture' for x in e.descendants()))
    click_one(user,[child_card]);await eventually(lambda:any(isinstance(e,ui.label) and plain(e)=='AGG-CHILD' for e in user.client.elements.values()));await refreshed(old)
    old=buttons(t(edit_key))[0].id;click(t(edit_key));d=await opened(user)
    with user:fields(d)['Title'].value='Updated aggregation child'
    click('Save',d);await eventually(lambda:not d.value);await refreshed(old)
    assert (await api.get('aggregations',child['id']))['title']=='Updated aggregation child'
    for action,key in [('vital','webui.open_aggregation.button.vital_status_69064d77'),('review','webui.open_aggregation.button.next_review_699d407b'),('location','webui.open_aggregation.button.location_5c67a431')]:
        old=buttons(t(edit_key))[0].id;click(t(key));d=await opened(user)
        with user:
            next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Governed regression fixture'
            if action=='vital':next(e for e in d.descendants() if isinstance(e,ui.checkbox)).value=True
            elif action=='review':next(e for e in d.descendants() if isinstance(e,ui.input) and not isinstance(e,ui.textarea)).value='2099-01-01T09:30'
            else:
                fields(d)[t('webui.change_location.input.assigned_location_7abee0ea')].value='ROOM01'
                fields(d)[t('webui.change_location.input.current_location_53a3ef86')].value='DESK02'
        await eventually(lambda:user.pending_requests==0)
        click('Save',d);await eventually(lambda:not d.value);await refreshed(old)
    saved=await api.get('aggregations',child['id']);assert saved['is_vital'] and saved['date_of_next_review'].startswith('2099-')
    assert saved['assigned_location']=='ROOM01' and saved['current_location']=='DESK02'
    click(t('webui.open_aggregation.button.close_5dfd4eee'))
    await eventually(lambda:bool(buttons(t('webui.open_aggregation.button.reopen_96cb2ac2'))) and user.pending_requests==0)
    assert (await api.get('aggregations',child['id']))['date_closed'] is not None
    assert not buttons(t(edit_key))
    click(t('webui.open_aggregation.button.reopen_96cb2ac2'));d=await opened(user)
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Reopen fixture'
    click(t('webui.show_reopen_aggregation.button.reopen_3a12b38d'),d)
    await eventually(lambda:not d.value);await refreshed(old)
    assert (await api.get('aggregations',child['id']))['date_closed'] is None
    assert not user.api_failures
