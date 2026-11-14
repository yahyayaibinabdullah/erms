"""Custody status, retained refresh, isolation and existing destination actions."""
import ast
import inspect
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def report(severity=None,filled=False):
    role=dict(id=7,code='CUSTODY',name='Custody role',profile_code='INFO_GOV_OFFICER',profile_name='Governance officer',security_level_code='TOP',security_level_name='Highest',level_number=9,is_highest_clearance=True,effective=True,has_required_custody_privileges=True,missing_custody_privilege_codes=[],current_assignee_count=6,effective_assignee_count=6,universal_custodian_count=6,qualifies_for_universal_custody=True)
    assignments=[dict(user_id=i,user_name=f'Custodian {i}',user_email=f'custodian{i}@test.invalid',role_id=7,role_code='CUSTODY',role_name='Custody role',valid_from='2026-01-01',valid_until=None,effective_for_universal_custody=True,ineffective_reasons=[]) for i in range(6)] if filled else []
    assignments += [dict(user_id=i,user_name=f'Attention {i}',user_email=f'attention{i}@test.invalid',role_id=7,role_code='CUSTODY',role_name='Custody role',effective_for_universal_custody=False,ineffective_reasons=['assignment_not_current']) for i in range(10,16)] if filled else []
    return dict(highest_security_level={'code':'TOP','name':'Highest','level_number':9},highest_clearance_custodian_count=6 if filled else 0,warnings=[{'severity':severity}] if severity else [],governance_roles=[role] if filled else [],assignments=assignments,disposition_configuration_warnings=[])

def build(scope):
    from frontend.webui.governance_custody import build_governance_custody
    scope.update(get_principal=lambda:scope['auth_state'].get('principal'),
                 get_resource=lambda:scope['state'].get('resource'),
                 enter_governance_custody=lambda:scope['state'].update(resource='governance-custody'),
                 clear_collection=lambda:scope['collection_state'].update(rows=[],searched=True),
                 can_open_settings=scope['application_settings_controller'].can_open,
                 open_settings=scope['application_settings_controller'].open_from_custody)
    return build_governance_custody(**{key:scope[key] for key in inspect.signature(build_governance_custody).parameters})

async def setup(user,data=None,principal=True):
    h=dict(vars(host),state={},collection_state={},auth_state={'principal':{'global_privileges':['authorization.administer']} if principal is True else principal},api=SimpleNamespace(governance_custody=AsyncMock(return_value=data or report())),register_navigation=Mock(),show_authenticated_view=Mock(),error_message=lambda error:'Rejected custody refresh',format_timestamp=str,select_entity=AsyncMock(),select_user_details=AsyncMock(),select_role_details=AsyncMock(),application_settings_controller=SimpleNamespace(can_open=lambda:True,open_from_custody=AsyncMock()))
    @ui.page('/custody-contract')
    async def page():
        for name in ('title','subtitle','guidance'):h[name]=ui.label('')
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button'):h[name]=ui.column()
        h['table_container']=ui.column();h['open']=build(h);await h['open']()
    await user.open('/custody-contract');return h
async def settle():await asyncio.sleep(.12)
def click(user,key):user.find(t(key)).click()

@pytest.mark.parametrize('severity,css',[(None,'healthy'),('warning','warning'),('critical','critical')])
async def test_status_empty_guidance_and_existing_configuration_links(user,severity,css):
    h=await setup(user,report(severity));assert any('governance-status-'+css in e.classes for e in user.client.elements.values())
    click(user,'webui.select_governance_custody.button.configure_a_role_29c8cb79');await settle();h['select_entity'].assert_awaited_with('roles')
    click(user,'webui.select_governance_custody.button.review_profiles_72e9cc1a');await settle();h['select_entity'].assert_awaited_with('profiles')

@pytest.mark.parametrize('principal',[None,{'global_privileges':[]}])
async def test_unauthorized_entry_does_not_fetch_or_change_page(user,principal):
    h=await setup(user,principal=principal);h['api'].governance_custody.assert_not_awaited();h['register_navigation'].assert_not_called();assert h['state']=={}

@pytest.mark.parametrize('boundary',['page','identity','newer'])
async def test_late_report_cannot_replace_current_view(user,boundary):
    h=await setup(user);started=asyncio.Event();release=asyncio.Event()
    async def delayed():started.set();await release.wait();return report(filled=True)
    h['api'].governance_custody.side_effect=delayed
    click(user,'settings.action.refresh');await asyncio.wait_for(started.wait(),3)
    if boundary=='page':h['state']['resource']='records'
    elif boundary=='identity':h['auth_state']['principal']={'global_privileges':['authorization.administer']}
    else:
        h['api'].governance_custody.side_effect=None
        h['api'].governance_custody.return_value=report()
        with user:await h['open']()
    release.set();await settle();await user.should_not_see('Custodian 0')

async def test_failed_warm_refresh_keeps_report_and_does_not_show_loading(user):
    h=await setup(user,report(filled=True));h['api'].governance_custody.side_effect=ApiError(503,'Unavailable')
    click(user,'settings.action.refresh');await settle();await user.should_see('Custodian 0');await user.should_not_see(t('settings.custody.loading'))
    assert any('Rejected custody refresh' in str(m) for m in user.notify.messages)

async def test_both_pagers_and_user_role_actions(user):
    h=await setup(user,report(filled=True));await user.should_see('Custodian 0');await user.should_not_see('Custodian 5');await user.should_see('Attention 10');await user.should_not_see('Attention 15')
    next_label=t('webui.select_governance_custody.button.next_1b4b15c1')
    controls=sorted([b for b in user.find(ui.button).elements if b.text==next_label],key=lambda b:b.id)
    for b in controls:b.mark('next-'+str(b.id));user.find(marker='next-'+str(b.id)).click()
    await settle();await user.should_see('Custodian 5');await user.should_see('Attention 15');await user.should_not_see('Custodian 0')
    card=next(e for e in user.client.elements.values() if 'governance-custody-assignment-card' in e.classes and any(getattr(c,'text',None)=='Custodian 5' for c in e.descendants()))
    for icon,callback,identity in [('person','select_user_details',5),('badge','select_role_details',7)]:
        button=next(b for b in card.descendants() if isinstance(b,ui.button) and b.props.get('icon')==icon);button.mark('destination-'+icon);user.find(marker='destination-'+icon).click();await settle();h[callback].assert_awaited_with(identity)

async def test_disposition_warning_uses_existing_settings_entry(user):
    data=report();data['disposition_configuration_warnings']=[{'code':'destination_unset','setting_key':'DISPOSITION_CLASSIFICATION_SCHEME_ID'}]
    h=await setup(user,data);click(user,'settings.custody.open');await settle();h['application_settings_controller'].open_from_custody.assert_awaited_once_with()
