"""Execute original committed UI files against the same disposable current API."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root));from tools import run_webui_integration as runner
snapshot=(root/'.runtime/webui-refactor-phase7/original-ui/frontend/webui').resolve()
output=root/sys.argv[sys.argv.index('--output')+1];launch=subprocess.Popen

def with_original(command,*args,**kwargs):
 marker="runpy.run_module('frontend.webui.app',run_name='__main__')"
 if isinstance(command,list) and command[-1].endswith(marker):
  command=list(command);command[-1]=f"import frontend.webui; frontend.webui.__path__=[{str(snapshot)!r}]; "+command[-1]
  check=f"import sys; assert all(not n.startswith('frontend.webui.') or not getattr(m,'__file__',None) or m.__file__.startswith({str(snapshot)!r}) for n,m in sys.modules.items()); "
  command[-1]=command[-1].replace(marker,check+marker)
  (output/'original-overlay.json').write_text(json.dumps({'commit':'8106e1e','package_path':str(snapshot.relative_to(root)),'manifest':'.runtime/webui-refactor-phase7/original-ui-manifest.json','method':'Only the test WebUI subprocess imports the immutable original package. API, schema, drivers and dependencies are identical to the refactored run.'},indent=2)+'\n')
 return launch(command,*args,**kwargs)
runner.subprocess.Popen=with_original
raise SystemExit(runner.main())
