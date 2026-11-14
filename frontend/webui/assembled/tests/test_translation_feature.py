"""Translation editor writes against disposable data; never promotes source artifacts."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import click,opened,saved
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_translation_draft_and_publication_preserve_version_and_export(assembled):
    user=assembled;await login(user);api=user.api_clients[0];key='navigation.item.translations'
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t(key)])
    await eventually(lambda:current_page(user)=='translations' and user.pending_requests==0)
    label=t('webui.select_translation_administration.input.key_16b82d81')
    await eventually(lambda:any(isinstance(e,ui.input) and plain(e)==label for e in user.find(ui.input).elements))
    with user:next(e for e in user.find(ui.input).elements if plain(e)==label).value=key
    await eventually(lambda:user.pending_requests==0 and sum(isinstance(b,ui.button) and b.props.get('icon')=='edit' for b in user.find(ui.button).elements)==1)
    for publish in (False,True):
        click_one(user,[b for b in user.find(ui.button).elements if b.props.get('icon')=='edit']);d=await opened(user)
        before=(await api.localization_messages(language_tag='ar',key=key))['items'][0]
        with user:
            next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='ترجمات تجريبية'
            next(e for e in d.descendants() if isinstance(e,ui.input) and not isinstance(e,ui.textarea)).value='Disposable translation verification'
        click_one(user,[b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')==('publish' if publish else 'save')])
        await saved(user,d)
        after=(await api.localization_messages(language_tag='ar',key=key))['items'][0]
        assert after['translated_text']=='ترجمات تجريبية' and after['translation_version']>before['translation_version']
        if publish:assert after['date_published']
    preview=await api.preview_localization_export('ar')
    assert preview['active_keys']>0
    assert not user.api_failures

async def test_complete_arabic_artifact_import_preview_reason_and_confirm(assembled):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from io import BytesIO

    user=assembled;await login(user);api=user.api_clients[0]
    artifact=json.loads(Path('frontend/webui/i18n/messages.ar.generated.json').read_bytes())
    # Simulate a reviewed import in memory. The checked-in draft can still
    # contain entries that need human review and are blocked by import preview.
    for item in artifact['items']:
        if item.get('quality_flags') == ['needs_human_review']:
            item['quality_flags'] = []
    preview = await api.preview_localization_import('ar', artifact)
    assert preview['complete'], (preview['missing_keys'], preview['invalid_keys'])
    artifact_bytes = json.dumps(artifact, ensure_ascii=False).encode('utf-8')
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.translations')])
    await eventually(lambda:current_page(user)=='translations' and user.pending_requests==0)
    await eventually(lambda:any(b.props.get('icon')=='upload_file' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('icon')=='upload_file']);d=await opened(user)
    upload=next(e for e in d.descendants() if isinstance(e,ui.upload));confirm=next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='upload_file')
    assert not confirm.enabled
    previous_previews = sum(r['path'].endswith('/import-preview') for r in user.api_requests)
    with user:upload._multi_upload_handlers[0](SimpleNamespace(contents=[BytesIO(artifact_bytes)],names=['fixture.json'],types=['application/json']))
    await eventually(lambda:sum(r['path'].endswith('/import-preview') for r in user.api_requests) > previous_previews and user.pending_requests==0)
    assert not confirm.enabled
    with user:next(e for e in d.descendants() if isinstance(e,ui.input)).value='Disposable artifact import verification'
    await eventually(lambda:confirm.enabled)
    click_one(user,[confirm]);await saved(user,d)
    assert any(r['path'].endswith('/import') and r['method']=='POST' for r in user.api_requests)
    assert not user.api_failures
