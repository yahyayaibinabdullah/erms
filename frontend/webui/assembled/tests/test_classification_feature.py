"""Classification creation/editing/history through the real root and disposable API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import (
    assembled, disposable_only, login, current_page, drawer_buttons, click_one, eventually,
)
from frontend.webui.assembled.tests.test_shared_entity_controls import plain, visible_text
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


async def test_scheme_and_classification_editing_preserve_rules_translations_and_history(assembled):
    user=assembled;await login(user)
    click_one(user,[b for b in drawer_buttons(user) if plain(b)=='Classification schemes'])
    await eventually(lambda:current_page(user)=='classification-workspace' and user.pending_requests==0)
    def click(label,root=None):
        elements=list(root.descendants()) if root else user.find(ui.button).elements
        click_one(user,[b for b in elements if isinstance(b,ui.button) and plain(b)==label])
    async def opened():
        await eventually(lambda:any(d.value for d in user.find(ui.dialog).elements))
        return next(d for d in user.find(ui.dialog).elements if d.value)
    def fields(dialog):
        result={}
        for e in dialog.descendants():
            if isinstance(e,(ui.input,ui.number,ui.select,ui.textarea)):
                result.setdefault(plain(e).removesuffix(' *'),e)
        return result
    async def saved(dialog):
        click('Save',dialog)
        try:
            await eventually(lambda:not dialog.value and user.pending_requests==0)
        except TimeoutError:
            raise AssertionError({'notices': [visible_text(m) for m in user.notify.messages], 'failures':user.api_failures, 'fields':{k:v.value for k,v in fields(dialog).items()}}) from None
    click('Add scheme');dialog=await opened()
    click('Save',dialog)
    await eventually(lambda:any('Code is required' in visible_text(m) for m in user.notify.messages))
    with user:
        fields(dialog)['Code'].value='PHASE6D'
        fields(dialog)['Title'].value='Classification regression'
    await saved(dialog)
    await eventually(lambda:current_page(user)=='classification-scheme-details' and user.pending_requests==0)
    # Navigation state changes before the detail controls finish rendering.
    await user.should_see('Edit scheme',retries=100)
    click('Edit scheme');dialog=await opened()
    assert not fields(dialog)['Date published'].enabled
    with user:fields(dialog)['Title'].value='Changed classification scheme'
    await saved(dialog)
    await user.should_see('Changed classification scheme')
    click(t('classification_browser.add_root'));dialog=await opened()
    assert not fields(dialog)['Classification scheme'].enabled
    with user:
        fields(dialog)['Code'].value='ROOT'
        fields(dialog)['Title'].value='Root classification'
        fields(dialog)['Current retention (years)'].value=2
    click('Save',dialog)
    await eventually(lambda:any('requires both periods' in visible_text(m) for m in user.notify.messages))
    assert dialog.value
    with user:
        fields(dialog)['Intermediate retention (years)'].value=3
        fields(dialog)['Final disposition'].value='destruction'
        fields(dialog)['Classification type'].value=False
    await saved(dialog)
    await eventually(lambda:current_page(user)=='classification-details' and user.pending_requests==0)
    await user.should_see('Root classification')
    click('Edit');dialog=await opened()
    assert fields(dialog)['Current retention (years)'].value==2
    expansion=next(e for e in dialog.descendants() if isinstance(e,ui.expansion))
    with user:expansion.open()
    language=next(e for e in expansion.descendants() if isinstance(e,ui.select))
    with user:language.value='ar'
    await user.should_see(t('entity_translation_editor.status.loaded'),retries=100)
    translated_title=next(e for e in expansion.descendants() if isinstance(e,ui.input) and plain(e)=='Title')
    reason=next(e for e in expansion.descendants() if isinstance(e,ui.input) and plain(e).startswith('Reason for'))
    with user:
        fields(dialog)['Current retention (years)'].value=4
        translated_title.value='تصنيف الاختبار'
        reason.value='Disposable regression'
    await saved(dialog)
    await eventually(lambda:any(plain(b)=='Edit' for b in user.find(ui.button).elements))
    click('Edit');dialog=await opened()
    assert fields(dialog)['Current retention (years)'].value==4
    click('Cancel',dialog)
    click('Event history');dialog=await opened()
    await user.should_see('Root classification',retries=100)
    await eventually(lambda: user.pending_requests==0)
    assert any('/history' in r['path'] for r in user.api_requests)
    # Optional direct-retention reads may legitimately return 404; all writes succeed.
    assert not [f for f in user.api_failures if f[2]!=404]
    writes=[r for r in user.api_requests if r['method'] in {'POST','PATCH','PUT'} and 'classification' in r['path']]
    assert any(r['method']=='POST' and r['path']=='/api/v1/classifications' for r in writes)
    assert any(r['method']=='PUT' and 'retention' in r['path'] for r in writes)
    assert any(r['method']=='PATCH' and '/entity-translations/classifications/' in r['path'] for r in writes)
