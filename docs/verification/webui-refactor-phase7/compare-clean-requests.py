"""Retain per-action request shape/count distributions beside timing results."""
from collections import Counter,defaultdict
import json,re
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');runs={}
uuid=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',re.I)
for row in json.loads((r/'performance-accepted-runs.json').read_text()):
 assert row['exit_code']==0
 d=json.loads((Path(row['output'])/'browser-results.json').read_text());assert d['complete']
 groups=defaultdict(Counter)
 for sample in d['performance_samples']:
  if sample['warmup']:continue
  requests=Counter((event['method'],uuid.sub('<fixture-id>',event['path']),uuid.sub('<fixture-id>',event['query']),event['status']) for event in sample['requests'])
  key=json.dumps(sorted([[*shape,count] for shape,count in requests.items()]))
  groups[(sample['workflow'],sample['language'])][key]+=1
 runs[(row['browser'],row['sequence'])]=groups
results=[]
for browser in ('chrome','edge'):
 for original,current in ((1,2),(4,3)):
  a,b=runs[(browser,original)],runs[(browser,current)];assert set(a)==set(b)
  for key in sorted(a):
   results.append({'browser':browser,'original_sequence':original,'current_sequence':current,'workflow':key[0],'language':key[1],'equal':a[key]==b[key],'original_distribution':dict(a[key]),'current_distribution':dict(b[key])})
(r/'performance-clean-request-comparison.json').write_text(json.dumps({'method':'Compare request method, route, query, status and count per measured action, with only synthetic UUIDs normalized. Existing stream/catch-up/unread polling was excluded by the timing driver; raw metadata remains.','comparisons':results,'differences':[x for x in results if not x['equal']]},indent=2)+'\n')
print(len(results),'paired workflow request comparisons;',sum(not x['equal'] for x in results),'differences to review')
