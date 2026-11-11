"""Preserve audit destination behavior through the real feature boundary."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from frontend.webui.api_client import ApiError


def callbacks(monkeypatch):
    api = SimpleNamespace(get=AsyncMock(), disposition_page=AsyncMock())
    settings = SimpleNamespace(can_open=Mock(return_value=True), open_from_event=AsyncMock())
    names = ['open_aggregation','show_record_details','show_components','select_classification_workspace','select_entity','open_editor']
    ns = dict(Any=Any, api=api, ApiError=ApiError, ui=SimpleNamespace(notify=Mock()),
              application_settings_controller=settings, asyncio=SimpleNamespace(sleep=AsyncMock()),
              table_container=nullcontext(), render_message=lambda key,**kw:key, error_message=str,
              format_timestamp=str, __package__='frontend.webui')
    ns.update({n:AsyncMock() for n in names})
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text())
    functions=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == 'open_audit_entity']
    exec(compile(ast.Module(body=functions,type_ignores=[]),'<original audit links>','exec'),ns)
    from frontend.webui import audit_workspace as feature
    monkeypatch.setattr(feature,'ui',ns['ui'])
    monkeypatch.setattr(feature,'asyncio',ns['asyncio'])
    workspace=feature.build_audit_workspace(
        api=api,table_container=ns['table_container'],principal=lambda:None,
        selected=lambda:True,enter=Mock(),error_message=str,format_timestamp=str,
        set_connection_status=Mock(),can_open_settings=settings.can_open,
        open_settings=settings.open_from_event,open_destination=ns['open_audit_entity'],
    )
    ns.update(navigate_to_event_entity=workspace.navigate_to_event_entity,
              can_open_event_entity=workspace.can_open_event_entity)
    return ns


@pytest.mark.parametrize('kind,resource,callback', [('record','records','show_record_details'),('aggregation','aggregations','open_aggregation'),('user','users','open_editor'),('role','roles','open_editor'),('org_unit','org-units','open_editor')])
async def test_current_entity_lookup_and_origin_closure(monkeypatch,kind,resource,callback):
    n=callbacks(monkeypatch); entity={'id':7};n['api'].get.return_value=entity
    origin=Mock();e={'entity_type':kind,'entity_id':7,'_origin_dialog':origin}
    await n['navigate_to_event_entity'](e)
    n['api'].get.assert_awaited_once_with(resource,7)
    assert e['_current_entity'] is entity
    origin.close.assert_called_once();n['asyncio'].sleep.assert_awaited_once_with(.15)
    n[callback].assert_awaited_once_with(entity)
    if kind in ('user','role','org_unit'): n['select_entity'].assert_awaited_once_with(resource)


async def test_settings_link_delegates_guard_and_origin_handling_without_entity_read(monkeypatch):
    n=callbacks(monkeypatch);e={'entity_type':'application_setting','entity_id':4}
    assert n['can_open_event_entity'](e)
    n['application_settings_controller'].can_open.return_value=False
    assert not n['can_open_event_entity'](e)
    await n['navigate_to_event_entity'](e)
    n['application_settings_controller'].open_from_event.assert_awaited_once_with(e)
    n['api'].get.assert_not_awaited()


async def test_digital_component_opens_parent_components_and_reuses_current_snapshot(monkeypatch):
    n=callbacks(monkeypatch);e={'entity_type':'digital_component','entity_id':8,'_current_entity':{'id':8,'record_id':7}}
    n['api'].get.return_value={'id':7}
    await n['navigate_to_event_entity'](e)
    n['api'].get.assert_awaited_once_with('records',7)
    n['show_components'].assert_awaited_once_with({'id':7})


@pytest.mark.parametrize('status',[403,404])
async def test_missing_or_forbidden_entity_does_not_close_origin(monkeypatch,status):
    n=callbacks(monkeypatch);n['api'].get.side_effect=ApiError(status,'fixture failure')
    n['api'].disposition_page.side_effect=ApiError(404,'no retained proof')
    origin=Mock()
    await n['navigate_to_event_entity']({'entity_type':'record','entity_id':7,'_origin_dialog':origin})
    origin.close.assert_not_called();n['show_record_details'].assert_not_awaited()
    assert n['ui'].notify.called
    assert n['api'].disposition_page.await_count==int(status==404)


@pytest.mark.parametrize('kind,expected',[
    ('classification_scheme',{'initial_scheme_id':7}),
    ('classification',{'initial_scheme_id':3,'initial_classification_id':7}),
])
async def test_existing_classification_dispatch(monkeypatch,kind,expected):
    n=callbacks(monkeypatch);entity={'id':7,'classification_scheme_id':3}
    await n['navigate_to_event_entity']({'entity_type':kind,'entity_id':7,'_current_entity':entity})
    n['select_classification_workspace'].assert_awaited_once_with(**expected)
    n['api'].get.assert_not_awaited()
    # The timeline has never offered a standalone open button for these events.
    assert not n['can_open_event_entity']({'entity_type':kind})


async def test_retained_proof_preserves_origin_and_uses_existing_read_only_dialog(monkeypatch):
    from frontend.webui.disposition import destruction
    detail=AsyncMock();monkeypatch.setattr(destruction,'retained_detail',detail)
    n=callbacks(monkeypatch);n['api'].get.side_effect=ApiError(404,'deleted')
    proof={'id':7};n['api'].disposition_page.return_value=proof;origin=Mock()
    await n['navigate_to_event_entity']({'entity_type':'record','entity_id':7,'_origin_dialog':origin})
    n['api'].disposition_page.assert_awaited_once_with('retained/record/7',audit=True)
    assert detail.await_args.kwargs['proof'] is proof
    assert detail.await_args.kwargs['active']()
    origin.close.assert_not_called();n['show_record_details'].assert_not_awaited()


async def test_unknown_entity_type_notifies_without_read_or_navigation(monkeypatch):
    n=callbacks(monkeypatch);event={'entity_type':'unknown','entity_id':7}
    assert not n['can_open_event_entity'](event)
    await n['navigate_to_event_entity'](event)
    n['api'].get.assert_not_awaited();n['ui'].notify.assert_called_once()

