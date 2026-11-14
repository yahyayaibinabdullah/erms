import json,statistics,time
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');p=r/'io-probe.jsonl';samples=[]
for mode in ('reopen','persistent','persistent','reopen'):
 writer=p.open('a') if mode=='persistent' else None
 reader=p.open('r') if mode=='persistent' else None
 rows=[]
 try:
  for n in range(120):
   start=time.perf_counter()
   if writer is None:
    with p.open('a') as file:file.write(json.dumps({'event':n})+'\n')
   else:writer.write(json.dumps({'event':n})+'\n');writer.flush()
   written=time.perf_counter()
   if reader is None:p.read_text()
   else:reader.read()
   rows.append({'write_ms':(written-start)*1000,'read_ms':(time.perf_counter()-written)*1000})
 finally:
  if writer:writer.close()
  if reader:reader.close()
 samples.append({'mode':mode,'samples':rows})
(r/'io-probe.json').write_text(json.dumps(samples,indent=2)+'\n')
for run in samples:
 print(run['mode'],[(key,round(statistics.median(x[key] for x in run['samples']),3),round(max(x[key] for x in run['samples']),3)) for key in ('write_ms','read_ms')])
