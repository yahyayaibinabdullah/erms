import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');attempts=json.loads((r/'performance-clean-runs.json').read_text())
assert len(attempts)==6 and attempts[-1]['exit_code']!=0
for p in r.glob('*/lifecycle.json'):assert json.loads(p.read_text()).get('database_dropped'),p
results=attempts[:5]
for number,variant in ((2,'current'),(3,'current'),(4,'original')):
 output=r/(f'performance-clean-edge-{number}-{variant}'+('-retry' if number==2 else ''))
 runner=str(r/'run-original-ui.py') if variant=='original' else 'tools/run_webui_integration.py'
 with output.with_suffix('.log').open('w') as log:
  code=subprocess.call(['backend/services/api/.venv/bin/python',runner,'--browser','edge','--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
 row={'browser':'edge','sequence':number,'variant':variant,'exit_code':code,'output':str(output)}
 if number==2:row['replaces_incomplete_run']=attempts[-1]['output']
 results.append(row);(r/'performance-clean-final-runs.json').write_text(json.dumps(results,indent=2)+'\n');print(number,variant,code,flush=True)
 if code:raise SystemExit(code)
