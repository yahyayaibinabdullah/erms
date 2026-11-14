"""Independent sequential original/current sessions, alternating order per browser."""
import json,subprocess,sys,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7')
for b in ('chrome','edge'):
 p=r/(b+'-resumed-queue.json')
 while not(p.exists() and len(json.loads(p.read_text()))==4):time.sleep(1)
 assert all(row['exit_code']==0 for row in json.loads(p.read_text())),p
# Refuse to overlap any database-backed functional run owned by this phase.
for p in r.glob('*/lifecycle.json'):
 assert json.loads(p.read_text()).get('database_dropped'),p
results=[]
# Two independent processes for each implementation/browser, with order reversed.
for b in ('chrome','edge'):
 for number,variant in enumerate(('original','current','current','original'),1):
  output=r/(f'performance-{b}-{number}-{variant}')
  runner=str(r/'run-original-ui.py') if variant=='original' else 'tools/run_webui_integration.py'
  with output.with_suffix('.log').open('w') as log:
   code=subprocess.call(['backend/services/api/.venv/bin/python',runner,'--browser',b,'--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
  results.append({'browser':b,'sequence':number,'variant':variant,'exit_code':code,'output':str(output)})
  (r/'performance-queue.json').write_text(json.dumps(results,indent=2)+'\n');print(b,number,variant,code,flush=True)
  if code:raise SystemExit(code)
