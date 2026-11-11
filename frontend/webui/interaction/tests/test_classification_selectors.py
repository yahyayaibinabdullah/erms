"""The two existing classification pickers retain independent pagination and selection."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


def picker(api,kind,direction):
    from frontend.webui.classification_selectors import build_classification_pickers
    editor,advanced=build_classification_pickers(
        api,direction=lambda:direction,
        tree_expander_icon=lambda expanded:'expand_more' if expanded else 'chevron_left' if direction=='rtl' else 'chevron_right',
        error_message=str,
    )
    return advanced if kind=='advanced' else editor



@pytest.mark.parametrize('kind',['editor','advanced'])
@pytest.mark.parametrize('direction',['ltr','rtl'])
async def test_picker_pages_branches_selects_terminal_and_retains_existing_value(user,kind,direction):
    calls=[]
    async def listing(resource,**params):
        calls.append((resource,params))
        assert params['limit']==26
        if resource=='classification-schemes':rows=[dict(id=1,code='S',title='Scheme')]
        elif params.get('roots_only'):rows=[dict(id=2,code='B',title='Branch',is_terminal=False)]
        else:rows=[dict(id=i+10,code=f'C{i:02}',title=f'Child {i:02}',is_terminal=True) for i in range(28)]
        return rows[params['offset']:params['offset']+params['limit']]
    holder={}
    @ui.page('/classification-picker')
    async def page():
        control=ui.select({99:'Existing'},value=99);holder['control']=control
        await picker(SimpleNamespace(list=listing),kind,direction)(control)
    await user.open('/classification-picker')
    def choose(text):
        label=next(e for e in user.find(ui.label).elements if e.text==text)
        card=label.parent_slot.parent
        while not isinstance(card,ui.card):card=card.parent_slot.parent
        card.mark('choice');user.find(marker='choice').click()
    choose('Scheme');await user.should_see('Branch')
    choose('Branch');await user.should_see('Child 00')
    await user.should_not_see('Child 26')
    assert holder['control'].value==99
    user.find('Load more').click();await user.should_see('Child 26')
    choose('Child 26');await asyncio.sleep(.03)
    assert holder['control'].value==36
    assert 99 in holder['control'].options and 36 in holder['control'].options
    assert not any(d.value for d in user.find(ui.dialog).elements)
    assert calls[-1]==('classifications',{'classification_scheme_id':1,'limit':26,'offset':25,'parent_classification_id':2})


@pytest.mark.parametrize('kind',['editor','advanced'])
async def test_failed_picker_request_keeps_selected_relationship(user,kind):
    holder={}
    @ui.page('/failed-classification-picker')
    async def page():
        control=ui.select({99:'Existing'},value=99);holder['control']=control
        await picker(SimpleNamespace(list=AsyncMock(side_effect=ApiError(503,'Unavailable'))),kind,'ltr')(control)
    await user.open('/failed-classification-picker')
    assert holder['control'].value==99 and holder['control'].options=={99:'Existing'}
    assert user.notify.messages
