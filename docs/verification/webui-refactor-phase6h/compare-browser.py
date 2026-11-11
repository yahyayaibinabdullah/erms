import json,sys,collections,math
from pathlib import Path
from PIL import Image,ImageChops
base=Path('.runtime/webui-refactor-phase6h');browser=sys.argv[1]
before=base/('before-edge-settled' if browser=='edge' else 'before-chrome-final');after=base/f'after-{browser}'
a=json.loads((before/'browser-results.json').read_text());b=json.loads((after/'browser-results.json').read_text())
# Early scope registration omitted only the completion flag; retain raw
# reports and require every expected check and scene, never infer from exit.
assert all(len(v['checks'])==7 and all(c['status']=='pass' for c in v['checks']) and len(v['screenshots'])==12 for v in (a,b))
assert a['indexer_focus']==b['indexer_focus']
assert not a.get('browser_errors') and not b.get('browser_errors')
results=[]
for item in a['screenshots']:
 name=item['file'];x=Image.open(before/name).convert('RGB');y=Image.open(after/name).convert('RGB');assert x.size==y.size
 diff=ImageChops.difference(x,y);channels=diff.split();maximum=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
 points=[(px,py) for py in range(72,x.height) for px in range(x.width) if maximum.getpixel((px,py))]
 language='ar' if name.endswith('-ar.png') else 'en'
 regions=[r['rect'] for report in (a,b) for r in report['observation_regions'] if r['language']==language]
 def in_observation(px,py):return any(r['x']-1<=px<=r['x']+r['width']+1 and r['y']-1<=py<=r['y']+r['height']+1 for r in regions)
 outside=[(px,py) for px,py in points if not in_observation(px,py)]
 results.append({'file':name,'changed_pixels_below_header':len(points),'outside_live_observation':len(outside),'bbox':diff.crop((0,72,x.width,x.height)).getbbox(),'outside_bbox':[min(px for px,py in outside),min(py for px,py in outside),max(px for px,py in outside),max(py for px,py in outside)] if outside else None})
 if points:diff.save(base/f'{browser}-diff-{name}')
def requests(folder):
 return collections.Counter((e['method'],e['path'],e['query'],e['status']) for e in map(json.loads,(folder/'requests.jsonl').read_text().splitlines()) if e['path'] not in {'/api/v1/messages/catch-up','/api/v1/messages/unread-count'})
ca,cb=requests(before),requests(after)
result={'browser':browser,'focus_identical':True,'no_browser_errors':True,'screenshots':results,'requests_only_before':[(k,n) for k,n in (ca-cb).items()],'requests_only_after':[(k,n) for k,n in (cb-ca).items()],'live_observation_regions':{'before':a['observation_regions'],'after':b['observation_regions']}}
(base/f'{browser}-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
