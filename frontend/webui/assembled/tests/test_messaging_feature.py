"""Actual mailbox compose, draft/send and existing retention protection via root UI."""
import os
import subprocess
from pathlib import Path
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually,plain
from frontend.webui.i18n_catalogue import render_message_plain as t
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_mailbox_compose_draft_send_retention_real_api(assembled):
    root=Path(__file__).resolve().parents[4]
    command=[str(root/'backend/services/api/.venv/bin/python'),'-m','tools.seed_webui_messaging']
    saved=subprocess.run(command,cwd=root,env=os.environ,check=True,capture_output=True,text=True)
    try:
        user=assembled;await login(user);api=user.api_clients[0]
        async def enter(folder):
            click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('messaging.navigation.'+folder)])
            await eventually(lambda:current_page(user)=='messages-'+folder and user.pending_requests==0)
        def button(key,scope=None):
            elements=scope.descendants() if scope else user.client.elements.values()
            return [b for b in elements if isinstance(b,ui.button) and b.visible and plain(b)==t(key)]
        await enter('inbox');click_one(user,button('messaging.action.compose'));await eventually(lambda:any(isinstance(e,ui.editor) for e in user.client.elements.values()))
        dialog=next(e for e in user.client.elements.values() if isinstance(e,ui.dialog) and e.value)
        recipient=next(e for e in dialog.descendants() if isinstance(e,ui.select) and 'message-recipients-to' in e._markers)
        result=await api.request('GET','/api/v1/messages/recipients/user',params={'q':'Test officer','limit':25})
        person=next(r for r in result['items'] if r['eligible']);recipient.set_options({person['id']*3:'User · '+person['name']},value=[person['id']*3])
        next(e for e in dialog.descendants() if isinstance(e,ui.input) and plain(e)==t('messaging.field.subject')).value='Mailbox refactor acceptance'
        next(e for e in dialog.descendants() if isinstance(e,ui.editor)).value='<p>Preserved mailbox content</p>'
        await eventually(lambda:button('messaging.action.send',dialog)[0].enabled and user.pending_requests==0)
        click_one(user,button('messaging.action.save_draft',dialog));await user.should_see(t('messaging.state.saved'))
        drafts=(await api.request('GET','/api/v1/messages/drafts'))['items'];draft=next(r for r in drafts if r['subject']=='Mailbox refactor acceptance')
        click_one(user,button('messaging.action.cancel',dialog));await enter('drafts')
        last_element=max(user.client.elements);user.find(marker='message-row-'+draft['id']).click();await eventually(lambda:any(isinstance(e,ui.button) and 'messaging-send' in e._markers and e.enabled and e.id>last_element for e in user.client.elements.values()))
        send=max((e for e in user.client.elements.values() if isinstance(e,ui.button) and 'messaging-send' in e._markers and e.enabled),key=lambda e:e.id)
        click_one(user,[send]);await user.should_see(t('messaging.state.sent'))
        sent=next(r for r in (await api.request('GET','/api/v1/messages/outbox'))['items'] if r['subject']=='Mailbox refactor acceptance')
        await enter('outbox');user.find(marker='message-row-'+sent['id']).click()
        await eventually(lambda:user.pending_requests==0 and bool(button('messaging.capture.save')))
        message=await api.request('GET','/api/v1/messages/outbox/'+sent['id'])
        assert not message['can_delete']
        assert not button('messaging.retention.delete')
        assert not user.api_failures
    finally:
        subprocess.run([*command,'cleanup'],cwd=root,env=os.environ,check=True,input=saved.stdout,capture_output=True,text=True)
