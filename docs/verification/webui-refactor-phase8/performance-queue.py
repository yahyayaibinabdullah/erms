"""Run the complete original/current ABBA comparison after functional gates finish."""
import json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8')
functional=json.loads((r/'functional-runs.json').read_text());assert len(functional)==12 and all(x['exit_code']==0 for x in functional)
for p in r.glob('*/lifecycle.json'):assert json.loads(p.read_text())['database_dropped'],p
for p in (r/'full-webui/1-unit.xml',r/'full-webui/1-interaction.xml',r/'full-assembled/assembled.xml'):
 cases=list(ET.parse(p).getroot().iter('testcase'));assert cases and not any(c.find(t) is not None for c in cases for t in ('failure','error','skipped'))
assert json.loads((r/'visual-review.json').read_text())['all_differences_reviewed']
original_visual=json.loads((r/'original-visual-runs.json').read_text());assert len(original_visual)==8 and all(x['exit_code']==0 for x in original_visual)
results=[]
for browser in ('chrome','edge'):
 for number,variant in enumerate(('original','current','current','original'),1):
  output=r/f'performance-{browser}-{number}-{variant}'
  with output.with_suffix('.log').open('w') as log:
   code=subprocess.call(['backend/services/api/.venv/bin/python',str(r/'run-browser.py'),'--variant',variant,'--browser',browser,'--browser-scope','performance','--output',str(output)],stdout=log,stderr=subprocess.STDOUT)
  results.append({'browser':browser,'sequence':number,'variant':variant,'exit_code':code,'output':str(output)})
  (r/'performance-runs.json').write_text(json.dumps(results,indent=2)+'\n');print(browser,number,variant,code,flush=True)
  if code:raise SystemExit(code)
