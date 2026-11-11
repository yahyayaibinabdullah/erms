"""Original/current UI with identical pinned Edge driver; no Git mutation."""
import json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root));from tools import run_webui_integration as runner
index=sys.argv.index('--variant');variant=sys.argv[index+1];del sys.argv[index:index+2];assert variant in ('original','current')
r=root/'.runtime/webui-refactor-phase7';output=root/sys.argv[sys.argv.index('--output')+1];launch=subprocess.Popen;snapshot=str(r/'original-ui/frontend/webui')
def observed(command,*args,**kwargs):
    if isinstance(command,list):
        command=list(command);marker="runpy.run_module('frontend.webui.app',run_name='__main__')"
        if variant=='original' and command[-1].endswith(marker):
            command[-1]=f"import frontend.webui; frontend.webui.__path__=[{snapshot!r}]; "+command[-1]
            (output/'original-overlay.json').write_text(json.dumps({'commit':'8106e1e','package_path':snapshot,'method':'Original complete package; same API/schema/dependencies/driver/test harness.'},indent=2)+'\n')
        elif len(command)>1 and command[1]=='tools/check_webui_browser.py':command[1]=str(r/'pinned-edge-browser.py')
    return launch(command,*args,**kwargs)
runner.subprocess.Popen=observed
raise SystemExit(runner.main())
