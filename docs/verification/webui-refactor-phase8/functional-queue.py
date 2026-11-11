import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');results=[]
for scope in ('full','session','application','keyboard','collections'):
 for browser in ('chrome','edge'):
  output=r/f'{scope}-{browser}'
  with output.with_suffix('.log').open('w') as log:
   code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-browser.py'),'--variant','current','--browser',browser,'--browser-scope',scope,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
  results.append({'browser':browser,'scope':scope,'exit_code':code,'output':str(output)})
  (r/'functional-runs.json').write_text(json.dumps(results,indent=2)+'\n');print(scope,browser,code,flush=True)
  if code:raise SystemExit(code)
