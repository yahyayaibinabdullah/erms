import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7')
for p in r.glob('*/lifecycle.json'):assert json.loads(p.read_text()).get('database_dropped'),p
results=json.loads((r/'performance-clean-runs.json').read_text())[:4]
assert all(x['browser']=='chrome' and x['exit_code']==0 for x in results)
for number,variant in enumerate(('original','current','current','original'),1):
 output=r/f'performance-pinned-edge-{number}-{variant}'
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-pinned-performance.py'),'--variant',variant,'--browser','edge','--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 results.append({'browser':'edge','sequence':number,'variant':variant,'exit_code':code,'output':str(output)})
 (r/'performance-accepted-runs.json').write_text(json.dumps(results,indent=2)+'\n');print(number,variant,code,flush=True)
 if code:raise SystemExit(code)
