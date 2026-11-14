from pathlib import Path
import json,hashlib,collections,statistics,re
from PIL import Image,ImageChops
root=Path('.runtime/webui-refactor-phase6a'); evidence=Path('docs/verification/webui-refactor-phase6a')
result={}
for browser,before in [('chrome','before-chrome-5'),('edge','before-edge-2')]:
 a,b=root/before,root/('after-'+browser)
 old=json.loads((a/'browser-results.json').read_text());new=json.loads((b/'browser-results.json').read_text())
 assert old['complete'] and new['complete']
 assert old['focus']==new['focus']
 comparisons=[]
 for row in new['screenshots']:
  name=row['file']; x,y=Image.open(a/name).convert('RGB'),Image.open(b/name).convert('RGB')
  assert x.size==y.size
  bbox=ImageChops.difference(x.crop((0,72,x.width,x.height)),y.crop((0,72,y.width,y.height))).getbbox()
  comparisons.append({'file':name,'identical_below_animated_header':bbox is None,'difference_box_below_y72':bbox})
 def requests(report):
  return collections.Counter((e['method'],re.sub(r'/\d+$','/{id}',e['path']),e['query'],e['status'],e['controlled']) for e in report['relationship_requests'])
 assert requests(old)==requests(new), (browser,requests(old)-requests(new),requests(new)-requests(old))
 def timing(report):
  times=[e['milliseconds'] for e in report['relationship_requests'] if e['method']=='GET' and not e['controlled'] and e['status']==200]
  return {'median_ms':statistics.median(times),'max_ms':max(times),'count':len(times)}
 hashes=json.loads((b/'source-environment.json').read_text())['sha256']
 assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
 result[browser]={'before':before,'after':'after-'+browser,'checks':len(new['checks']),'screenshots':comparisons,'focus':new['focus'],'focus_equal':True,'request_counts_and_queries_equal':True,'uncontrolled_read_times_before':timing(old),'uncontrolled_read_times_after':timing(new),'final_sources_match':True}
result['limits']='Full original screenshots retained; comparison excludes only the unchanged animated header above y72. API durations include server processing under shared local load; they are not end-to-end performance guarantees.'
(evidence/'browser-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
for k in ('chrome','edge'):
 print(k, 'matching images',sum(x['identical_below_animated_header'] for x in result[k]['screenshots']), '/',len(result[k]['screenshots']))
 print('differences',[x for x in result[k]['screenshots'] if not x['identical_below_animated_header']])
