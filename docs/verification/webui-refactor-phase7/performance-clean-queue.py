"""Repeat the full identical ABBA protocol after removing measured log I/O stalls."""
import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7')
assert (r/'io-probe.json').exists()
assert all(x['exit_code']==0 for x in json.loads((r/'diagnostic-queue.json').read_text()))
for p in r.glob('*/lifecycle.json'):assert json.loads(p.read_text()).get('database_dropped'),p
results=[]
for browser in ('chrome','edge'):
 for number,variant in enumerate(('original','current','current','original'),1):
  output=r/f'performance-clean-{browser}-{number}-{variant}'
  runner=str(r/'run-original-ui.py') if variant=='original' else 'tools/run_webui_integration.py'
  with output.with_suffix('.log').open('w') as log:
   code=subprocess.call(['backend/services/api/.venv/bin/python',runner,'--browser',browser,'--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
  results.append({'browser':browser,'sequence':number,'variant':variant,'exit_code':code,'output':str(output)})
  (r/'performance-clean-runs.json').write_text(json.dumps(results,indent=2)+'\n');print(browser,number,variant,code,flush=True)
  if code:raise SystemExit(code)
