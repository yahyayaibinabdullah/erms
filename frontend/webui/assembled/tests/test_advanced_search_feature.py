"""Saved-query writes and administration through the assembled application."""
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import opened
from frontend.webui.i18n_catalogue import render_message_plain as t
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def buttons(user,key,root=None):
    if root is None:root=next(e for e in user.client.elements.values() if 'advanced-search-page' in e.classes)
    return [e for e in (root.descendants() if root else user.client.elements.values()) if isinstance(e,ui.button) and plain(e)==t(key)]
def input_for(user,key,root=None):
    if root is None:root=next(e for e in user.client.elements.values() if 'advanced-search-page' in e.classes)
    return next(e for e in (root.descendants() if root else user.client.elements.values()) if isinstance(e,(ui.input,ui.textarea)) and plain(e)==t(key))
async def enter(user):
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.advanced_search')])
    await eventually(lambda:current_page(user)=='advanced-search' and any('advanced-search-page' in e.classes for e in user.client.elements.values()) and user.pending_requests==0)

async def test_advanced_query_execute_save_update_and_reasoned_delete(assembled):
    user=assembled;await login(user);await enter(user);api=user.api_clients[0]
    value='webui.render_condition.input.value_8dc59edc'
    with user:input_for(user,value).value='Test'
    search='webui.select_advanced_search.button.search_97989f23'
    await eventually(lambda:buttons(user,search)[0].enabled)
    click_one(user,buttons(user,search));await eventually(lambda:any('compact-result-item' in e.classes for e in user.client.elements.values()) and user.pending_requests==0)
    click_one(user,buttons(user,'webui.refresh_saved_actions.text.save_search_76b8ff5b'));dialog=await opened(user)
    with user:input_for(user,'webui.save_search.input.name_76ae569a',dialog).value='Assembled saved query'
    click_one(user,buttons(user,'webui.save_search.button.save_53b01f94',dialog));await eventually(lambda:not dialog.value and user.pending_requests==0)
    saved=(await api.saved_searches(q='Assembled saved query',scope='owned',limit=25,offset=0))['items'][0]
    assert saved['audience_mode']=='private'
    with user:input_for(user,value).value='Updated test'
    update='webui.refresh_saved_actions.text.update_saved_search_31788e51'
    click_one(user,buttons(user,update));await user.should_see(t('webui.persist_saved_search.notify.saved_search_updated_7bd649da'))
    updated=await api.saved_search(saved['id']);assert updated['version']>saved['version'] and 'Updated test' in str(updated['definition'])
    click_one(user,buttons(user,'webui.select_advanced_search.button.delete_f507983a'))
    dialog=await opened(user);delete='webui.delete_saved_search.button.delete_saved_search_226c4222'
    click_one(user,buttons(user,delete,dialog));await user.should_see(t('webui.remove.text.a_reason_is_required_0adbb4d3'));assert dialog.value
    with user:input_for(user,'webui.delete_saved_search.textarea.reason_for_deletion_5aca706a',dialog).value='Disposable query cleanup'
    click_one(user,buttons(user,delete,dialog));await eventually(lambda:not dialog.value and user.pending_requests==0)
    assert not (await api.saved_searches(q='Assembled saved query',scope='owned',limit=25,offset=0))['items']
    assert not user.api_failures

async def test_saved_query_administration_is_hidden_and_denied_for_viewer(assembled):
    user=assembled;await login(user,'viewer@test.invalid')
    assert not any(plain(b)==t('privilege.search.saved_search.administrator.name') for b in drawer_buttons(user))
    with pytest.raises(ApiError) as error:await user.api_clients[0].saved_search_administration(limit=25,offset=0)
    assert error.value.status_code==403
