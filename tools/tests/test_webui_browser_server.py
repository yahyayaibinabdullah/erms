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
