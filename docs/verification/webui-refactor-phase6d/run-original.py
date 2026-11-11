"""Run the captured pre-6D host without replacing files in the working tree."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
from tools import run_webui_integration as runner
snapshot=root/'.runtime/webui-refactor-phase6d/app-before.py'
original=root/'frontend/webui/app.py'
output=root/sys.argv[sys.argv.index('--output')+1]
launch=subprocess.Popen

def with_original_host(command,*args,**kwargs):
    marker="runpy.run_module('frontend.webui.app',run_name='__main__')"
    if isinstance(command,list) and command[-1].endswith(marker):
        command=list(command)
        command[-1]=command[-1].replace(marker,
            f"exec(compile(open({str(snapshot)!r}).read(), {str(original)!r}, 'exec'), "
            f"{{'__file__':{str(original)!r},'__name__':'__main__','__package__':'frontend.webui'}})")
        (output/'baseline-overlay.json').write_text(json.dumps({
            'effective_host':str(snapshot.relative_to(root)),
            'sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            'note':'Pre-6D host snapshot compiled with original package/file identity. Working tree unchanged. Source-environment.json describes on-disk files; this overlay replaces only the effective app.py.'
        },indent=2)+'\n')
    if isinstance(command,list) and command[1:3] == ['-m','pytest']:
        pytest_args=command[3:]
        code=("import sys,types; import frontend.webui; "
            "m=types.ModuleType('frontend.webui.app'); "
            f"m.__file__={str(original)!r}; m.__package__='frontend.webui'; "
            "sys.modules['frontend.webui.app']=m; frontend.webui.app=m; "
            f"exec(compile(open({str(snapshot)!r}).read(), {str(original)!r}, 'exec'),m.__dict__); "
            f"import pytest; raise SystemExit(pytest.main({pytest_args!r}))")
        command=[command[0],'-c',code]
        (output/'baseline-overlay.json').write_text(json.dumps({
            'effective_host':str(snapshot.relative_to(root)),
            'sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            'note':'Pre-6D host snapshot loaded as frontend.webui.app before assembled tests; working files unchanged.'
        },indent=2)+'\n')
    return launch(command,*args,**kwargs)
runner.subprocess.Popen=with_original_host
raise SystemExit(runner.main())
