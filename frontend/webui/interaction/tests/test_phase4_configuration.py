"""Page configuration must refresh fallback timezones without changing preferences."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.locale_services import set_locale_context,current_locale_context

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
NODE=next(n for n in ast.walk(ast.parse((Path(__file__).parents[2]/'app.py').read_text()))
          if isinstance(n,ast.FunctionDef) and n.name=='accept_application_configuration')


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('uses_default',[True,False])
async def test_api_page_snapshot_refreshes_only_fallback_timezone(user,language,uses_default):
    holder={}
    @ui.page('/configuration-test')
    def page():
        state={'localization':{'effective_language':language,'working_timezone':'Asia/Dubai',
                              'uses_default_working_timezone':uses_default}}
        set_locale_context(language,'Asia/Dubai')
        storage={}
        scope={'state':state,'table_container':ui.column(),'set_locale_context':set_locale_context,
               'app':SimpleNamespace(storage=SimpleNamespace(user=storage))}
        exec(compile(ast.Module(body=[NODE],type_ignores=[]),'<page-configuration>','exec'),scope)
        holder.update(state=state,storage=storage,accept=scope['accept_application_configuration'])
    await user.open('/configuration-test')
    for timezone_name in ('UTC','Asia/Tokyo'):
        with user:
            holder['accept']({'DEFAULT_WORKING_TIMEZONE':timezone_name})
            language_now,timezone_now=current_locale_context()
        assert language_now==language and timezone_now==(timezone_name if uses_default else 'Asia/Dubai')
        assert holder['state']['application_configuration']['DEFAULT_WORKING_TIMEZONE']==timezone_name
        if uses_default:assert holder['storage']['localization_context']['working_timezone']==timezone_name
        else:assert holder['storage']=={}


@pytest.mark.parametrize('initial_language,effective_language,rebuild',[('en','en',False),('en','ar',True),('ar','ar',False)])
async def test_first_bootstrap_reuses_matching_rendered_language_and_does_not_persist_settings(user,initial_language,effective_language,rebuild):
    node=next(n for n in ast.walk(ast.parse((Path(__file__).parents[2]/'app.py').read_text()))
              if isinstance(n,ast.AsyncFunctionDef) and n.name=='load_localization_context')
    holder={};scripts=[];calls=[];state={};storage={}
    async def javascript(source,**kwargs):scripts.append(source)
    async def direction(*args):pass
    async def bootstrap():
        calls.append('bootstrap')
        return {'effective_language':effective_language,'direction':'rtl' if effective_language=='ar' else 'ltr',
                'working_timezone':'UTC','catalogue_revision':1,'uses_default_working_timezone':True,
                'application_configuration':{'DEFAULT_WORKING_TIMEZONE':'UTC'}}
    async def catalogue(*args,**kwargs):return {'messages':{'common.action.save':'Save'},'fallback_keys':[]}
    @ui.page('/bootstrap-test')
    async def page():
        scope={'api':SimpleNamespace(localization_bootstrap=bootstrap,localization_catalogue=catalogue),
            'app':SimpleNamespace(storage=SimpleNamespace(user=storage)), 'state':state,
            'initial_language':initial_language,'initial_direction':'rtl' if initial_language=='ar' else 'ltr',
            'set_active_messages':lambda *args:None,'set_locale_context':set_locale_context,
            'apply_document_direction':direction,'ui':SimpleNamespace(run_javascript=javascript)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<bootstrap>','exec'),scope)
        holder['rebuild']=await scope['load_localization_context']()
    await user.open('/bootstrap-test')
    assert holder['rebuild'] is rebuild and len(scripts)==int(rebuild) and calls==['bootstrap']
    assert 'application_configuration' not in storage['localization_context']
    assert state['application_configuration']=={'DEFAULT_WORKING_TIMEZONE':'UTC'}
