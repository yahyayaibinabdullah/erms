"""Own disposable browser/API/UI checks with a fixed driver and optional original UI."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root));from tools import run_webui_integration as runner
index=sys.argv.index('--variant');variant=sys.argv[index+1];del sys.argv[index:index+2];assert variant in ('original','current')
r=root/'.runtime/webui-refactor-phase8';output=root/sys.argv[sys.argv.index('--output')+1];launch=subprocess.Popen
snapshot=root/'.runtime/webui-refactor-phase7/original-ui'
manifest=json.loads((root/'.runtime/webui-refactor-phase7/original-ui-manifest.json').read_text())
if variant=='original':
 assert all(hashlib.sha256((snapshot/p).read_bytes()).hexdigest()==h for p,h in manifest['files'].items())
def observed(command,*args,**kwargs):
 if isinstance(command,list):
  command=list(command);marker="runpy.run_module('frontend.webui.app',run_name='__main__')"
  if variant=='original' and command[-1].endswith(marker):
   package=str(snapshot/'frontend/webui')
   command[-1]=f"import frontend.webui; frontend.webui.__path__=[{package!r}]; "+command[-1]
   check=f"import sys; assert all(not n.startswith('frontend.webui.') or not getattr(m,'__file__',None) or m.__file__.startswith({package!r}) for n,m in sys.modules.items()); "
   command[-1]=command[-1].replace(marker,check+marker)
   (output/'original-overlay.json').write_text(json.dumps({'commit':manifest['commit'],'package_path':package,'method':'Complete original package verified against retained SHA-256 manifest; same current API/schema/fixtures/dependencies/driver.'},indent=2)+'\n')
  elif len(command)>1 and command[1]=='tools/check_webui_browser.py':command[1]=str(r/'pinned-browser.py')
 return launch(command,*args,**kwargs)
runner.subprocess.Popen=observed
raise SystemExit(runner.main())
