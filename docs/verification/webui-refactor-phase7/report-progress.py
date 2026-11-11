import json
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7')
for browser in ('chrome','edge'):
 q=r/(browser+'-resumed-queue.json')
 print(browser,'completed',json.loads(q.read_text()) if q.exists() else [])
 for scope in ('application','components'):
  p=r/(scope+'-'+browser+'-resumed')
  if p.exists():
   pics=list(p.glob('*.png'));last=max(pics,key=lambda p:p.stat().st_mtime).name if pics else None
   print(scope,len(pics),last)
p=r/'performance-queue.json'
print('performance',json.loads(p.read_text()) if p.exists() else 'not yet completed a run')
for p in r.glob('performance-*/browser-results.json'):
 d=json.loads(p.read_text());samples=d.get('performance_samples',[]);print(p.parent.name,d['complete'],len(samples),samples[-1]['workflow'] if samples else '',d['checks'][-1]['status'])
