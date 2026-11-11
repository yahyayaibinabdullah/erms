"""Account dialogs preserve validation, restricted sessions and preference invalidation."""
import ast,asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui,app
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def build(values):
    from frontend.webui.account_password import build_account_password
    from frontend.webui.account_preferences import build_account_preferences
    password=build_account_password(api=values['api'],get_principal=lambda:values['auth_state']['principal'],prepare_authenticated_workspace=values['prepare_authenticated_workspace'],select_dashboard=values['select_dashboard'],sign_out=values['sign_out'],error_message=host.error_message)
    preferences=build_account_preferences(api=values['api'],get_localization=lambda:values['state'].get('localization'),error_message=host.error_message,show_api_error=values['show_api_error'])
    return password,preferences


async def setup(user,*,forced=False,preferences=False,read_error=False):
    principal={'must_change_password':forced}
    api=SimpleNamespace(change_password=AsyncMock(),me=AsyncMock(return_value={'must_change_password':False}),preferences=AsyncMock(return_value={'language_tag':'en','working_timezone':'UTC','version':2}),localization_bootstrap=AsyncMock(return_value={'supported_languages':[{'language_tag':'en','native_name':'English'},{'language_tag':'ar','native_name':'العربية'}]}),update_preferences=AsyncMock())
    if read_error:api.preferences.side_effect=ApiError(403,'Denied')
    values=dict(api=api,auth_state={'principal':principal},state={},prepare_authenticated_workspace=AsyncMock(return_value=True),select_dashboard=AsyncMock(),sign_out=AsyncMock(),show_api_error=Mock())
    @ui.page('/account-test')
    async def page():
        values['password'],values['preferences']=build(values)
        for key in ('localization_context','localization_messages','localization_fallback_keys','localization_catalogue_etag'):app.storage.user[key]='fixture'
        await (values['preferences']() if preferences else values['password']())
    await user.open('/account-test')
    return api,values


def dialog(user):return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
def click(user,b):b.mark(f'account-{b.id}');user.find(marker=f'account-{b.id}').click()
def button(d,key):return next(b for b in d.descendants() if isinstance(b,ui.button) and host.strip_diagnostic_metadata(b.text)==t(key))
async def settle():await asyncio.sleep(.15)


@pytest.mark.parametrize('forced',[False,True])
async def test_password_cancel_or_forced_recovery(user,forced):
    api,v=await setup(user,forced=forced);d=dialog(user)
    assert d.props.get('persistent')
    key='webui.show_change_password.button.back_to_sign_in_a4e9c09d' if forced else 'webui.show_change_password.button.cancel_6a686362'
    click(user,button(d,key));await settle();assert not d.value
    api.change_password.assert_not_awaited();assert v['sign_out'].await_count==int(forced)


@pytest.mark.parametrize('failure,rebuild',[(False,False),(False,True),(True,False)])
@pytest.mark.parametrize('forced',[False,True])
async def test_password_validation_order_and_workspace_restart(user,forced,failure,rebuild):
    api,v=await setup(user,forced=forced);d=dialog(user)
    inputs=[i for i in d.descendants() if isinstance(i,ui.input)]
    key='webui.show_change_password.button.set_new_password_067753d1' if forced else 'webui.show_change_password.button.change_password_81533b94'
    with user:inputs[0].value='old-fixture';inputs[1].value='new-fixture';inputs[2].value='mismatch'
    click(user,button(d,key));await settle();api.change_password.assert_not_awaited();assert d.value
    with user:inputs[2].value='new-fixture'
    if failure:api.change_password.side_effect=ApiError(403,'Denied')
    v['prepare_authenticated_workspace'].return_value=not rebuild
    click(user,button(d,key));await settle()
    api.change_password.assert_awaited_once_with('old-fixture','new-fixture')
    assert d.value==failure
    assert api.me.await_count==int(not failure)
    assert v['select_dashboard'].await_count==int(not failure and not rebuild)
    if not failure:v['prepare_authenticated_workspace'].assert_awaited_once_with(api.me.return_value)


@pytest.mark.parametrize('failure',[False,True])
async def test_preferences_save_retains_version_and_clears_all_locale_storage_together(user,failure,monkeypatch):
    api,v=await setup(user,preferences=True);d=dialog(user);scripts=[]
    async def javascript(source,**kwargs):scripts.append(source)
    monkeypatch.setattr(ui,'run_javascript',javascript)
    with user:
        selects=[e for e in d.descendants() if isinstance(e,ui.select)]
        selects[0].value='ar';selects[1].value='Asia/Dubai'
    if failure:api.update_preferences.side_effect=ApiError(409,'Conflict')
    save=next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='save')
    click(user,save);await settle()
    api.update_preferences.assert_awaited_once_with('ar','Asia/Dubai',2)
    assert d.value==failure
    with user:
        for key in ('localization_context','localization_messages','localization_fallback_keys','localization_catalogue_etag'):assert (key in app.storage.user)==failure
    assert bool(scripts)==(not failure)
    if scripts:assert scripts==['window.location.reload(); true']


async def test_preferences_cancel_and_failed_read_have_no_write(user):
    api,v=await setup(user,preferences=True);d=dialog(user)
    click(user,next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='close'));await settle()
    api.update_preferences.assert_not_awaited();assert not d.value
    api.preferences.side_effect=ApiError(403,'Denied')
    with user:await v['preferences']()
    v['show_api_error'].assert_called_once()
