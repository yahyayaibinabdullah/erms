"""Fresh original application traversal to investigate changed native scrollbar presentation."""
import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');rows=[{'browser':'edge','scope':'translations','variant':'original','exit_code':0,'output':str(r/'original-translations-edge-diagnostic')}]
assert json.loads((r/'original-translations-edge-diagnostic/lifecycle.json').read_text())['test_exit_code']==0
functional=json.loads((r/'functional-runs.json').read_text());assert len(functional)==12 and all(row['exit_code']==0 for row in functional)
for scope in ('application','keyboard','collections','translations'):
 for browser in ('chrome','edge'):
  if any(row['browser']==browser and row['scope']==scope for row in rows):continue
  output=r/f'original-{scope}-{browser}'
  with output.with_suffix('.log').open('w') as log:
   code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-browser.py'),'--variant','original','--browser',browser,'--browser-scope',scope,'--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
  rows.append({'browser':browser,'scope':scope,'variant':'original','exit_code':code,'output':str(output)})
  (r/'original-visual-runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(browser,code,flush=True)
  if code:raise SystemExit(code)
