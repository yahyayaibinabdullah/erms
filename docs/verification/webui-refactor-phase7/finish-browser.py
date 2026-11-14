import json,subprocess,sys,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');browser=sys.argv[1];q=r/(browser+'-queue.json')
while not(q.exists() and len(json.loads(q.read_text()))==8):time.sleep(1)
results=[]
for scope in (['full'] if browser=='chrome' else [])+['keyboard','application']:
 output=r/(scope+'-'+browser+'-final')
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call(['backend/services/api/.venv/bin/python','tools/run_webui_integration.py','--browser',browser,'--browser-scope',scope,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 results.append({'scope':scope,'exit_code':code});(r/(browser+'-final-queue.json')).write_text(json.dumps(results,indent=2)+'\n');print(browser,scope,code,flush=True)
