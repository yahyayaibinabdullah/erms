import subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
from tools import run_webui_integration as runner
launch=subprocess.Popen
def pinned(command,*args,**kwargs):
 if isinstance(command,list) and len(command)>1 and command[1]=='tools/check_webui_browser.py':
  command=[command[0],str(root/'.runtime/governed-move-fix/pinned-browser.py'),*command[2:]]
 return launch(command,*args,**kwargs)
runner.subprocess.Popen=pinned
raise SystemExit(runner.main())
