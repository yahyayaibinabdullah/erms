"""Bounded published-scheme searches retain the selected value and debounce input."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from frontend.webui.classification_selectors import build_scheme_selector


class Control:
    def __init__(self):
        self.value=99
        self.options={99:'Selected scheme'}
        self.handlers={}
        self.updates=0
    def on(self,event,handler):self.handlers[event]=handler
    def update(self):self.updates+=1


def test_scheme_typeahead_debounces_and_keeps_selected_option():
    async def run():
        api=SimpleNamespace(browse_schemes=AsyncMock(return_value=[{'id':1,'code':'S','title':'Scheme'}]))
        control=Control();build_scheme_selector(api)(control)
        control.handlers['input-value'](SimpleNamespace(args='first'))
        await asyncio.sleep(.05)
        control.handlers['input-value'](SimpleNamespace(args='second'))
        await asyncio.sleep(.25)
        api.browse_schemes.assert_awaited_once_with('second',limit=25)
        assert control.value==99 and control.options=={1:'S — Scheme',99:'Selected scheme'}
        assert control.updates==1
    asyncio.run(run())


def test_abandoned_scheme_query_does_not_replace_new_options():
    async def run():
        started=asyncio.Event()
        async def browse(query,**kwargs):
            assert kwargs=={'limit':25}
            if query=='slow':
                started.set();await asyncio.Event().wait()
            return [{'id':2,'code':'NEW','title':'Latest'}]
        control=Control();build_scheme_selector(SimpleNamespace(browse_schemes=browse))(control)
        control.handlers['input-value'](SimpleNamespace(args='slow'))
        await asyncio.wait_for(started.wait(),2)
        control.handlers['input-value'](SimpleNamespace(args='fast'))
        await asyncio.sleep(.25)
        assert control.options=={2:'NEW — Latest',99:'Selected scheme'}
        assert control.updates==1
    asyncio.run(run())
