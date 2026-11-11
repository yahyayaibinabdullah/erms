"""Test-only instrumentation must not change ordinary responses or leak bodies."""
import asyncio
import json

from tools.webui_browser_server import BrowserDiagnostics, ObservedAPI, ERROR_CAPTURE


def exchange(application, scope):
    sent=[]
    async def receive():return {'type':'http.request','body':b''}
    async def send(message):sent.append(message)
    asyncio.run(application(scope,receive,send))
    return sent


def test_ordinary_api_response_is_preserved_and_sensitive_payload_is_not_logged(tmp_path):
    async def app(scope,receive,send):
        await send({'type':'http.response.start','status':201,'headers':[(b'content-type',b'application/json')]})
        await send({'type':'http.response.body','body':b'{"private":"fixture-token"}'})
    messages=exchange(ObservedAPI(app,tmp_path),{'type':'http','method':'POST','path':'/test','query_string':b'limit=25',
        'headers':[(b'authorization',b'fixture-credential')]})
    assert messages[-1]['body']==b'{"private":"fixture-token"}'
    event=json.loads((tmp_path/'requests.jsonl').read_text())
    assert event['status']==201 and event['query']=='limit=25'
    for path in tmp_path.iterdir():
        assert 'fixture-token' not in path.read_text() and 'fixture-credential' not in path.read_text()


def test_controlled_email_failure_never_calls_the_real_sender(tmp_path):
    (tmp_path/'control.json').write_text(json.dumps({'method':'POST','path':'/api/v1/application-settings/test-send','status':503}))
    async def forbidden(*args):raise AssertionError('Must not reach the real email sender')
    messages=exchange(ObservedAPI(forbidden,tmp_path),{'type':'http','method':'POST','path':'/api/v1/application-settings/test-send','query_string':b''})
    assert messages[0]['status']==503
    assert json.loads((tmp_path/'requests.jsonl').read_text())['controlled']


def test_diagnostics_precede_page_scripts_and_preserve_html_content():
    original=b'<html><head><script>page()</script></head><body>Existing UI</body></html>'
    async def app(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'text/html'),(b'content-length',str(len(original)).encode())]})
        await send({'type':'http.response.body','body':original[:20],'more_body':True})
        await send({'type':'http.response.body','body':original[20:]})
    messages=exchange(BrowserDiagnostics(app),{'type':'http'})
    body=messages[-1]['body']
    assert body.replace(ERROR_CAPTURE,b'')==original
    assert body.index(ERROR_CAPTURE)<body.index(b'page()')
    assert int(dict(messages[0]['headers'])[b'content-length'])==len(body)


def test_held_response_is_released_explicitly_before_reaching_the_api(tmp_path):
    control=tmp_path/'control.json'
    control.write_text(json.dumps({'path':'/settings','hold':True}))
    reached=[]
    async def app(scope,receive,send):
        assert json.loads(control.read_text())=={}
        reached.append(True)
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'ok'})
    async def run():
        async def receive():return {'type':'http.request','body':b''}
        async def send(message):pass
        task=asyncio.create_task(ObservedAPI(app,tmp_path)(
            {'type':'http','method':'GET','path':'/settings','query_string':b''},receive,send))
        await asyncio.sleep(.1)
        assert not reached and not task.done()
        control.write_text('{}')
        await asyncio.wait_for(task,1)
    asyncio.run(run())
    assert reached==[True]


def test_client_diagnostics_preserve_results_and_never_log_credentials_or_payloads(tmp_path, monkeypatch):
    import httpx
    from frontend.webui.api_client import ErmsApiClient
    from tools.webui_browser_server import install_client_diagnostics
    for name in ('request', 'cancel_pending_reads', 'close'):
        monkeypatch.setattr(ErmsApiClient, name, getattr(ErmsApiClient, name))
    install_client_diagnostics(tmp_path)

    async def handler(request):
        return httpx.Response(200, json={'private': 'sensitive-response-fixture'})
    async def run():
        client = ErmsApiClient('http://fixture', transport=httpx.MockTransport(handler))
        client.set_session_token('sensitive-token-fixture')
        try:
            return await client.request('POST', '/fixture', json={'secret': 'sensitive-body-fixture'})
        finally:
            await client.close()
    assert asyncio.run(run()) == {'private': 'sensitive-response-fixture'}
    raw = (tmp_path / 'ui-client-events.jsonl').read_text()
    assert 'sensitive-' not in raw
    events = list(map(json.loads, raw.splitlines()))
    assert [e['event'] for e in events] == ['cancel-reads', 'request-start', 'request-finish', 'close']


def test_client_diagnostics_preserve_read_cancellation(tmp_path, monkeypatch):
    import httpx
    import pytest
    from frontend.webui.api_client import ErmsApiClient
    from tools.webui_browser_server import install_client_diagnostics
    for name in ('request', 'cancel_pending_reads', 'close'):
        monkeypatch.setattr(ErmsApiClient, name, getattr(ErmsApiClient, name))
    install_client_diagnostics(tmp_path)

    async def run():
        started = asyncio.Event()
        async def handler(request):
            started.set()
            await asyncio.Event().wait()
        client = ErmsApiClient('http://fixture', transport=httpx.MockTransport(handler))
        task = asyncio.create_task(client.request('GET', '/fixture'))
        await started.wait()
        client.cancel_pending_reads()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.close()
    asyncio.run(run())
    events = list(map(json.loads, (tmp_path / 'ui-client-events.jsonl').read_text().splitlines()))
    assert any(e['event'] == 'cancel-reads' and e['pending'] == 1 for e in events)
    assert any(e['event'] == 'request-error' and e['error_type'] == 'CancelledError' for e in events)


def test_api_request_logging_reuses_handles_and_closes_on_shutdown(tmp_path, monkeypatch):
    from pathlib import Path
    async def app(scope,receive,send):
        if scope['type']=='http':
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
    observed=ObservedAPI(app,tmp_path)
    original=Path.open
    def no_reopening(self,*args,**kwargs):
        if self.parent==tmp_path and args and args[0]=='a':
            raise AssertionError('Request logging reopened an existing stream')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_reopening)
    for _ in range(3):
        exchange(observed,{'type':'http','method':'GET','path':'/test','query_string':b''})
    assert len((tmp_path/'requests-started.jsonl').read_text().splitlines())==3
    assert len((tmp_path/'requests.jsonl').read_text().splitlines())==3
    exchange(observed,{'type':'lifespan'})
    assert observed.started_events.file.closed and observed.finished_events.file.closed
