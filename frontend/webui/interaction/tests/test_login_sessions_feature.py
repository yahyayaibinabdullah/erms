"""Session administration preserves paging, revocation and current-session cleanup."""
from frontend.webui.i18n_catalogue import strip_diagnostic_metadata as _owner_strip_diagnostic_metadata
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from nicegui import ui, app
from frontend.webui import app as host
from frontend.webui.i18n_catalogue import render_message_plain as t
from frontend.webui.api_client import ApiError

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def build(scope):
    from frontend.webui.login_sessions import build_login_sessions
    def enter(user_id):
        if user_id is None:scope['register_navigation']('login-sessions','Login sessions')
        scope['show_authenticated_view']()
        scope['state'].update(resource='login-sessions',rows=[],searched=True,aggregation_detail=None)
        scope['table_container'].clear()
    def revoked():
        app.storage.user.pop('session_token',None)
        scope['api'].set_session_token(None)
        scope['clear_signed_in_identity']()
        scope['login_dialog'].open()
    return build_login_sessions(scope['api'],table_container=scope['table_container'],enter=enter,
        principal=lambda:scope['auth_state']['principal'],current_session_revoked=revoked,
        render_user_avatar=scope['render_user_avatar'],format_timestamp=scope['format_timestamp'],
        localized_lifecycle_value=host.localized_lifecycle_value,error_message=host.error_message)


async def setup(user,*,admin=True,current=False,status='active',identity=None):
    row=dict(id=4,user_id=7,user_name='Session fixture',user_email='session@test.invalid',
             is_current=current,status=status,user_agent='Chrome/1 Macintosh',client_ip='127.0.0.1')
    api=SimpleNamespace(login_sessions_page=AsyncMock(return_value={'items':[row],'total':41,'active':1}),
                        revoke_session=AsyncMock(),revoke_user_sessions=AsyncMock(),set_session_token=Mock())
    scope=dict(api=api,auth_state={'principal':{'global_privileges':['identity.sessions.administer'] if admin else []}},state={},
               register_navigation=Mock(),show_authenticated_view=Mock(),clear_signed_in_identity=Mock(),
               login_dialog=Mock(),render_user_avatar=Mock(),format_timestamp=lambda value:'Fixed timestamp')
    @ui.page('/session-feature')
    async def page():
        for name in ('title','subtitle','guidance'):scope[name]=ui.label()
        for name in ('add_button','add_record_button','search_bar','aggregation_mode_bar','table_container'):scope[name]=ui.column()
        scope['open']=build(scope)
        app.storage.user['session_token']='synthetic-token'
        await scope['open'](identity)
    await user.open('/session-feature')
    return api,scope


def button(user,key):return next(b for b in user.find(ui.button).elements if _owner_strip_diagnostic_metadata(b.text)==t(key))
def click(user,b):b.mark(f'session-target-{b.id}');user.find(marker=f'session-target-{b.id}').click()
async def settle():await asyncio.sleep(.1)


@pytest.mark.parametrize('identity',[None,7])
async def test_entry_filters_and_paging_contract(user,identity):
    api,s=await setup(user,identity=identity)
    assert s['register_navigation'].call_count==int(identity is None)
    assert s['state']['resource']=='login-sessions'
    assert api.login_sessions_page.await_args.args==(identity,)
    assert api.login_sessions_page.await_args.kwargs==dict(limit=20,offset=0,query='',session_status='all',sort_by='date_created',descending=True,date_field='date_created',from_timestamp=None,until_timestamp=None)
    click(user,button(user,'webui.select_login_sessions.button.next_b09718d5'));await settle()
    assert api.login_sessions_page.await_args.kwargs['offset']==20
    field=next(i for i in user.find(ui.input).elements if i.label==t('webui.select_login_sessions.input.user_or_client_e41c0521'))
    with user:field.value='  fixture  '
    click(user,button(user,'webui.select_login_sessions.button.apply_filters_fc2322aa'));await settle()
    assert api.login_sessions_page.await_args.kwargs['query']=='fixture'
    assert api.login_sessions_page.await_args.kwargs['offset']==0
    click(user,button(user,'webui.select_login_sessions.button.clear_7925d8e0'));await settle()
    assert field.value==''


@pytest.mark.parametrize('admin,status,actions',[(True,'active',2),(False,'active',1),(True,'expired',0),(True,'revoked',0)])
async def test_revoke_buttons_follow_existing_privilege_and_status_rules(user,admin,status,actions):
    api,s=await setup(user,admin=admin,status=status)
    assert len([b for b in user.find(ui.button).elements if 'login-session-action-button' in b.classes])==actions


@pytest.mark.parametrize('current,all_for_user',[(False,False),(False,True),(True,False),(True,True)])
async def test_confirmed_revoke_refresh_or_current_identity_cleanup(user,current,all_for_user):
    api,s=await setup(user,current=current)
    icon='person_off' if all_for_user else 'logout'
    action=next(b for b in user.find(ui.button).elements if b.props.get('icon')==icon)
    click(user,action);await settle()
    click(user,button(user,'webui.confirm_revoke.button.cancel_9fc0545b'));await settle()
    api.revoke_session.assert_not_awaited();api.revoke_user_sessions.assert_not_awaited()
    click(user,action);await settle()
    dialogs=[d for d in user.find(ui.dialog).elements if d.value];assert len(dialogs)==1
    confirm=next(b for b in dialogs[0].descendants() if isinstance(b,ui.button) and _owner_strip_diagnostic_metadata(b.text)==t('webui.confirm_revoke.button.force_sign_out_e02eacd0'))
    click(user,confirm);await settle()
    if all_for_user:api.revoke_user_sessions.assert_awaited_once_with(7)
    else:api.revoke_session.assert_awaited_once_with(4)
    if current:
        with user:assert 'session_token' not in app.storage.user
        api.set_session_token.assert_called_once_with(None)
        s['clear_signed_in_identity'].assert_called_once();s['login_dialog'].open.assert_called_once()
        assert api.login_sessions_page.await_count==1
    else:
        assert api.login_sessions_page.await_count==2
        s['clear_signed_in_identity'].assert_not_called()


async def test_failed_revoke_keeps_current_identity(user):
    api,s=await setup(user,current=True);api.revoke_session.side_effect=ApiError(403,'Denied')
    click(user,next(b for b in user.find(ui.button).elements if b.props.get('icon')=='logout'));await settle()
    click(user,button(user,'webui.confirm_revoke.button.force_sign_out_e02eacd0'));await settle()
    s['clear_signed_in_identity'].assert_not_called()
    with user:assert app.storage.user['session_token']=='synthetic-token'


async def test_failed_read_and_page_shrink_keep_existing_request_rules(user):
    api,s=await setup(user)
    api.login_sessions_page.side_effect=ApiError(403,'Denied')
    click(user,button(user,'webui.select_login_sessions.button.refresh_85d6e787'));await settle()
    api.login_sessions_page.side_effect=None
    api.login_sessions_page.return_value={'items':[],'total':0,'active':0}
    click(user,button(user,'webui.select_login_sessions.button.next_b09718d5'));await settle()
    assert api.login_sessions_page.await_args.kwargs['offset']==0
    await user.should_see(t('webui.select_login_sessions.label.no_login_sessions_match_these_filters_2c8578fd'))
