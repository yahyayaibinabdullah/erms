"""Exercise the real shared viewer and staged cards, not just source strings."""
import ast
import asyncio
import base64
import inspect
from pathlib import Path
import pytest
from nicegui import ui,context,core
from nicegui.client import Client
from frontend.webui import app as webapp
from frontend.webui.api_client import ApiError,ErmsApiClient
from frontend.webui.i18n_catalogue import render_message_plain
from frontend.webui.tests.test_disposition_tasks import host

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII=')
PDF=b'%PDF-1.4\n%%EOF'


def component(identity=1,*,mime='image/png',name=None,order=None,status='staged'):
    return dict(id=identity,draft_id=17,component_order=order or identity,file_name=name or f'File {identity}',mime_type=mime,content_status=status,size_in_bytes=1)


class Api:
    def __init__(self):self.calls=[];self.fail=False
    async def open_original_pdf(self,component_id,draft_id=None):
        self.calls.append((draft_id,component_id))
        if self.fail:raise ApiError(410,'expired')
        return f'/preview-pdf/drafts/{draft_id}/{component_id}/fixture'
    async def view_draft_component(self,draft_id,component_id):
        self.calls.append((draft_id,component_id))
        if self.fail:raise ApiError(410,'expired')
        return PNG if component_id==1 else PDF


def viewer(api):
    from frontend.webui.component_preview import build_component_preview
    return build_component_preview(api=api,error_message=lambda e:'Preview unavailable')


class JSResult:
    def __await__(self):
        async def result():return True
        return result().__await__()


async def click(button):
    handler=next(e.handler for e in button._event_listeners.values() if e.type=='click')
    result=handler(None) if inspect.signature(handler).parameters else handler()
    if inspect.isawaitable(result):await result
    await asyncio.sleep(.01)


def patch_js(monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    calls=[]
    def run(self,script,**kw):calls.append(script);return JSResult()
    monkeypatch.setattr(Client,'run_javascript',run)
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    return calls


@pytest.mark.asyncio
async def test_only_completed_supported_staged_cards_offer_preview_with_accessible_name(host):
    seen=[]
    with host:
        webapp.render_component_cards([
            component(),component(2,mime='application/zip'),component(3,status='uploading'),
        ],lambda *a:None,lambda *a:None,on_view=seen.append,staged_preview=True)
        buttons=[e for e in host.descendants() if isinstance(e,ui.button) and e._props.get('icon')=='visibility']
        assert len(buttons)==1 and buttons[0].enabled and not buttons[0]._props.get('disable')
        assert buttons[0]._props['aria-label']==render_message_plain('webui.render_compact_resource_result.tooltip.preview_digital_component_71925875')
        await click(buttons[0])
    assert [r['id'] for r in seen]==[1]
    assert not webapp.component_is_previewable(component())
    assert webapp.component_is_previewable(component(),staged=True)


@pytest.mark.asyncio
async def test_staged_shared_viewer_switches_formats_without_saved_record_privileges_or_requests(host,monkeypatch):
    patch_js(monkeypatch);api=Api()
    with host:
        await viewer(api)(None,1,draft_id=17,staged_components=[component(2,mime='application/pdf',order=1),component(order=2),component(3,mime='application/zip')],source_active=lambda:True)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.image) for e in dialog.descendants())
        assert any(isinstance(e,ui.label) and e.text==render_message_plain('components.staged.preview_hint') for e in dialog.descendants())
        buttons=[e for e in dialog.descendants() if isinstance(e,ui.button)]
        assert not any(e._props.get('icon') in {'print','download'} for e in buttons)
        # Order is PDF then image, while the clicked image remains selected.
        image_button=next(e for e in buttons if e.text=='2')
        assert image_button._props['aria-pressed']=='true'
        chosen=next(e for e in buttons if e.text=='1')
        await click(chosen)
        assert any(e.tag=='iframe' for e in dialog.descendants()),(api.calls,[(e.tag,getattr(e,'text','')) for e in dialog.descendants()])
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e._props.get('icon')=='close'))
        assert not dialog.value
    assert api.calls==[(17,1),(17,2)]


@pytest.mark.asyncio
async def test_preview_errors_keep_switcher_and_do_not_change_staged_metadata(host,monkeypatch):
    patch_js(monkeypatch);api=Api();api.fail=True;rows=[component(),component(2,mime='application/pdf')]
    with host:
        await viewer(api)(None,1,draft_id=17,staged_components=rows)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text=='Preview unavailable' for e in dialog.descendants())
        api.fail=False
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text=='2'))
        assert any(e.tag=='iframe' for e in dialog.descendants()),(api.calls,[(e.tag,getattr(e,'text','')) for e in dialog.descendants()])
    assert all(r['content_status']=='staged' for r in rows) and api.calls==[(17,1),(17,2)]


@pytest.mark.asyncio
@pytest.mark.parametrize('close_source',[False,True])
async def test_abandoned_staged_preview_cannot_render_late_bytes(host,monkeypatch,close_source):
    patch_js(monkeypatch);entered=asyncio.Event();finish=asyncio.Event();active=[True]
    class Slow(Api):
        async def view_draft_component(self,*args):entered.set();await finish.wait();return PNG
    with host:
        async def open_view():
            with host:await viewer(Slow())(None,1,draft_id=17,staged_components=[component()],source_active=lambda:active[0])
        task=asyncio.create_task(open_view())
        await entered.wait();dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        if close_source:active[0]=False
        else:await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e._props.get('icon')=='close'))
        finish.set();await task
        assert not any(isinstance(e,ui.image) for e in dialog.descendants())


@pytest.mark.asyncio
async def test_staged_switcher_limits_rendered_metadata_and_requests_only_selected_bytes(host,monkeypatch):
    patch_js(monkeypatch);api=Api();rows=[component(i,mime='application/pdf') for i in range(1,122)]
    with host:
        await viewer(api)(None,121,draft_id=17,staged_components=rows)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        numbered=[e for e in dialog.descendants() if isinstance(e,ui.button) and e.text.isdigit()]
        assert len(numbered)==21 and api.calls==[(17,121)]
        back=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e._props.get('aria-label')==render_message_plain('webui.render_entity_compact_results.accessible_name.previous_page_2ba84275'))
        await click(back)
        assert len([e for e in dialog.descendants() if isinstance(e,ui.button) and e.text.isdigit()])==50
        assert api.calls[-1]==(17,51)


@pytest.mark.asyncio
async def test_api_client_staged_preview_is_a_read_only_binary_get(monkeypatch):
    calls=[]
    async def request(self,*a,**kw):calls.append((a,kw));return PDF
    monkeypatch.setattr(ErmsApiClient,'request',request)
    client=object.__new__(ErmsApiClient)
    assert await client.view_draft_component(17,3)==PDF
    assert calls==[(('GET','/api/v1/record-drafts/17/components/3/rendition'),{})]


@pytest.mark.asyncio
@pytest.mark.parametrize('download,printing',[(False,False),(True,True)])
async def test_saved_viewer_keeps_its_original_capability_controls_and_content_route(host,monkeypatch,download,printing):
    patch_js(monkeypatch)
    class Saved(Api):
        async def resource_capabilities(self,resource,identity):return dict(list_components=True,view_component=True,download_component=download,print_component=printing)
        async def previewable_component_page(self,identity,**params):
            self.calls.append(('page',identity,params))
            return {'items':[component(status='available')],'total':1,'offset':0}
        async def view_component_pdf(self,identity):self.calls.append(('saved',identity));return PNG
    api=Saved()
    with host:
        await viewer(api)({'id':99})
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        icons=[e._props.get('icon') for e in dialog.descendants() if isinstance(e,ui.button)]
        assert ('download' in icons)==download and ('print' in icons)==printing
        assert not any(isinstance(e,ui.label) and e.text==render_message_plain('components.staged.preview_hint') for e in dialog.descendants())
    assert api.calls==[('page',99,{'limit':50,'selected_component_id':None}),('saved',1)]

@pytest.mark.asyncio
@pytest.mark.parametrize('denied,failed',[(True,False),(False,True)])
async def test_saved_preview_denial_and_initial_failure_create_no_viewer(host,monkeypatch,denied,failed):
    patch_js(monkeypatch)
    class Saved(Api):
        async def resource_capabilities(self,*args):
            if failed:raise ApiError(403,'Forbidden')
            return {'list_components':True,'view_component':not denied}
        async def previewable_component_page(self,*args,**kwargs):
            pytest.fail('A denied viewer must not request component metadata')
    with host:
        await viewer(Saved())({'id':99})
        assert not any(isinstance(e,ui.dialog) and e.value for e in host.descendants())

@pytest.mark.asyncio
async def test_saved_print_and_download_keep_binary_routes_and_mime(host,monkeypatch):
    from unittest.mock import Mock
    scripts=patch_js(monkeypatch);download=Mock();monkeypatch.setattr(ui,'download',download)
    class Saved(Api):
        async def resource_capabilities(self,*args):return dict(list_components=True,view_component=True,download_component=True,print_component=True)
        async def previewable_component_page(self,*args,**kwargs):return {'items':[component(status='available',name='image.png')],'total':1,'offset':0}
        async def view_component_pdf(self,identity):return PNG
        async def print_component_pdf(self,identity):self.calls.append(('print',identity));return PNG
        async def download_component(self,identity):self.calls.append(('download',identity));return PNG
    api=Saved()
    with host:
        await viewer(api)({'id':99})
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        for icon in ('print','download'):
            await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.props.get('icon')==icon))
    assert api.calls==[('print',1),('download',1)]
    download.assert_called_once_with(PNG,'image.png','image/png')
    assert any('ermsPdfViewer.print(' in script and 'image/png' in script for script in scripts)


@pytest.mark.asyncio
async def test_original_pdf_stays_selected_and_cannot_reopen_while_first_page_loads(host, monkeypatch):
    patch_js(monkeypatch)
    fetching = asyncio.Event()
    painted = asyncio.Event()
    scripts = []

    def run(self, script, **kwargs):
        if "ermsPdfViewer.open(" in script:
            scripts.append(script)
            fetching.set()
            return painted.wait()
        return JSResult()

    monkeypatch.setattr(Client, "run_javascript", run)
    api = Api()
    async def open_preview():
        with host:
            await viewer(api)(None, 1, draft_id=17, staged_components=[
                component(1, mime="application/pdf"), component(2),
            ])

    with host:
        pending = asyncio.create_task(open_preview())
        try:
            await asyncio.wait_for(fetching.wait(), 2)
            selected = next(e for e in host.descendants() if isinstance(e, ui.button) and e.text == "1")
            assert not selected.enabled
            await click(selected)
            assert api.calls == [(17, 1)]
            assert len(scripts) == 1 and '"/preview-pdf/drafts/17/1/fixture"' in scripts[0]
        finally:
            painted.set()
            await pending
        assert next(e for e in host.descendants() if isinstance(e, ui.button) and e.text == "1").enabled


@pytest.mark.asyncio
async def test_abandoning_conversion_releases_late_open_without_mounting_reader(host, monkeypatch):
    scripts = patch_js(monkeypatch)
    entered, finish = asyncio.Event(), asyncio.Event()
    url = '/preview-pdf/converted/drafts/17/1/checksum/receipt'
    released = []

    class SlowConversion(Api):
        async def update_viewer_renditions(self, ids, *, release):
            if release:
                released.extend(ids)

        async def open_converted_pdf(self, component_id, draft_id=None, *, rendition_id, reuse=False):
            self.receipt = rendition_id
            entered.set()
            await finish.wait()
            return url

    with host:
        async def open_viewer():
            with host:
                await viewer(SlowConversion())(None, 1, draft_id=17, staged_components=[
                    component(1, mime='application/octet-stream', name='letter.docx'),
                ])
        pending = asyncio.create_task(open_viewer())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            close = next(element for element in host.descendants()
                         if isinstance(element, ui.button) and element._props.get('icon') == 'close')
            await click(close)
        finally:
            finish.set()
            await pending
    assert len(released) == 2 and released[0] == released[1]  # Close, then late publication.
    assert not any('ermsPdfViewer.open(' in script for script in scripts)


@pytest.mark.asyncio
async def test_draft_viewer_retains_and_renews_hidden_renditions(host, monkeypatch):
    patch_js(monkeypatch)
    opens, updates = [], []

    class DraftApi(Api):
        async def open_converted_pdf(self, component_id, draft_id, *, rendition_id, reuse=False):
            opens.append((component_id, rendition_id, reuse))
            return f'/preview-pdf/converted/drafts/{draft_id}/{component_id}/checksum/{rendition_id}'

        async def update_viewer_renditions(self, ids, *, release):
            updates.append((list(ids), release))

    with host:
        await viewer(DraftApi())(None, 1, draft_id=17, staged_components=[
            component(i, mime='application/octet-stream', name=f'File {i}.docx') for i in [1, 2]
        ])
        dialog = next(e for e in host.descendants() if isinstance(e, ui.dialog) and e.value)
        for button_text in ('2', '1'):
            await click(next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == button_text))
        first_id, second_id = opens[0][1], opens[1][1]
        assert first_id != second_id
        assert opens == [(1, first_id, False), (2, second_id, False), (1, first_id, True)]
        assert updates == []
        timer = next(e for e in dialog.descendants() if isinstance(e, ui.timer))
        monkeypatch.setattr(Client, 'has_socket_connection', property(lambda _: True))
        assert timer.interval == 120
        await timer.callback()
        assert updates == [([first_id, second_id], False)]
        await click(next(e for e in dialog.descendants() if isinstance(e, ui.button) and e._props.get('icon') == 'close'))
        assert updates[-1] == ([first_id, second_id], True)


@pytest.mark.asyncio
async def test_return_during_conversion_waits_and_replaces_an_invalidated_handle(host, monkeypatch):
    patch_js(monkeypatch)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls, released = [], []

    class SlowApi(Api):
        async def open_converted_pdf(self, component_id, draft_id, *, rendition_id, reuse=False):
            calls.append((rendition_id, reuse))
            if len(calls) == 1:
                entered.set()
                await finish.wait()
            if reuse and len(calls) == 3:
                raise ApiError(412, 'source replaced')
            return f'/preview-pdf/converted/drafts/{draft_id}/{component_id}/checksum/{rendition_id}'

        async def update_viewer_renditions(self, ids, *, release):
            if release:
                released.extend(ids)

    with host:
        async def start():
            with host:
                await viewer(SlowApi())(None, 1, draft_id=17, staged_components=[
                    component(1, mime='text/plain', name='file.txt'), component(2),
                ])

        first = asyncio.create_task(start())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            dialog = next(e for e in host.descendants() if isinstance(e, ui.dialog) and e.value)

            def switch(text):
                return click(next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == text))

            await switch('2')
            returning = asyncio.create_task(switch('1'))
            await asyncio.sleep(0)
        finally:
            finish.set()
            await first
        await returning
        old = calls[0][0]
        assert calls == [(old, False), (old, True)]
        assert released == []
        await switch('2')
        await switch('1')
        new = calls[-1][0]
        assert new != old and calls[-2:] == [(old, True), (new, False)]
        assert released == [old]
        await click(next(e for e in dialog.descendants() if isinstance(e, ui.button) and e._props.get('icon') == 'close'))
        assert released == [old, new]
