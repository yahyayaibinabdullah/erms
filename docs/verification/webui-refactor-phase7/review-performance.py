"""Summarize every positive two-pair result for explicit review, without declaring acceptance."""
import json,statistics
from pathlib import Path
from tools.compare_webui_performance import percentile
r=Path('.runtime/webui-refactor-phase7')
comparison=json.loads((r/'performance-clean-comparison.json').read_text())
runs={}
for row in json.loads((r/'performance-accepted-runs.json').read_text()):
 runs[row['browser'],row['sequence']]=json.loads((Path(row['output'])/'browser-results.json').read_text())
reviews=[]
for browser,rows in comparison['browsers'].items():
 for row in rows:
  metrics=row['repeatable_slower_metrics_to_investigate']
  if not metrics:continue
  details=[]
  for sequence in range(1,5):
   samples=[s for s in runs[browser,sequence]['performance_samples'] if not s['warmup'] and (s['workflow'],s['language'])==(row['workflow'],row['language'])]
   slow=sorted(samples,key=lambda s:s['milliseconds'],reverse=True)[:3]
   details.append({'sequence':sequence,'median_ms':statistics.median(s['milliseconds'] for s in samples),'p90_ms':percentile([s['milliseconds'] for s in samples],.9),'slowest_cycles':[{'cycle':s['cycle'],'total_ms':s['milliseconds'],'api_ms':[e['milliseconds'] for e in s['requests']],'api_paths':[e['path'] for e in s['requests']]} for s in slow]})
  reviews.append({'browser':browser,'workflow':row['workflow'],'language':row['language'],'metrics':metrics,'pairs':row['pairs'],'runs':details})
(r/'performance-review-details.json').write_text(json.dumps(reviews,indent=2)+'\n')
for row in reviews:
 print(row['browser'],row['workflow'],row['language'])
 for metric in row['metrics']:
  print(metric,[(round(p['metrics'][metric]['delta_ms'],1),round(p['metrics'][metric]['delta_percent'],1)) for p in row['pairs']])
 for run in row['runs']:
  print(run['sequence'],[(round(s['total_ms'],1),round(max(s['api_ms'],default=0),1)) for s in run['slowest_cycles']])
