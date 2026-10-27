import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from frontend.webui.api_client import ApiError
from frontend.webui.capabilities import can_edit_entity_translation


def test_untouched_translation_fields_do_not_block_unrelated_metadata_save():
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    state_node = next(node for node in ast.walk(tree) if isinstance(node, ast.AnnAssign)
                      and isinstance(node.target, ast.Name) and node.target.id == 'translation_state')
    pending = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name == 'pending_entity_translation')
    state = eval(compile(ast.Expression(state_node.value), 'state', 'eval'), {
        'multilingual_fields': {'roles': ('name', 'description')}, 'spec': SimpleNamespace(key='roles'),
    })
    controls = {field: SimpleNamespace(value=None) for field in ('name', 'description')}
    namespace = {'translation_state': state, 'translation_controls': controls,
                 'language_control': SimpleNamespace(value=None), 'render_message': lambda key: key}
    exec(compile(ast.Module(body=[pending], type_ignores=[]), 'pending', 'exec'), namespace)
    assert namespace['pending_entity_translation']() is None
    controls['name'].value = 'Actual translation edit'
    with pytest.raises(ValueError, match='load_the_selected_language'):
        namespace['pending_entity_translation']()


def test_user_administration_includes_entity_translation_permission():
    assert can_edit_entity_translation('users', ['identity.users.administer'])
    assert not can_edit_entity_translation('users', ['localization.administer'])
    assert not can_edit_entity_translation('users', ['role.modify_metadata'])
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text())
    block=next(node for node in ast.walk(tree) if isinstance(node,ast.If)
               and 'translation_edit_allowed' in ast.unparse(node.test)
               and 'multilingual_fields' in ast.unparse(node.test))
    assert 'not creating' in ast.unparse(block.test)


@pytest.mark.asyncio
@pytest.mark.parametrize('language,message',[
    ('ar','لا يسمح حسابك الحالي بهذا الإجراء'),
    ('en','The current account is not authorized for this operation'),
])
async def test_failed_entity_translation_load_displays_error_in_editor_context(language,message):
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text())
    loader=next(node for node in ast.walk(tree) if isinstance(node,ast.AsyncFunctionDef)
                and node.name=='load_entity_translation')
    class Control:
        value=''
        enabled=True
        def disable(self):self.enabled=False
        def enable(self):self.enabled=True
        def update(self):pass
    class Client:
        active=False
        def __enter__(self):self.active=True
        def __exit__(self,*args):self.active=False
    client=Client();statuses=[];notices=[];calls=[]
    async def denied(*args):
        calls.append(args)
        raise ApiError(403,'forbidden')
    def localized_error(error):
        assert client.active
        assert error.status_code==403
        return message
    def show_error(error):
        assert client.active
        notices.append(localized_error(error))
    controls={'name':Control(),'description':Control()}
    state={'loaded_language':None,'load_generation':0,'baseline':{}}
    namespace={'language_control':SimpleNamespace(value=language),'translation_state':state,
               'translation_controls':controls,'translation_status':SimpleNamespace(client=client,set_text=statuses.append),
               'translation_loading_status':'Loading','translation_loaded_status':'Loaded',
               'api':SimpleNamespace(entity_translation=denied),'spec':SimpleNamespace(key='users'),
               'row':{'id':17,'version':1},'dialog':SimpleNamespace(value=True),
               'ApiError':ApiError,'error_message':localized_error,'show_api_error':show_error}
    exec(compile(ast.Module(body=[loader],type_ignores=[]),'loader','exec'),namespace)
    await namespace['load_entity_translation']()
    assert len(calls)==1
    assert statuses[-1]==message and notices==[message]
    assert state['loaded_language'] is None
    assert all(not control.enabled for control in controls.values())
    assert namespace['row']['version']==1
