"""Security dialog contracts, exercised without network or persistent data."""
from frontend.webui.i18n_catalogue import strip_diagnostic_metadata as _owner_strip_diagnostic_metadata
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui, events
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t
from frontend.webui.entity_selectors import build_relationship_selector

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


def owner(api, principal, direction, refresh):
    from frontend.webui.access_control_dialogs import build_access_control_dialogs
    from frontend.webui.access_explanation_dialog import build_access_explanation
    from frontend.webui.security_level_controls import build_security_level_change
    from frontend.webui.security_administration import build_profile_privilege_editor
    bind=build_relationship_selector(api,error_message=host.error_message)
    acl=build_access_control_dialogs(
        api,principal=lambda:principal.get('principal'),direction=lambda:direction['value'],
        open_aggregation=AsyncMock(),show_organization_structure=AsyncMock(),
        bind_remote_relationship_select=bind,error_message=host.error_message,
    )
    return SimpleNamespace(
        show_acl_editor=acl.show_acl_editor, show_contextual_acl_roles=acl.show_contextual_acl_roles,
        show_access_explanation=build_access_explanation(api,principal=lambda:principal.get('principal'),
            open_aggregation=AsyncMock(),localized_editor_entity=host.localized_editor_entity,error_message=host.error_message),
        show_security_level_change=build_security_level_change(api,bind_remote_relationship_select=bind,error_message=host.error_message),
        show_profile_privilege_editor=build_profile_privilege_editor(api,select_entity=refresh,error_message=host.error_message,show_api_error=host.show_api_error),
    )


class Api:
    def __init__(self):
        self.acl = dict(override_acl=[],resource_acl_version=7,inherit_acl_from_parent=False,
                        custom_acl=[],effective_acl=[],version=8,mode='custom')
        self.permissions_catalogue=AsyncMock(side_effect=lambda resource:[{'code':resource+'.'+c} for c in ('view','modify_metadata')])
        self.resource_acl=AsyncMock(side_effect=lambda *a:copy.deepcopy(self.acl))
        self.child_acl=AsyncMock(side_effect=lambda *a:copy.deepcopy(self.acl))
        self.get=AsyncMock(side_effect=self.row)
        self.replace_resource_acl=AsyncMock()
        self.replace_child_acl=AsyncMock()
        self.preview_child_acl=AsyncMock(return_value=dict(added_grants=1,removed_grants=0,potentially_affected_user_count=2))
        self.request=AsyncMock(return_value={'items':[],'has_more':False})
        self.administration_reference_page=AsyncMock(return_value={'items':[],'total':0})
        self.preview_security_level_change=AsyncMock(return_value=dict(conflict=False,affected_aggregations=[],affected_records=[],reviewed_versions={'resource':9}))
        self.apply_security_level_change=AsyncMock(return_value={'resource':{'id':11,'version':10}})
        self.explain_access=AsyncMock(return_value=dict(allowed=False,decision_code='insufficient_privilege',gates=[],subject={'effective_roles':[]},contributors={},acl={}))
        self.explainable_users=AsyncMock(return_value=[])
        self.list=AsyncMock(return_value=[
            dict(id=1,code='records.read',category='records',required_privilege_ids=[]),
            dict(id=2,code='records.update',category='records',required_privilege_ids=[1]),
        ])
        self.profile_privileges=AsyncMock(return_value=[])
        self.profile_impact=AsyncMock(return_value={'role_count':2,'user_count':3})
        self.replace_profile_privileges=AsyncMock()
    async def row(self,resource,identifier):
        return dict(id=identifier,code='TEST',name='Test',level_number=0,parent_aggregation_id=None)


async def setup(user, *, privileges=(), rtl=False):
    api=Api(); refresh=AsyncMock()
    principal={'principal':{'global_privileges':list(privileges)}}
    direction={'value':'rtl' if rtl else 'ltr'}
    result={}
    @ui.page('/security-dialog-contract')
    def page():result['owner']=owner(api,principal,direction,refresh)
    await user.open('/security-dialog-contract')
    return api,result['owner'],refresh


def dialog(user):return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
def elements(root,kind):return [e for e in root.descendants() if isinstance(e,kind)]
def button(root,key):
    label=t(key)
    return next(b for b in elements(root,ui.button) if _owner_strip_diagnostic_metadata(b.text)==label)
def click(user,b):
    b.mark(f'security-target-{b.id}')
    user.find(marker=f'security-target-{b.id}').click()
async def settle():await asyncio.sleep(.12)


@pytest.mark.parametrize('scope',['resource','aggregation','record'])
@pytest.mark.parametrize('rtl',[False,True])
async def test_acl_validation_payload_preview_and_refresh(user,scope,rtl):
    api,feature,_=await setup(user,rtl=rtl);saved=AsyncMock()
    with user:await feature.show_acl_editor('aggregations',11,scope=scope,on_saved=saved)
    d=dialog(user)
    assert not elements(d,ui.checkbox)
    click(user,button(d,'webui.show_acl_editor.button.save_acl_a2306fa4'));await settle()
    api.replace_resource_acl.assert_not_awaited();api.preview_child_acl.assert_not_awaited()
    click(user,button(d,'webui.render_principals.button.add_everyone_c070438a'));await settle()
    boxes=elements(d,ui.checkbox)
    with user:
        boxes[-1].value=True
        elements(d,ui.input)[-1].value='  regression reason  '
    await settle()
    assert all(c.value for c in boxes)
    click(user,button(d,'webui.show_acl_editor.button.save_acl_a2306fa4'));await settle()
    if scope!='resource':
        api.replace_child_acl.assert_not_awaited()
        confirmation=dialog(user);assert confirmation is not d
        click(user,button(confirmation,'webui.save_acl.button.apply_change_16aede93'));await settle()
        args=api.replace_child_acl.await_args.args
        assert args[:2]==(11,scope)
    else:args=api.replace_resource_acl.await_args.args
    payload=args[-1]
    assert payload['reason']=='regression reason'
    assert payload['version']==(7 if scope=='resource' else 8)
    kind='record' if scope=='record' else 'aggregation'
    assert payload['grants']==[{'principal_type':'everyone','role_id':None,'permission_codes':[kind+'.modify_metadata',kind+'.view']}]
    assert not d.value;saved.assert_awaited_once()


async def test_dormant_default_and_failed_write_keep_existing_state(user):
    api,feature,_=await setup(user)
    api.acl.update(mode='mirror_resource_acl',custom_acl=[{'principal_type':'everyone','role_id':None,'permission_codes':['discover']}])
    api.replace_child_acl.side_effect=ApiError(409,{'message':'Conflict'})
    with user:await feature.show_acl_editor('aggregations',11,scope='aggregation')
    d=dialog(user)
    assert all(not c.enabled for c in elements(d,ui.checkbox))
    click(user,button(d,'webui.render_acl_state.button.use_custom_default_acl_01cde39d'));await settle()
    assert all(c.enabled for c in elements(d,ui.checkbox))
    with user:elements(d,ui.input)[-1].value='regression'
    click(user,button(d,'webui.show_acl_editor.button.save_acl_a2306fa4'));await settle()
    click(user,button(dialog(user),'webui.save_acl.button.apply_change_16aede93'));await settle()
    assert d.value
    assert api.replace_child_acl.await_args.args[-1]['mode']=='custom'


async def test_blank_role_validation_and_cancel_do_not_write(user):
    api,feature,_=await setup(user)
    with user:await feature.show_acl_editor('records',11)
    d=dialog(user)
    click(user,button(d,'webui.render_principals.button.add_role_504bd3b3'));await settle()
    click(user,button(d,'webui.render_principals.button.add_role_504bd3b3'));await settle()
    assert len(elements(d,ui.select))==1
    with user:elements(d,ui.input)[-1].value='reason'
    click(user,button(d,'webui.show_acl_editor.button.save_acl_a2306fa4'));await settle()
    api.replace_resource_acl.assert_not_awaited()
    click(user,button(d,'webui.show_acl_editor.button.cancel_256f9c91'));await settle()
    assert not d.value


@pytest.mark.parametrize('principal_type,label_key', [
    ('owning_and_higher_level_unit_managers', 'authorization.oversight.managers'),
    ('effective_file_administrator', 'authorization.oversight.file_administrator'),
])
@pytest.mark.parametrize('can_browse_organization', [False, True])
async def test_record_acl_opens_with_contextual_principal(
    user, principal_type, label_key, can_browse_organization,
):
    privileges = ['organization.browse'] if can_browse_organization else []
    api, feature, _ = await setup(user, privileges=privileges)
    api.acl['override_acl'] = [
        {'principal_type': principal_type, 'role_id': None, 'permission_codes': ['record.view']},
    ]

    with user:
        await feature.show_acl_editor('records', 11)

    acl_dialog = dialog(user)
    assert t(label_key) in [
        _owner_strip_diagnostic_metadata(label.text)
        for label in elements(acl_dialog, ui.label)
    ]
    show_roles = [
        control for control in elements(acl_dialog, ui.button)
        if _owner_strip_diagnostic_metadata(control.text) == t('authorization.oversight.show_roles')
    ]
    assert len(show_roles) == int(can_browse_organization)
    if can_browse_organization:
        click(user, show_roles[0])
        await settle()
        api.request.assert_awaited_once_with(
            'GET', '/api/v1/records/11/acl-contextual-principals',
            params={'principal_type': principal_type, 'limit': 25, 'offset': 0},
        )
    else:
        api.request.assert_not_awaited()
    api.replace_resource_acl.assert_not_awaited()


@pytest.mark.parametrize('allowed',[False,True])
async def test_explanation_subject_gate_and_server_decision(user,allowed):
    api,feature,_=await setup(user,privileges=['authorization.explain'] if allowed else [])
    with user:await feature.show_access_explanation('record',11)
    d=dialog(user)
    assert len(elements(d,ui.select))==(2 if allowed else 1)
    assert api.explain_access.await_args.args[0]=={'resource_type':'record','resource_id':11,'operation':'record.view'}
    assert t('webui.load_explanation.label.denied_c4e96002') in [_owner_strip_diagnostic_metadata(e.text) for e in elements(d,ui.label)]
    if allowed:
        with user:elements(d,ui.select)[-1].set_options({7:'Another user'},value=7)
        await settle()
        assert api.explain_access.await_args.args[0]['user_id']==7


async def test_old_explanation_response_does_not_replace_new_operation(user):
    api,feature,_=await setup(user)
    with user:await feature.show_access_explanation('record',11)
    d=dialog(user);op=elements(d,ui.select)[0]
    gate=asyncio.Event();entered=asyncio.Event();old=copy.deepcopy(api.explain_access.return_value)
    old.update(allowed=True,decision_code='allowed')
    async def delayed(payload):entered.set();await gate.wait();return old
    api.explain_access.side_effect=delayed
    click(user,button(d,'webui.show_access_explanation.button.explain_46823543'))
    await asyncio.wait_for(entered.wait(),2)
    api.explain_access.side_effect=None
    with user:op.value='record.update'
    await settle();gate.set();await settle()
    assert t('webui.load_explanation.label.allowed_4d6e5631') not in [_owner_strip_diagnostic_metadata(e.text) for e in elements(d,ui.label)]


@pytest.mark.parametrize('conflict',[False,True])
async def test_security_change_review_reason_versions_and_refresh(user,conflict):
    api,feature,_=await setup(user);saved=AsyncMock()
    api.preview_security_level_change.return_value['conflict']=conflict
    with user:await feature.show_security_level_change('record',{'id':11,'security_level_id':1},saved)
    d=dialog(user);target=elements(d,ui.select)[0]
    apply=button(d,'webui.show_security_level_change.button.apply_change_aee38579')
    assert not apply.enabled
    with user:target.set_options({1:'General',2:'Restricted'},value=2)
    await settle()
    click(user,button(d,'webui.show_security_level_change.button.review_change_e13907fc'));await settle()
    assert apply.enabled is not conflict
    if conflict:
        with user:elements(d,ui.select)[1].value='raise_ancestors'
        await settle();assert not apply.enabled
        click(user,button(d,'webui.show_security_level_change.button.review_change_e13907fc'));await settle()
    click(user,apply);await settle();api.apply_security_level_change.assert_not_awaited()
    with user:elements(d,ui.textarea)[0].value='  approved reason  '
    click(user,apply);await settle()
    assert api.apply_security_level_change.await_args.kwargs=={'reason':'approved reason'}
    assert api.apply_security_level_change.await_args.args[0]['reviewed_versions']=={'resource':9}
    saved.assert_awaited_once_with({'id':11,'version':10});assert not d.value


async def test_profile_dependency_selection_reason_and_refresh(user):
    api,feature,refresh=await setup(user)
    with user:await feature.show_profile_privilege_editor({'id':4,'name':'Profile','version':6})
    d=dialog(user);boxes=elements(d,ui.checkbox)
    with user:boxes[1].value=True
    await settle();assert all(b.value for b in boxes)
    save=button(d,'webui.show_profile_privilege_editor.button.save_privileges_9223c6cc')
    click(user,save);await settle();api.replace_profile_privileges.assert_not_awaited()
    with user:elements(d,ui.textarea)[0].value='  profile reason  '
    click(user,save);await settle()
    assert api.replace_profile_privileges.await_args.args==(4,6,[1,2])
    assert api.replace_profile_privileges.await_args.kwargs=={'reason':'profile reason'}
    refresh.assert_awaited_once_with('profiles');assert not d.value


async def test_profile_prerequisite_removal_requires_confirmation(user):
    api,feature,_=await setup(user);api.profile_privileges.return_value=[{'id':1},{'id':2}]
    with user:await feature.show_profile_privilege_editor({'id':4,'name':'Profile','version':6})
    d=dialog(user);boxes=elements(d,ui.checkbox)
    with user:boxes[0].value=False
    await settle();confirm=dialog(user);assert confirm is not d
    assert all(b.value for b in boxes)
    click(user,button(confirm,'webui.show_profile_privilege_editor.button.cancel_d03380ff'));await settle()
    assert all(b.value for b in boxes);api.replace_profile_privileges.assert_not_awaited()


async def test_contextual_roles_paging_and_closed_dialog_response(user):
    api,feature,_=await setup(user)
    api.request.return_value={'items':[],'has_more':True}
    with user:await feature.show_contextual_acl_roles('aggregations',11,'effective_file_administrator')
    d=dialog(user)
    assert not button(d,'authorization.oversight.previous').enabled
    click(user,button(d,'authorization.oversight.next'));await settle()
    assert api.request.await_args.kwargs['params']=={'principal_type':'effective_file_administrator','limit':25,'offset':25}
    gate=asyncio.Event();entered=asyncio.Event()
    async def delayed(*a,**kw):entered.set();await gate.wait();return {'items':[],'has_more':False}
    api.request.side_effect=delayed
    click(user,button(d,'authorization.oversight.next'))
    await asyncio.wait_for(entered.wait(),2)
    click(user,button(d,'authorization.oversight.close'));await settle();gate.set();await settle()
    assert not d.value


@pytest.mark.parametrize('name,method,args',[
    ('show_acl_editor','permissions_catalogue',('records',11)),
    ('show_security_level_change','get',('record',{'id':11,'security_level_id':1},AsyncMock())),
    ('show_profile_privilege_editor','profile_impact',({'id':4,'name':'Profile','version':6},)),
])
async def test_open_failure_does_not_render_editable_dialog(user,name,method,args):
    api,feature,_=await setup(user);getattr(api,method).side_effect=ApiError(403,{'message':'Denied'})
    with user:await getattr(feature,name)(*args)
    assert not [d for d in user.client.elements.values() if isinstance(d,ui.dialog) and d.value]
    api.replace_profile_privileges.assert_not_awaited();api.replace_resource_acl.assert_not_awaited()


async def test_explanation_subject_picker_is_bounded_and_preserves_selection(user):
    api,feature,_=await setup(user,privileges=['authorization.explain'])
    api.explainable_users.return_value=[{'id':i,'name':f'User {i}','email':f'{i}@test.invalid'} for i in range(26)]
    with user:await feature.show_access_explanation('record',11)
    d=dialog(user);picker=elements(d,ui.select)[1]
    # Exercise the same public event handlers that the browser fires.
    with user:
        listener=[v for v in picker._event_listeners.values() if v.type=='popupShow'][-1]
        await listener.handler()
    await settle()
    assert len(picker.options)==25
    assert api.explainable_users.await_args.kwargs=={'query':'','limit':26,'offset':0}
    with user:picker.value=2
    await settle()
    api.explainable_users.return_value=[{'id':26,'name':'Other','email':'other@test.invalid'}]
    click(user,button(d,'webui.render_collection.button.load_more_755f4879'));await settle()
    assert picker.value==2 and 26 in picker.options
    assert api.explainable_users.await_args.kwargs['offset']==25
