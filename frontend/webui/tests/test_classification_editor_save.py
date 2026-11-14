"""Exercise the real editor Save boundary, including retention and translation writes."""
import ast
from frontend.webui.organization_editor import organization_change_reason
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from frontend.webui.api_client import ApiError
from frontend.webui.entities import ENTITIES
from frontend.webui.classification_editor import prepare_retention_payload
from frontend.webui.i18n_catalogue import render_message, strip_diagnostic_metadata


def save_scope(*, creating=False, values=None, rule=None, translation=None, failure=None):
    tree=ast.parse((Path(__file__).parents[1]/'entity_editor.py').read_text())
    editor=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='open_editor')
    save=next(n for n in ast.walk(editor) if isinstance(n,ast.AsyncFunctionDef) and n.name=='save')
    row={'id':7,'version':3,'classification_scheme_id':2,'title':'Original'}
    calls=[]
    async def write(kind,*args,**kwargs):
        calls.append((kind,deepcopy(args),deepcopy(kwargs)))
        if failure==kind:raise ApiError(409,'conflict')
        return dict(row,version=4 if kind!='translation' else 5)
    api=SimpleNamespace(create=lambda *a,**k:write('create',*a,**k),update=lambda *a,**k:write('update',*a,**k),
                        put_classification_retention_rule=lambda *a,**k:write('rule',*a,**k),
                        update_entity_translation=lambda *a,**k:write('translation',*a,**k))
    scope=dict(prepare_retention_payload=prepare_retention_payload,ApiError=ApiError,spec=ENTITIES['classifications'],row=row,creating=creating,controls={},
               translation_only=False,prepare_entity_translation_update=lambda:translation,
               form_payload=lambda *a,**k:deepcopy(values or {'title':'Changed','classification_scheme_id':2}),
               retention_rule=rule,api=api,resource_change_reason=None, lookup_rows_by_field={}, security_change_reason=None, organization_change_reason=organization_change_reason,profile_change_reason=None,
               dialog=Mock(),ui=Mock(),render_message=render_message,strip_diagnostic_metadata=strip_diagnostic_metadata,
               editor_entity='classification',on_saved=AsyncMock(),load_recent=AsyncMock(),
               validation_error_message=str,show_api_error=Mock(),highlight_medium_error=Mock())
    exec(compile(ast.Module(body=[save],type_ignores=[]),'<actual-classification-save>','exec'),scope)
    return scope,calls


@pytest.mark.parametrize('creating',[True,False])
@pytest.mark.parametrize('direct',[False,True])
def test_classification_save_preserves_retention_payload_order_and_versions(creating,direct):
    values={'title':'Changed','classification_scheme_id':2}
    rule=dict(current_period_years=2,intermediate_period_years=3,final_disposition='destruction',instructions='Keep')
    if direct:values.update(rule)
    translation=None if creating else ('ar',{'title':'عنوان'},'Review')
    scope,calls=save_scope(creating=creating,values=values,rule={'version':9},translation=translation)
    asyncio.run(scope['save']())
    assert [c[0] for c in calls]==(['create'] if creating else ['update']+(['rule'] if direct else [])+['translation'])
    payload=calls[0][1][1 if creating else 3]
    assert not set(rule)&payload.keys()
    if creating:
        assert payload['classification_scheme_id']==2
        assert payload.get('retention_rule')==(rule if direct else None)
    else:
        assert 'classification_scheme_id' not in payload
        if direct:assert calls[1][1]==(7,rule,9)
        assert calls[-1][1]==('classifications',7,'ar',{'title':'عنوان'},4,'Review')
        assert scope['row']['version']==5
    scope['dialog'].close.assert_called_once()
    scope['load_recent'].assert_awaited_once()
    scope['on_saved'].assert_awaited_once()


@pytest.mark.parametrize('values',[{'instructions':'Partial'},{'current_period_years':0},{'final_disposition':'destruction'}])
def test_incomplete_direct_retention_rule_blocks_all_writes(values):
    scope,calls=save_scope(values=values)
    asyncio.run(scope['save']())
    assert not calls
    scope['dialog'].close.assert_not_called()
    assert 'requires both periods' in scope['ui'].notify.call_args.args[0]


@pytest.mark.parametrize('failure',['update','rule','translation'])
def test_rejected_classification_write_keeps_dialog_and_does_not_refresh(failure):
    scope,calls=save_scope(values=dict(current_period_years=0,intermediate_period_years=0,final_disposition='destruction'),
                           translation=('ar',{'title':'عنوان'},'Review'),failure=failure)
    asyncio.run(scope['save']())
    assert calls[-1][0]==failure
    scope['dialog'].close.assert_not_called()
    scope['on_saved'].assert_not_awaited()
    scope['load_recent'].assert_not_awaited()
    scope['show_api_error'].assert_called_once()
