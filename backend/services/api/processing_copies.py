"""API-owned rendition scratch, registered before use and acked after deletion."""
from contextlib import contextmanager
from pathlib import Path
from anyio import CancelScope
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
import tempfile,hashlib
from psycopg.conninfo import conninfo_to_dict
from ..processing_workspace import recover, workspace
from .database import pool,database_url

def root():
    config=conninfo_to_dict(database_url())
    identity='|'.join(config.get(k,'') for k in ('host','port','dbname'))
    return Path(tempfile.gettempdir())/'wathiq-api-renditions'/hashlib.sha256(identity.encode()).hexdigest()


def acknowledge(metadata):
    with pool.connection() as c:c.execute("DELETE FROM disposition_private.processing_copies WHERE token=%s AND kind='rendition'",(metadata['token'],))


def _draft_root():
    return root() / "draft-workspaces"


def _no_receipt(_metadata):
    # Staged uploads have no saved component or disposition processing-copy row.
    pass


@contextmanager
def draft_conversion_workspace():
    with workspace(_draft_root(), {}, _no_receipt, _no_receipt) as directory:
        yield directory


def recover_renditions():
    return recover(root(), acknowledge) + recover(_draft_root(), _no_receipt)


class ResponseCopy:
    """Fence buffered/converted previews until ASGI has finished sending them."""
    def __init__(self,component_id,user_id,connection):
        import json,os,fcntl
        from uuid import uuid4
        self.metadata={'token':str(uuid4())}
        self.directory=root()/('wathiq-processing-'+self.metadata['token'])
        self.directory.mkdir(mode=0o700,parents=True)
        (self.directory/'receipt.json').write_text(json.dumps(self.metadata));os.chmod(self.directory/'receipt.json',0o600)
        self.lock=(self.directory/'.lock').open('xb');fcntl.flock(self.lock,fcntl.LOCK_EX)
        try:
            # Authorization holds row locks on this connection. Registering on
            # another connection would wait for our own locks. Commit the fence
            # and authorization audit before reading any bytes, then restore the
            # request's transaction-local audit context for content-view events.
            keys=('user_id','actor_name','actor_email','actor_type','event_source','request_id','correlation_id','change_reason','event_metadata','content_indexing_scheduling_enabled')
            context={key:connection.execute('SELECT current_setting(%s,true) value',('app.'+key,)).fetchone()['value'] or '' for key in keys}
            connection.execute("SELECT disposition_private.register_processing_copy(%s,%s,%s,'rendition')",(self.metadata['token'],component_id,user_id))
            connection.commit()
            for key,value in context.items():connection.execute('SELECT set_config(%s,%s,true)',('app.'+key,value))
        except Exception:
            self.close();raise

    def close(self):
        from ..processing_workspace import cleanup_owned
        self.lock.close()
        if self.directory.exists():cleanup_owned(self.directory,self.metadata,acknowledge)


class _ProtectedResponse(Response):
    """Release the disposition fence even when the downstream send is cancelled."""
    def __init__(self, response, handle):
        self.response = response
        self.handle = handle
        self.status_code = response.status_code
        self.raw_headers = response.raw_headers
        self.background = None

    async def __call__(self, scope, receive, send):
        try:
            await self.response(scope, receive, send)
            if self.background:
                await self.background()
        finally:
            with CancelScope(shield=True):
                await run_in_threadpool(self.handle.close)


def protect_response(function):
    from functools import wraps
    from ..processing_workspace import _FDS
    @wraps(function)
    def guarded(component,request,connection):
        handle=ResponseCopy(component['id'],connection.execute('SELECT current_user_id() id').fetchone()['id'],connection)
        state=_FDS.set((*_FDS.get(),handle.lock.fileno()))
        try:
            response=function(component,request,connection,_temporary_root=handle.directory)
            return _ProtectedResponse(response, handle)
        except Exception:
            handle.close();raise
        finally:_FDS.reset(state)
    return guarded
