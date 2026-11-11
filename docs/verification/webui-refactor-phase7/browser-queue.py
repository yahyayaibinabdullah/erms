"""Run each approved native journey in its own disposable database/session."""
import json,subprocess,sys,time
from pathlib import Path
root=Path.cwd();browser=sys.argv[1];r=root/'.runtime/webui-refactor-phase7'
# The current all-destination test owns this browser's first test session.
while True:
 p=r/('application-'+browser+'-v2')/'lifecycle.json'
 if p.exists() and json.loads(p.read_text()).get('database_dropped'):break
 time.sleep(1)
results=[]
for scope in ('full','session','keyboard','governance-custody','dashboard','records','aggregations','components'):
 output=r/(scope+'-'+browser)
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call([str(root/'backend/services/api/.venv/bin/python'),str(root/'tools/run_webui_integration.py'),'--browser',browser,'--browser-scope',scope,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 results.append({'scope':scope,'exit_code':code,'output':str(output.relative_to(root))})
 (r/(browser+'-queue.json')).write_text(json.dumps(results,indent=2)+'\n')
 print(browser,scope,'exit',code,flush=True)
 # A failure retains its evidence; independent journeys can still be checked.
