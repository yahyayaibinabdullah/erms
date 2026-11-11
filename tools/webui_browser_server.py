"""Disposable browser-test instrumentation; never imported by production startup.

Records API request metadata, and supports explicitly controlled read failures
and delays. No headers, cookies, request bodies or response bodies are logged.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from tools.webui_test_events import EventWriter

class ObservedAPI:
    def __init__(self, app, directory):
        self.app, self.directory = app, Path(directory)
        self.started_events = EventWriter(self.directory / 'requests-started.jsonl')
        self.finished_events = EventWriter(self.directory / 'requests.jsonl')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            try:
                return await self.app(scope, receive, send)
            finally:
                self.started_events.close()
                self.finished_events.close()
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status = None
        control = self.directory / 'control.json'
        instruction = json.loads(control.read_text()) if control.exists() else {}
        matched = instruction.get('path') == scope['path'] and instruction.get('method', 'GET') == scope['method']
        entry = dict(method=scope['method'], path=scope['path'], query=scope['query_string'].decode(),
                     controlled=matched)
        self.started_events.append(entry)

        async def observed(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            if matched:
                if instruction.get('hold'):
                    deadline = time.monotonic() + 30
                    while control.exists() and json.loads(control.read_text()) == instruction:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Disposable test did not release its held response')
                        await asyncio.sleep(.05)
                await asyncio.sleep(instruction.get('delay', 0))
                if instruction.get('status'):
                    status = instruction['status']
                    body = json.dumps({'detail': 'Controlled disposable test failure'}).encode()
                    await observed({'type': 'http.response.start', 'status': status,
                                    'headers': [(b'content-type', b'application/json')]})
                    await observed({'type': 'http.response.body', 'body': body})
                    return
            await self.app(scope, receive, observed)
        finally:
            entry.update(status=status, milliseconds=round(1000*(time.monotonic()-started),2))
            self.finished_events.append(entry)


ERROR_CAPTURE = b'''<script>
window.__webuiTestErrors=[];
window.__webuiTestClicks=[];
document.addEventListener('click',e=>{const target=e.target.closest('button,input,[role=option]') || e.target;
window.__webuiTestClicks.push({id:target.id,tag:target.tagName});},true);
const recordWebuiError=(kind,message)=>window.__webuiTestErrors.push({kind,message:String(message)});
window.addEventListener('error',e=>window.__webuiTestErrors.push({kind:'error',
message:String(e.message || 'Resource/event error'),filename:e.filename || null,
target:e.target && e.target.tagName || null,
resource:e.target && (e.target.src || e.target.href) || null,
eventType:e.constructor.name}),true);
window.addEventListener('unhandledrejection',e=>recordWebuiError('unhandledrejection',e.reason));
for(const kind of ['warn','error']){const original=console[kind];console[kind]=(...args)=>{
recordWebuiError(kind,args.join(' '));return original.apply(console,args);};}
</script>'''


class BrowserDiagnostics:
    """Install error observation before page scripts, without changing UI/CSS."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        start = None
        body = bytearray()

        async def observed(message):
            nonlocal start
            if message['type'] == 'http.response.start':
                headers = dict(message.get('headers', []))
                if b'text/html' in headers.get(b'content-type', b'') and b'content-encoding' not in headers:
                    start = message
                    return
            if start is not None and message['type'] == 'http.response.body':
                body.extend(message.get('body', b''))
                if not message.get('more_body', False):
                    modified = bytes(body).replace(b'<head>', b'<head>'+ERROR_CAPTURE, 1)
                    start['headers'] = [(k,v) for k,v in start['headers'] if k != b'content-length']
                    start['headers'].append((b'content-length', str(len(modified)).encode()))
                    await send(start)
                    await send({'type':'http.response.body', 'body':modified})
                return
            await send(message)
        await self.app(scope, receive, observed)


def install_client_diagnostics(directory):
    """Read-only lifecycle metadata for disposable UI requests; never log payloads/tokens."""
    import functools
    import traceback
    from frontend.webui.api_client import ErmsApiClient

    events = EventWriter(Path(directory) / 'ui-client-events.jsonl')
    request = ErmsApiClient.request
    cancel = ErmsApiClient.cancel_pending_reads
    close = ErmsApiClient.close

    def record(client, event, **fields):
        row = dict(client=id(client), event=event, monotonic=time.monotonic(), **fields)
        events.append(row)

    @functools.wraps(request)
    async def observed_request(client, method, path, **kwargs):
        record(client, 'request-start', method=method, path=path)
        try:
            result = await request(client, method, path, **kwargs)
        except BaseException as error:
            record(client, 'request-error', method=method, path=path, error_type=type(error).__name__)
            raise
        record(client, 'request-finish', method=method, path=path)
        return result

    @functools.wraps(cancel)
    def observed_cancel(client):
        record(client, 'cancel-reads', pending=sum(not t.done() for t in client._inflight_reads.values()),
               callers=[f.name for f in traceback.extract_stack(limit=9)[:-1]])
        return cancel(client)

    @functools.wraps(close)
    async def observed_close(client):
        record(client, 'close')
        return await close(client)

    ErmsApiClient.request = observed_request
    ErmsApiClient.cancel_pending_reads = observed_cancel
    ErmsApiClient.close = observed_close


def main():
    from psycopg.conninfo import conninfo_to_dict
    parser = argparse.ArgumentParser()
    parser.add_argument('--fd', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not conninfo_to_dict(os.environ['DATABASE_URL'])['dbname'].startswith('erms_webui_test_'):
        raise RuntimeError('Browser instrumentation requires the disposable test runner')
    import uvicorn
    from backend.services.api.main import app
    uvicorn.run(ObservedAPI(app,args.output), fd=args.fd)


if __name__ == '__main__':
    main()
