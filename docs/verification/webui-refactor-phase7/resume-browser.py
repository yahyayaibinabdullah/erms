import json,subprocess,sys,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');b=sys.argv[1];q=r/(b+'-final-queue.json');expected=3 if b=='chrome' else 2
while not(q.exists() and len(json.loads(q.read_text()))==expected):time.sleep(1)
results=[]
for scope in ('full','keyboard','application','components'):
 output=r/(scope+'-'+b+'-resumed')
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call(['backend/services/api/.venv/bin/python','tools/run_webui_integration.py','--browser',b,'--browser-scope',scope,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 results.append({'scope':scope,'exit_code':code});(r/(b+'-resumed-queue.json')).write_text(json.dumps(results,indent=2)+'\n');print(b,scope,code,flush=True)
