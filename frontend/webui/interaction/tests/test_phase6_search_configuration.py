"""Search visibility follows the API snapshot in both languages."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.config import full_text_search_enabled
from frontend.webui.locale_services import set_locale_context
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
NODE=next(n for n in ast.walk(ast.parse((Path(__file__).parents[2]/'app.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='accept_application_configuration')

@pytest.mark.parametrize('language',['en','ar'])
async def test_current_api_flag_controls_header_without_environment_or_identity_cache(user,language,monkeypatch):
    monkeypatch.setenv('WEBUI_FULL_TEXT_SEARCH_ENABLED','false')
    holder={}
    @ui.page('/phase6-search-policy')
    def page():
        state={'localization':{'effective_language':language,'working_timezone':'UTC','uses_default_working_timezone':False}}
        header=ui.row();container=ui.column();header.set_visibility(False)
        set_locale_context(language,'UTC')
        scope={'state':state,'table_container':container,'global_search_wrap':header,
            'full_text_search_enabled':full_text_search_enabled,'set_locale_context':set_locale_context,
            'app':SimpleNamespace(storage=SimpleNamespace(user={}))}
        exec(compile(ast.Module(body=[NODE],type_ignores=[]),'<api-search-configuration>','exec'),scope)
        holder.update(header=header,accept=scope['accept_application_configuration'],state=state)
    await user.open('/phase6-search-policy')
    for enabled in (True,False,True):
        with user:holder['accept']({'DEFAULT_WORKING_TIMEZONE':'UTC','FULL_TEXT_SEARCH_ENABLED':enabled})
        assert holder['header'].visible is enabled
        assert holder['state']['application_configuration']['FULL_TEXT_SEARCH_ENABLED'] is enabled
