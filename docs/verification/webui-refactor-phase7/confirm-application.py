import json,subprocess,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');q=r/'chrome-resumed-queue.json'
while not(q.exists() and len(json.loads(q.read_text()))==4):time.sleep(1)
out=r/'application-chrome-confirmed'
with out.with_suffix('.log').open('w') as log:
 code=subprocess.call(['backend/services/api/.venv/bin/python','tools/run_webui_integration.py','--browser','chrome','--browser-scope','application','--output',str(out)],stdout=log,stderr=subprocess.STDOUT)
(r/'application-chrome-confirmed-result.json').write_text(json.dumps({'exit_code':code,'output':str(out)},indent=2)+'\n')
raise SystemExit(code)
