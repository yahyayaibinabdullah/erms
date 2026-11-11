"""Identical original/current diagnostic wrappers; owned runner retains cleanup."""
import json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root));from tools import run_webui_integration as runner
index=sys.argv.index('--variant');variant=sys.argv[index+1];del sys.argv[index:index+2];assert variant in ('original','current')
r=root/'.runtime/webui-refactor-phase7';output=root/sys.argv[sys.argv.index('--output')+1];launch=subprocess.Popen
hooks=str(r/'diagnostic-hooks.py');snapshot=str(r/'original-ui/frontend/webui')

def observed(command,*args,**kwargs):
    if isinstance(command,list):
        command=list(command);marker="runpy.run_module('frontend.webui.app',run_name='__main__')"
        install=lambda role:f"exec(compile(open({hooks!r}).read(),{hooks!r},'exec')); install({str(output)!r},{role!r}); "
        if command[-1].endswith(marker):
            prefix=(f"import frontend.webui; frontend.webui.__path__=[{snapshot!r}]; " if variant=='original' else '')
            command[-1]=prefix+install('ui')+command[-1].replace(marker,f'install_request_errors({str(output)!r}); '+marker)
        elif len(command)>2 and command[1:3]==['-m','tools.webui_browser_server']:
            command=[command[0],'-c',install('api')+'from tools.webui_browser_server import main; main()',*command[3:]]
        elif len(command)>1 and command[1]=='tools/check_webui_browser.py':
            command[1]=str(r/'diagnostic-browser.py')
            (output/'diagnostic-method.json').write_text(json.dumps({'variant':variant,'source_commit':'8106e1e' if variant=='original' else '123ad8b','instrumentation':'100ms read-only API/UI process stacks, GC durations over 20ms, WebDriver commands over 50ms; no frame locals or command parameters.','acceptance_use':'Diagnostic runs are supplementary; do not silently replace the original paired measurements.'},indent=2)+'\n')
    return launch(command,*args,**kwargs)
runner.subprocess.Popen=observed
raise SystemExit(runner.main())
