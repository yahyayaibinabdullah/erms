"""API-owned rendition scratch, registered before use and acked after deletion."""
from pathlib import Path
import tempfile,hashlib
from psycopg.conninfo import conninfo_to_dict
from ..processing_workspace import recover
from .database import pool,database_url

def root():
    config=conninfo_to_dict(database_url())
    identity='|'.join(config.get(k,'') for k in ('host','port','dbname'))
    return Path(tempfile.gettempdir())/'wathiq-api-renditions'/hashlib.sha256(identity.encode()).hexdigest()


def acknowledge(metadata):
    with pool.connection() as c:c.execute("DELETE FROM disposition_private.processing_copies WHERE token=%s AND kind='rendition'",(metadata['token'],))


def recover_renditions():return recover(root(),acknowledge)


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


def protect_response(function):
    from functools import wraps
    from ..processing_workspace import _FDS
    from starlette.concurrency import run_in_threadpool
    @wraps(function)
    def guarded(component,request,connection):
        handle=ResponseCopy(component['id'],connection.execute('SELECT current_user_id() id').fetchone()['id'],connection)
        state=_FDS.set((*_FDS.get(),handle.lock.fileno()))
        try:
            response=function(component,request,connection,_temporary_root=handle.directory)
            previous=response.background
            async def after():
                try:
                    if previous:await previous()
                finally:await run_in_threadpool(handle.close)
            response.background=after
            return response
        except Exception:
            handle.close();raise
        finally:_FDS.reset(state)
    return guarded
