"""Security writes and refresh through the real root and disposable API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import (
    assembled,disposable_only,login,current_page,drawer_buttons,click_one,eventually,
)
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def click(user,label,root=None):
    choices=list(root.descendants()) if root else user.find(ui.button).elements
    click_one(user,[b for b in choices if isinstance(b,ui.button) and plain(b)==label and 'erms-nav-link' not in b.classes])
async def opened(user):
    await eventually(lambda:any(d.value for d in user.find(ui.dialog).elements) and user.pending_requests==0)
    return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
async def saved(user,d):await eventually(lambda:not d.value and user.pending_requests==0)


async def test_profile_privilege_write_retains_dependencies_and_refreshes(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    profile=await api.create('profiles',{'code':'PHASE6E','name':'Security regression','description':'Disposable fixture'})
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Profiles'])
    await eventually(lambda:current_page(user)=='profiles' and user.pending_requests==0)
    with user:next(i for i in user.find(ui.input).elements if plain(i)=='Filter profiles').value='PHASE6E'
    await eventually(lambda:len([c for c in user.find(ui.card).elements if 'governance-list-card' in c.classes])==1 and user.pending_requests==0)
    card=next(c for c in user.find(ui.card).elements if 'governance-list-card' in c.classes)
    click_one(user,[b for b in card.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='key'])
    d=await opened(user)
    checkbox=next(e for e in d.descendants() if isinstance(e,ui.checkbox) and 'record.modify' in plain(e))
    with user:checkbox.value=True
    assert any(e.value and 'record.view' in plain(e) for e in d.descendants() if isinstance(e,ui.checkbox))
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Regression reason'
    click(user,t('webui.show_profile_privilege_editor.button.save_privileges_9223c6cc'),d)
    await saved(user,d)
    selected=await api.profile_privileges(profile['id'])
    assert {'record.modify','record.view'} <= {p['code'] for p in selected}
    assert not user.api_failures


async def test_record_acl_write_reopens_fresh_and_explains_access(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Records'])
    await eventually(lambda:current_page(user)=='records' and user.pending_requests==0)
    with user:next(i for i in user.find(ui.input).elements if plain(i)==t('webui.index.input.search_by_number_title_or_description_e21ed520')).value='TEST-REC'
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==t('webui.index.button.search_4d02b714') and 'unelevated' in b.props and 'dense' not in b.props])
    await eventually(lambda:any(b.props.get('aria-label')=='Open record' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('aria-label')=='Open record'])
    await eventually(lambda:current_page(user)=='record-details' and user.pending_requests==0)
    await eventually(lambda:any(plain(b)==t('webui.select_record_details.button.access_489ef75d') for b in user.find(ui.button).elements))
    original_access=next(b.id for b in user.find(ui.button).elements if plain(b)==t('webui.select_record_details.button.access_489ef75d'))
    click(user,t('webui.select_record_details.button.access_489ef75d'))
    d=await opened(user)
    switches=[e for e in d.descendants() if isinstance(e,ui.switch)]
    if switches:
        with user:switches[0].value=False
    with user:next(e for e in d.descendants() if isinstance(e,ui.input)).value='Regression ACL reason'
    click(user,t('webui.show_acl_editor.button.save_acl_a2306fa4'),d)
    await saved(user,d)
    writes=[r for r in user.api_requests if r['method']=='PUT' and r['path'].endswith('/permissions')]
    assert len(writes)==1
    identifier=int(writes[0]['path'].split('/')[-2])
    await eventually(lambda:any(b.id!=original_access and plain(b)==t('webui.select_record_details.button.access_489ef75d') for b in user.find(ui.button).elements))
    acl=await api.resource_acl('records',identifier)
    assert not acl['inherit_acl_from_parent']
    click(user,t('webui.select_record_details.button.access_489ef75d'))
    d=await opened(user)
    assert not next(e for e in d.descendants() if isinstance(e,ui.switch)).value
    click(user,t('webui.show_acl_editor.button.cancel_256f9c91'),d)
    click(user,t('webui.select_record_details.button.why_this_access_a28abcce'))
    d=await opened(user)
    await user.should_see(t('webui.load_explanation.label.decision_gates_1847ec0e'),retries=100)
    assert not user.api_failures
