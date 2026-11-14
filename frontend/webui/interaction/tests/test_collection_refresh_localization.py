"""Background collection refreshes must resolve labels in their owning page."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import pytest
from nicegui import ui,background_tasks
from frontend.webui import i18n_catalogue as i18n
from frontend.webui.entities import COLLECTION_ENTITIES

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
KEYS=['webui.select_entity.text.search_required_before_loading_results_88549c49',
      'webui.select_entity.text.large_collections_are_search_first_to_avoi_717a0f77']

@pytest.mark.parametrize('resource',['aggregations','records'])
@pytest.mark.parametrize('arabic',[True,False])
async def test_background_refresh_keeps_page_language_without_inherited_context(user,resource,arabic):
    refreshed=asyncio.Event()
    labels={KEYS[0]:'يجب إجراء بحث قبل تحميل النتائج',KEYS[1]:'يبدأ البحث في المجموعات الكبيرة قبل عرضها'} if arabic else {}
    node=next(n for n in ast.walk(ast.parse((Path(__file__).parents[2]/'collection_table.py').read_text()))
              if isinstance(n,ast.FunctionDef) and n.name=='render_table')
    elements={}
    @ui.page('/')
    def page():
        i18n.set_active_messages(labels)
        elements['subtitle']=ui.label('')
        elements['guidance']=ui.label('')
        container=ui.column()
        scope=dict(ui=ui,EntitySpec=SimpleNamespace,COLLECTION_ENTITIES=COLLECTION_ENTITIES,collection_state={'searched':False},
            table_container=container,subtitle=elements['subtitle'],guidance=elements['guidance'],
            render_message=i18n.render_message,
            render_resource_personal_sections=lambda _:ui.label('Personal sections'))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<real-render-table>','exec'),scope)
        async def refresh():
            # Deliberately do not inherit a page slot or a populated catalogue.
            i18n._active_messages.set({})
            scope['render_table'](SimpleNamespace(key=resource,search_first=True))
            refreshed.set()
        background_tasks.create(refresh())
    await user.open('/')
    await asyncio.wait_for(refreshed.wait(),3)
    for element,key in [(elements['subtitle'],KEYS[0]),(elements['guidance'],KEYS[1])]:
        assert element.text==(labels[key] if arabic else i18n.render_english(key))
