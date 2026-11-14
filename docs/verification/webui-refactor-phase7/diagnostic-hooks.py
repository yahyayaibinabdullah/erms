"""Read-only process samples and GC timings; never log frame locals or payloads."""
import gc,json,os,resource,sys,threading,time
from pathlib import Path


def install(directory, role):
    target=Path(directory)/(role+'-process-samples.jsonl')
    def emit(row):
        with target.open('a') as file:file.write(json.dumps(row)+'\n')
    starts={}
    def collected(phase, info):
        generation=info['generation']
        if phase=='start':starts[generation]=(time.monotonic(),time.process_time())
        elif generation in starts:
            begin,cpu=starts.pop(generation);elapsed=time.monotonic()-begin
            if elapsed>=.02:emit({'event':'gc','monotonic':begin,'milliseconds':elapsed*1000,'cpu_ms':(time.process_time()-cpu)*1000,**info})
    gc.callbacks.append(collected)
    main=threading.main_thread().ident
    def sample():
        while True:
            frame=sys._current_frames().get(main);stack=[]
            while frame is not None and len(stack)<12:
                stack.append({'function':frame.f_code.co_name,'file':frame.f_code.co_filename,'line':frame.f_lineno});frame=frame.f_back
            del frame
            emit({'event':'sample','monotonic':time.monotonic(),'cpu_seconds':time.process_time(),'max_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'main_stack':stack})
            time.sleep(.1)
    threading.Thread(target=sample,daemon=True).start()
    emit({'event':'installed','pid':os.getpid(),'role':role,'interval_seconds':.1,'gc_reporting_threshold_ms':20,'frame_locals_recorded':False})


def install_request_errors(directory):
    import functools
    from frontend.webui.api_client import ErmsApiClient
    original=ErmsApiClient.request
    @functools.wraps(original)
    async def observed(client,method,path,**kwargs):
        try:return await original(client,method,path,**kwargs)
        except BaseException as error:
            cause=error.__cause__
            row={'monotonic':time.monotonic(),'method':method,'path':path,
                 'error_type':type(error).__name__,'status_code':getattr(error,'status_code',None),
                 'cause_type':type(cause).__name__ if cause else None,
                 'cause_message':str(cause) if cause else None}
            with (Path(directory)/'request-error-details.jsonl').open('a') as file:file.write(json.dumps(row)+'\n')
            raise
    ErmsApiClient.request=observed
