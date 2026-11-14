import json,sys,collections
from pathlib import Path
from PIL import Image,ImageChops
base=Path('.runtime/webui-refactor-phase6d');browser=sys.argv[1]
before=base/f'before-{browser}-4';after=base/f'after-{browser}-1'
a=json.loads((before/'browser-results.json').read_text());b=json.loads((after/'browser-results.json').read_text())
assert a['complete'] and b['complete']
assert a['classification_focus']==b['classification_focus']
assert not a.get('browser_errors') and not b.get('browser_errors')
results=[]
for item in a['screenshots']:
 name=item['file'];x=Image.open(before/name).convert('RGB');y=Image.open(after/name).convert('RGB');assert x.size==y.size
 diff=ImageChops.difference(x.crop((0,72,x.width,x.height)),y.crop((0,72,y.width,y.height)))
 box=diff.getbbox();channels=diff.split();maximum=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2]);count=sum(maximum.histogram()[1:])
 results.append({'file':name,'changed_pixels_below_header':count,'bbox':box,'max_channel_difference':max(high for low,high in diff.getextrema())})
 if box:diff.save(base/f'{browser}-diff-{name}')
def requests(folder):
 return collections.Counter((e['method'],e['path'],e['query'],e['status']) for e in map(json.loads,(folder/'requests.jsonl').read_text().splitlines()) if e['path'] not in {'/api/v1/messages/catch-up','/api/v1/messages/unread-count'})
ca,cb=requests(before),requests(after)
result={'browser':browser,'before':str(before),'after':str(after),'focus_identical':True,'no_browser_errors':True,'screenshots':results,'requests_only_before':[(k,n) for k,n in (ca-cb).items()],'requests_only_after':[(k,n) for k,n in (cb-ca).items()]}
(base/f'{browser}-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'browser':browser,'screenshots':len(results),'differing_scenes':[r for r in results if r['changed_pixels_below_header']], 'requests_only_before':result['requests_only_before'],'requests_only_after':result['requests_only_after']},indent=2))
