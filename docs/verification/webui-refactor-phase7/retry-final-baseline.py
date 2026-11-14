import json,subprocess
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');out=r/'performance-edge-4-original-retry'
with out.with_suffix('.log').open('w') as log:
 code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-original-ui.py'),'--browser','edge','--browser-scope','performance','--output',str(out)],stdout=log,stderr=subprocess.STDOUT)
(r/'performance-edge-retry-result.json').write_text(json.dumps({'exit_code':code,'output':str(out)},indent=2)+'\n')
if code==0:
 rows=json.loads((r/'performance-queue.json').read_text());assert len(rows)==8 and rows[-1]['exit_code']!=0
 rows[-1]={**rows[-1],'output':str(out),'exit_code':0,'replaces_incomplete_run':rows[-1]['output']}
 (r/'performance-final-runs.json').write_text(json.dumps(rows,indent=2)+'\n')
raise SystemExit(code)
