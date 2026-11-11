"""Hold drawer visibility preserves privilege and visible-hold fallback behavior."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from frontend.webui import hold_navigation as host
from frontend.webui.api_client import ApiError

@pytest.mark.asyncio
@pytest.mark.parametrize('privilege,total,error,visible',[
    ('holds.administer',0,False,True),('holds.held_items.manage_all',0,False,True),
    ('',1,False,True),('',0,False,False),('',1,True,False),
])
async def test_hold_visibility_privilege_and_api_fallback(privilege,total,error,visible):
    node=next(n for n in ast.walk(ast.parse(Path(host.__file__).read_text())) if isinstance(n,ast.AsyncFunctionDef) and n.name=='refresh_hold_navigation')
    api=SimpleNamespace(holds_page=AsyncMock(return_value={'total':total}))
    if error:api.holds_page.side_effect=ApiError(403,'Denied')
    scope=dict(vars(host));scope.update(api=api,auth_state={'principal':{'global_privileges':[privilege]}},holds_navigation=Mock(),refresh_drawer_headings=Mock())
    scope['principal']=lambda:scope['auth_state'].get('principal')
    exec(compile(ast.Module(body=[node],type_ignores=[]),host.__file__,'exec'),scope)
    await scope['refresh_hold_navigation']()
    scope['holds_navigation'].set_visibility.assert_called_once_with(visible);scope['refresh_drawer_headings'].assert_called_once()
    if privilege:api.holds_page.assert_not_awaited()
    else:api.holds_page.assert_awaited_once_with(limit=1)
