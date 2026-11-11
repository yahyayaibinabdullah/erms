import json,subprocess,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');q=r/'performance-edge-retry-result.json'
while not q.exists():time.sleep(1)
for p in r.glob('*/lifecycle.json'):assert json.loads(p.read_text()).get('database_dropped'),p
results=[]
for variant in ('original','current'):
 output=r/('diagnostic-chrome-'+variant)
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-diagnostic-ui.py'),'--variant',variant,'--browser','chrome','--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 results.append({'variant':variant,'exit_code':code,'output':str(output)});(r/'diagnostic-queue.json').write_text(json.dumps(results,indent=2)+'\n');print(variant,code,flush=True)
 if code:raise SystemExit(code)
