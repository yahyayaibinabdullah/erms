"""Inspector authority, asynchronous failure and destination/cleanup contracts."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from frontend.webui import translation_inspector as host

NAMES=('clear_translation_inspector_session','ensure_translation_inspector_asset','refresh_inspectable_chrome','synchronize_translation_inspector','toggle_translation_inspector','open_inspected_translation')

def build():
    nodes={n.name:n for n in ast.walk(ast.parse(Path(host.__file__).read_text())) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in NAMES}
    values=dict(vars(host))
    values.update(page_client=SimpleNamespace(id='fixture',run_javascript=AsyncMock(return_value=True)),auth_state={'principal':{'global_privileges':['localization.administer']}},enable_diagnostic_metadata=Mock(),disable_diagnostic_metadata=Mock(),ui=SimpleNamespace(notify=Mock()),select_translation_administration=AsyncMock())
    for name in ('diagnostics_separator','diagnostics_section','inspector_switch','brand_row','brand_mark','brand_name','user_menu'):values[name]=Mock()
    values['principal']=lambda:values['auth_state'].get('principal')
    values['inspector_switch'].value=False
    async def navigate(callback):await callback()
    values['guarded_page_navigation']=AsyncMock(side_effect=navigate)
    exec(compile(ast.Module(body=[nodes[n] for n in NAMES],type_ignores=[]),host.__file__,'exec'),values)
    return values

@pytest.mark.asyncio
@pytest.mark.parametrize('authorized',[False,True])
@pytest.mark.parametrize('failure',[False,True])
async def test_synchronize_privilege_visibility_restore_and_failure(authorized,failure):
    v=build()
    if failure:v['page_client'].run_javascript.side_effect=RuntimeError('fixture')
    await v['synchronize_translation_inspector']({'localization.administer'} if authorized else set())
    v['enable_diagnostic_metadata' if authorized else 'disable_diagnostic_metadata'].assert_called_once_with('fixture')
    for name in ('diagnostics_separator','diagnostics_section'):v[name].set_visibility.assert_called_once_with(authorized)
    assert v['inspector_switch'].value is (authorized and not failure)
    if not authorized:v['page_client'].run_javascript.assert_not_awaited()
    if authorized and not failure:
        calls=v['page_client'].run_javascript.await_args_list
        assert 'new Promise' in calls[0].args[0] and '.initialize(' in calls[1].args[0] and '.restore()' in calls[2].args[0]

@pytest.mark.asyncio
@pytest.mark.parametrize('authorized',[False,True])
async def test_toggle_propagates_authority_and_recovers_load_failure(authorized):
    v=build();v['auth_state']['principal']['global_privileges']=['localization.administer'] if authorized else []
    await v['toggle_translation_inspector'](SimpleNamespace(value=True))
    assert f'setAuthorized({str(authorized).lower()})' in v['page_client'].run_javascript.await_args.args[0]
    v['page_client'].run_javascript.side_effect=RuntimeError('fixture')
    await v['toggle_translation_inspector'](SimpleNamespace(value=True))
    assert v['inspector_switch'].value is False;v['ui'].notify.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize('authorized,key',[(False,'fixture.key'),(True,''),(True,' fixture.key ')])
async def test_inspect_open_obeys_privilege_key_and_navigation_guard(authorized,key):
    v=build();v['auth_state']['principal']['global_privileges']=['localization.administer'] if authorized else []
    v['page_client'].run_javascript.return_value=key
    await v['open_inspected_translation'](None)
    if authorized and key.strip():
        v['user_menu'].close.assert_called_once();v['guarded_page_navigation'].assert_awaited_once();v['select_translation_administration'].assert_awaited_once_with(initial_key='fixture.key')
    else:v['select_translation_administration'].assert_not_awaited();v['user_menu'].close.assert_not_called()

@pytest.mark.asyncio
async def test_cleanup_uses_captured_client_and_existing_root_history_replacement():
    v=build();await v['clear_translation_inspector_session']()
    v['page_client'].run_javascript.assert_awaited_once_with("window.wathiqTranslationInspector?.clearSession(); history.replaceState(null, '', '/'); true",timeout=5)
