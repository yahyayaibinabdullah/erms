"""Translation writes and artifact controls; synthetic data never replaces source artifacts."""
import ast,asyncio,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui import translation_administration as feature
from frontend.webui.api_client import ApiError

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def build(values):
    import inspect
    dependencies={name:values.get(name,getattr(host,name,None)) for name in inspect.signature(feature.build_translation_administration).parameters}
    dependencies['enter_translations']=lambda:values['state'].update(resource='translations',rows=[],searched=True)
    dependencies['current_page']=lambda:values['state'].get('resource')
    return feature.build_translation_administration(**dependencies)


async def setup(user):
    item=dict(message_key='fixture.key',context_group='fixture',validity='valid',semantic_meaning='Fixture meaning',default_text='Fixture',rendered_example='Fixture',translator_guidance='Fixture guidance',grammatical_role='label',common_locations=[],parameter_schema={},translated_text='اختبار',translation_version=2,origin='manual',date_reviewed=None,generation_metadata={'fixture':True})
    languages=[dict(language_tag=tag,native_name=name,english_name=name,direction=direction,is_enabled=True,is_default=tag=='en',catalogue_revision=1) for tag,name,direction in [('en','English','ltr'),('ar','العربية','rtl')]]
    api=SimpleNamespace(localization_languages=AsyncMock(return_value=languages),localization_messages=AsyncMock(return_value={'items':[item],'total':1,'group_total':1,'context_groups':['fixture']}),localization_generation_report=AsyncMock(return_value=dict(total=1,drafts=1,reviewed=0,unreviewed=1,published=0,unpublished=1,quality_attention=0)),update_localization_translation=AsyncMock(return_value={'version':3}),publish_localization_translation=AsyncMock(),preview_bulk_localization_publication=AsyncMock(return_value=dict(items=[{'message_key':'fixture.key','version':2}],count=1,invalid=[])),bulk_review_publish_localization=AsyncMock(return_value={'published':1}),preview_localization_export=AsyncMock(return_value=dict(complete=True,exportable_keys=1,active_keys=1,changed_from_checked_in=0,reviewed_draft_overrides=0,missing_keys=[],invalid_keys=[])),export_localization_artifact=AsyncMock(return_value={'artifact':{'language_tag':'ar','items':[]},'filename':'fixture.json'}),preview_localization_import=AsyncMock(return_value=dict(complete=True,importable=1,protected=0,unchanged=0,active_keys=1,missing_keys=[],invalid_keys=[])),import_localization_artifact=AsyncMock(return_value={'imported':1}),create_localization_language=AsyncMock())
    values=dict(api=api,state={},register_navigation=Mock(),show_authenticated_view=Mock(),page_client=SimpleNamespace(run_javascript=AsyncMock(return_value=0)),buffer_upload_batch=lambda event:[(values['upload_bytes'],'fixture.json','application/json')],upload_bytes=b'{"language_tag":"ar","items":[]}')
    @ui.page('/translation-feature')
    async def page():
        for name in ('title','subtitle','guidance'):values[name]=ui.label()
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):values[name]=ui.column()
        values['open']=build(values);await values['open']('fixture.key')
    await user.open('/translation-feature')
    return api,values,item


def click(user,b):b.mark(f'translation-{b.id}');user.find(marker=f'translation-{b.id}').click()
def buttons(user,icon,root=None):return sorted([b for b in (root.descendants() if root else user.find(ui.button).elements) if isinstance(b,ui.button) and b.props.get('icon')==icon],key=lambda b:b.id)
def opened(user):return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
async def settle():await asyncio.sleep(.15)


@pytest.mark.parametrize('publish',[False,True])
@pytest.mark.parametrize('failure',[False,True])
async def test_edit_reason_validation_version_payload_publish_and_error(user,publish,failure):
    api,v,item=await setup(user)
    click(user,buttons(user,'edit')[0]);await settle();d=opened(user)
    save=buttons(user,'publish' if publish else 'save',d)[0];assert not save.enabled
    with user:next(e for e in d.descendants() if isinstance(e,ui.input) and not isinstance(e,ui.textarea)).value='Fixture reason'
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value=''
    assert not save.enabled
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='نص الاختبار'
    assert save.enabled
    if failure:api.update_localization_translation.side_effect=ApiError(409,'Conflict')
    click(user,save);await settle()
    api.update_localization_translation.assert_awaited_once_with('fixture.key','ar',dict(translated_text='نص الاختبار',origin='manual',reviewed=False,generation_metadata={'fixture':True}),2,'Fixture reason')
    assert d.value==failure
    assert api.publish_localization_translation.await_count==int(publish and not failure)
    if publish and not failure:api.publish_localization_translation.assert_awaited_once_with('fixture.key','ar',3,'Fixture reason')
    assert api.localization_messages.await_count==(1 if failure else 2)


@pytest.mark.parametrize('condition',['valid','invalid','empty','failure'])
async def test_bulk_preview_reason_gates_and_confirmed_write(user,condition):
    api,v,item=await setup(user)
    if condition=='invalid':api.preview_bulk_localization_publication.return_value['invalid']=[{'message_key':'fixture.key','code':'invalid_placeholder'}]
    if condition=='empty':api.preview_bulk_localization_publication.return_value.update(items=[],count=0)
    if condition=='failure':api.bulk_review_publish_localization.side_effect=ApiError(409,'Conflict')
    click(user,buttons(user,'done_all')[0]);await settle();d=opened(user)
    confirm=buttons(user,'publish',d)[0];assert not confirm.enabled
    with user:next(e for e in d.descendants() if isinstance(e,ui.input)).value='  Fixture reason  '
    assert confirm.enabled==(condition in {'valid','failure'})
    if not confirm.enabled:api.bulk_review_publish_localization.assert_not_awaited();return
    click(user,confirm);await settle()
    api.bulk_review_publish_localization.assert_awaited_once_with('ar',[{'message_key':'fixture.key','version':2}],'Fixture reason')
    assert d.value==(condition=='failure')


@pytest.mark.parametrize('complete',[False,True])
async def test_export_preview_draft_selection_download_or_block(user,complete,monkeypatch):
    api,v,item=await setup(user);api.preview_localization_export.return_value['complete']=complete
    download=Mock();monkeypatch.setattr(user,'download',download)
    click(user,buttons(user,'download')[0]);await settle();d=opened(user)
    control=buttons(user,'download',d)[0];assert control.enabled==complete
    with user:next(e for e in d.descendants() if isinstance(e,ui.checkbox)).value=True
    await settle();api.preview_localization_export.assert_awaited_with('ar',include_reviewed_drafts=True)
    if complete:
        click(user,control);await settle()
        api.export_localization_artifact.assert_awaited_once_with('ar',include_reviewed_drafts=True)
        assert json.loads(download.call_args.args[0])=={'language_tag':'ar','items':[]}
        assert download.call_args.args[1:]==('fixture.json','application/json')
        assert not d.value
    else:api.export_localization_artifact.assert_not_awaited();download.assert_not_called()


@pytest.mark.parametrize('condition',['valid','invalid','unreadable','failure'])
async def test_import_parsing_preview_reason_and_write(user,condition):
    api,v,item=await setup(user)
    if condition=='invalid':api.preview_localization_import.return_value.update(complete=False,invalid_keys=[{'code':'artifact_key_order_mismatch'}])
    if condition=='unreadable':v['upload_bytes']=b'not json'
    if condition=='failure':api.import_localization_artifact.side_effect=ApiError(409,'Conflict')
    click(user,buttons(user,'upload_file')[0]);await settle();d=opened(user)
    confirm=buttons(user,'upload_file',d)[0];assert not confirm.enabled
    uploader=next(e for e in d.descendants() if isinstance(e,ui.upload))
    with user:uploader._multi_upload_handlers[0](SimpleNamespace())
    await settle()
    assert not confirm.enabled
    with user:next(e for e in d.descendants() if isinstance(e,ui.input)).value='  Fixture reason  '
    assert confirm.enabled==(condition in {'valid','failure'})
    if not confirm.enabled:api.import_localization_artifact.assert_not_awaited();return
    click(user,confirm);await settle()
    api.import_localization_artifact.assert_awaited_once_with('ar',{'language_tag':'ar','items':[]},'Fixture reason')
    assert d.value==(condition=='failure')

@pytest.mark.parametrize('failure',[False,True])
async def test_language_creation_requires_complete_fields_and_preserves_payload(user,failure):
    api,v,item=await setup(user)
    click(user,buttons(user,'add')[0]);await settle();d=opened(user);submit=buttons(user,'add',d)[0]
    click(user,submit);await settle();api.create_localization_language.assert_not_awaited()
    fields=[e for e in d.descendants() if isinstance(e,ui.input)]
    with user:
        for control,value in zip(fields,['fr','French','Français','Fixture reason']):control.value=value
    if failure:api.create_localization_language.side_effect=ApiError(409,'Conflict')
    click(user,submit);await settle()
    api.create_localization_language.assert_awaited_once_with(dict(language_tag='fr',english_name='French',native_name='Français',direction='ltr',is_enabled=True,is_default=False,formatting_config={'locale':'fr'}),'Fixture reason')
    assert d.value==failure
