"""Indexer lifecycle against the disposable real API; never log credential values."""
from datetime import datetime,timedelta,timezone
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,disposable_only,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import click,opened,saved
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def input_value(user,d,key,value):
    with user:next(i for i in d.descendants() if isinstance(i,ui.input) and plain(i)==t(key)).value=value

async def test_indexer_creation_status_rotation_and_revocation(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Text Indexers'])
    await eventually(lambda:current_page(user)=='text-indexers' and user.pending_requests==0)
    click(user,t('webui.select_text_indexers.button.add_text_indexer_fd6584b1'));d=await opened(user)
    for key,value in [('webui.add_text_indexer_dialog.input.deployment_or_pool_name_7539da84','Phase6H indexer'),('webui.add_text_indexer_dialog.input.immutable_external_id_0e9e9051','phase6h-indexer'),('webui.add_text_indexer_dialog.input.initial_credential_name_33daef5e','Initial key')]:input_value(user,d,key,value)
    click(user,t('webui.add_text_indexer_dialog.button.create_and_generate_key_a5f16e9e'),d)
    await saved(user,d);reveal=await opened(user)
    assert reveal.props.get('persistent')
    click(user,t('webui.reveal_text_indexer_key.button.i_have_stored_it_safely_e3a69b9d'),reveal)
    await eventually(lambda:current_page(user)=='text-indexer-details' and user.pending_requests==0)
    await eventually(lambda:any(plain(b)==t('webui.select_text_indexer_details.button.generate_api_key_35bdc780') for b in user.find(ui.button).elements))
    indexer=next(x for x in await api.text_indexers() if x['external_id']=='phase6h-indexer');identity=indexer['id']
    original=(await api.text_indexer_credentials(identity))['items'][0]
    click(user,t('webui.select_text_indexer_details.button.suspend_7f5e5b10'))
    await eventually(lambda:user.pending_requests==0 and any(isinstance(b,ui.button) and plain(b)==t('webui.select_text_indexer_details.button.activate_b44c7d38') for b in user.find(ui.button).elements))
    assert (await api.text_indexer(identity))['status']=='suspended'
    generate=next(b for b in user.find(ui.button).elements if plain(b)==t('webui.select_text_indexer_details.button.generate_api_key_35bdc780'));assert not generate.enabled
    click(user,t('webui.select_text_indexer_details.button.activate_b44c7d38'))
    await eventually(lambda:user.pending_requests==0 and any(plain(b)==t('webui.select_text_indexer_details.button.suspend_7f5e5b10') for b in user.find(ui.button).elements))
    click(user,t('webui.render_credentials.button.rotate_1496c92c'));d=await opened(user)
    input_value(user,d,'webui.credential_dialog.input.credential_name_b670464d','Rotated key')
    click(user,t('webui.credential_dialog.button.rotate_key_abe27125'),d)
    await saved(user,d);reveal=await opened(user)
    click(user,t('webui.reveal_text_indexer_key.button.i_have_stored_it_safely_e3a69b9d'),reveal)
    await saved(user,reveal)
    credentials=(await api.text_indexer_credentials(identity))['items']
    assert len(credentials)==2
    assert next(c for c in credentials if c['id']==original['id'])['status']=='revoked'
    click(user,t('webui.render_credentials.button.revoke_4fc0db3b'));d=await opened(user)
    click(user,t('webui.confirm_revoke.button.revoke_f9d8c510'),d);await saved(user,d)
    assert all(c['status']=='revoked' for c in (await api.text_indexer_credentials(identity))['items'])
    assert not user.api_failures


async def test_indexer_backfill_refresh_and_empty_retry_disabled(assembled):
    user=assembled;await login(user)
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Text Indexers'])
    await eventually(lambda:current_page(user)=='text-indexers' and user.pending_requests==0)
    assert not next(b for b in user.find(ui.button).elements if b.props.get('icon')=='replay').enabled
    for icon,submit,path in [('playlist_add','webui.queue_backfill_dialog.button.queue_batch_59aa1eb9','/backfill')]:
        click_one(user,[b for b in user.find(ui.button).elements if b.props.get('icon')==icon]);d=await opened(user)
        with user:next(i for i in d.descendants() if isinstance(i,ui.number)).value=1
        click(user,t(submit),d);await saved(user,d)
        assert any(r['method']=='POST' and r['path'].endswith(path) for r in user.api_requests)
    assert not user.api_failures
