"""Exercise the extracted editor's real controls and per-dialog load state."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nicegui import ui, context
from frontend.webui.entity_translation_editor import entity_translation_editor
from frontend.webui.i18n_catalogue import render_message

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
LANGUAGES=[{'language_tag':tag,'native_name':tag,'english_name':tag} for tag in ('ar','en')]

async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.01)

async def open_editor(user, api, *, external=False):
    result={}
    row={'id':17,'version':1}
    @ui.page('/shared-translation-editor')
    async def page():
        dialog=ui.dialog()
        with dialog,ui.card():
            result['pending']=await entity_translation_editor(api,resource='profiles' if external else 'roles',
                row=row,fields=('name','description'),languages=LANGUAGES,dialog=dialog,
                uses_external_reason=external,get_external_reason=lambda:result['reason'],
                error_message=str,show_api_error=lambda error:ui.notify(str(error)))
            elements=list(context.client.elements.values())
            result['language']=next(e for e in elements if isinstance(e,ui.select))
            result['name']=next(e for e in elements if isinstance(e,ui.input) and e.label==render_message('entity_translation_editor.input.name'))
            if external:
                # As in the profile host, this control is created after the translation editor.
                result['reason']=ui.input('Profile change reason')
            else:
                result['reason']=next(e for e in elements if isinstance(e,ui.input) and e.label==render_message('webui.open_editor.input.reason_for_translation_change_82d24ea1'))
        dialog.open()
    await user.open('/shared-translation-editor')
    result['row']=row
    return result

@pytest.mark.parametrize('external',[False,True])
async def test_load_baseline_and_shared_reason_are_preserved(user,external):
    api=SimpleNamespace(entity_translation=AsyncMock(return_value={'version':3,'fields':{'name':'Original'}}))
    editor=await open_editor(user,api,external=external)
    assert editor['pending']() is None
    with user:editor['language'].set_value('ar')
    await until(lambda:editor['name'].value=='Original')
    assert editor['row']['version']==3
    assert editor['pending']() is None
    with user:editor['name'].set_value('  Updated  ')
    with pytest.raises(ValueError):editor['pending']()
    with user:editor['reason'].set_value('  Review  ')
    assert editor['pending']()==('ar',{'name':'Updated'},'Review')
    api.entity_translation.assert_awaited_once_with('profiles' if external else 'roles',17,'ar')

async def test_late_translation_cannot_replace_selected_language(user):
    started,release=asyncio.Event(),asyncio.Event()
    async def fetch(resource,identity,language):
        if language=='ar':started.set();await release.wait()
        return {'version':2 if language=='ar' else 4,'fields':{'name':language}}
    editor=await open_editor(user,SimpleNamespace(entity_translation=fetch))
    with user:editor['language'].set_value('ar')
    await asyncio.wait_for(started.wait(),5)
    with user:editor['language'].set_value('en')
    await until(lambda:editor['name'].value=='en')
    release.set();await asyncio.sleep(.02)
    assert editor['name'].value=='en' and editor['row']['version']==4
    assert editor['pending']() is None
