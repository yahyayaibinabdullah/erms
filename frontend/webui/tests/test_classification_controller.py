"""Per-client classification entry, restoration and lifetime contract."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock



def controller_fixture(principal):
    from unittest.mock import patch
    from frontend.webui.classification_controller import ClassificationController
    state={};auth={'principal':principal};renderer=AsyncMock();navigation=Mock()
    scope=dict(auth_state=auth,state=state,show_authenticated_view=Mock(),
               title=Mock(),subtitle=Mock(),open_editor=AsyncMock(),show_entity_history=AsyncMock())
    def begin():
        scope['show_authenticated_view']()
        state.update(resource='classification-workspace',rows=[],searched=True,aggregation_detail=None)
    def register(page,label,item,subtitle_text):
        navigation(page,label,entity_id=item['id'] if item else None,dynamic_label=bool(item))
        state['resource']=page;scope['title'].text=label;scope['subtitle'].text=subtitle_text
    owner=ClassificationController(
        api=Mock(),container=Mock(),principal=lambda:auth['principal'],
        selected=lambda:state.get('resource') in {'classification-workspace','classification-scheme-details','classification-details'},
        begin=begin,clear=Mock(),register=register,open_editor=scope['open_editor'],
        show_entity_history=scope['show_entity_history'],format_timestamp=str,display_value=str,error_message=str,
        entity_metadata_label=str,localized_disposition_value=str,direction=lambda:'rtl',
    )
    async def open(*args,**kwargs):
        with patch('frontend.webui.classification_controller.classification_workspace',renderer):
            await owner.open(*args,**kwargs)
    return SimpleNamespace(open=open,reset=owner.reset),scope,renderer,navigation


def test_classification_does_not_start_before_principal_resolves():
    controller,scope,renderer,_=controller_fixture(None)
    asyncio.run(controller.open(2,7))
    renderer.assert_not_awaited();scope['show_authenticated_view'].assert_not_called()
    assert scope['state']=={}


def test_entry_forwards_destinations_permissions_history_and_direction():
    controller,scope,renderer,navigation=controller_fixture({'global_privileges':['classifications.administer']})
    asyncio.run(controller.open(2,7))
    call=renderer.call_args.kwargs
    assert call['initial_scheme_id']==2 and call['initial_classification_id']==7
    assert call['can_transfer'] is True and call['direction']()=='rtl'
    assert call['open_editor'] is scope['open_editor'] and call['show_entity_history'] is scope['show_entity_history']
    assert call['active']()
    for page in ('classification-workspace','classification-scheme-details','classification-details'):
        call['register_page'](page,{'id':7,'code':'C','title':'Title'})
        assert scope['state']['resource']==page
        navigation.assert_called_with(page,'C — Title',entity_id=7,dynamic_label=True)
        assert scope['title'].text=='C — Title' and scope['subtitle'].text==''
    call['register_page']('classification-workspace',None)
    assert scope['subtitle'].text
    scope['state']['resource']='records';assert not call['active']()


def test_reentry_keeps_preferences_and_rejects_old_view_then_identity_reset_discards_them():
    controller,scope,renderer,_=controller_fixture({'global_privileges':[]})
    asyncio.run(controller.open())
    first=renderer.call_args.kwargs
    assert first['can_transfer'] is False
    first['preferences']['expanded']=[9]
    asyncio.run(controller.open(initial_classification_id=7))
    second=renderer.call_args.kwargs
    assert not first['active']() and second['active']()
    assert second['preferences'] is first['preferences']
    controller.reset();assert not second['active']()
    asyncio.run(controller.open())
    third=renderer.call_args.kwargs
    assert third['preferences']=={} and third['preferences'] is not second['preferences']


def test_classification_preferences_and_tokens_are_isolated_between_clients():
    a,_,ar,_=controller_fixture({'global_privileges':[]})
    b,_,br,_=controller_fixture({'global_privileges':[]})
    asyncio.run(a.open());asyncio.run(b.open())
    ar.call_args.kwargs['preferences']['query']='private'
    assert br.call_args.kwargs['preferences']=={}
    a.reset();assert br.call_args.kwargs['active']()
