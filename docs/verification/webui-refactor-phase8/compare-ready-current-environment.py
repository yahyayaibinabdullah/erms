"""Compare retained final captures with accepted baselines without replacing them."""
import copy,json
from pathlib import Path
from PIL import Image,ImageChops
r=Path('.runtime/webui-refactor-phase8');rows=[];focus=[]
for browser in ('chrome','edge'):
 for scope in ('full','session','application','keyboard','collections','translations'):
  if scope in {'application','keyboard','collections','translations'} and not any(x['scope']==scope and x['browser']==browser for x in json.loads((r/'original-visual-runs.json').read_text())):continue
  current=Path(next(x['output'] for x in json.loads((r/'functional-runs.json').read_text()) if x['scope']==scope and x['browser']==browser))
  if scope=='collections':
   baseline=Path('docs/verification/webui-refactor-phase6g')/('after-collections-edge-settled' if browser=='edge' else 'after-collections-chrome')
  elif scope=='translations':
   baseline=Path('docs/verification/webui-refactor-phase6j')/f'after-{browser}-final'
  else:
   name=f'{scope}-{browser}'
   if scope in {'full','application','keyboard'}:name+='-resumed'
   if scope=='application' and browser=='chrome':name='application-chrome-confirmed'
   baseline=Path('docs/verification/webui-refactor-phase7')/name
  if scope in {'application','keyboard','collections','translations'}:
   baseline=Path(next(x['output'] for x in json.loads((r/'original-visual-runs.json').read_text()) if x['scope']==scope and x['browser']==browser))
  old=json.loads((baseline/'browser-results.json').read_text());new=json.loads((current/'browser-results.json').read_text())
  assert old['complete'] and new['complete']
  left={s['file']:s for s in old['screenshots']};right={s['file']:s for s in new['screenshots']};assert left.keys()==right.keys(),(scope,browser)
  for name,shot in right.items():
   assert shot['environment']==left[name]['environment'],(scope,browser,name)
   a=Image.open(baseline/name).convert('RGB');b=Image.open(current/name).convert('RGB');assert a.size==b.size
   box=(0,72,*a.size);diff=ImageChops.difference(a.crop(box),b.crop(box));bbox=diff.getbbox()
   changed=sum(count for color,count in enumerate(diff.convert('L').histogram()) if color)
   rows.append({'scope':scope,'browser':browser,'image':name,'baseline':str(baseline/name),'current':str(current/name),'compared_region':box,'different_pixels_luminance':changed,'difference_bbox_relative_to_region':bbox})
  if scope=='keyboard':
   def normalize(d):
    d=copy.deepcopy(d);d.pop('id',None);d.get('indicator',{}).pop('opacity',None);return d
   before=[normalize(x) for x in old['keyboard_observations']];after=[normalize(x) for x in new['keyboard_observations']]
   assert len(before)==len(after)==58
   focus.append({'browser':browser,'observations':len(after),'differences':[{'baseline':a,'current':b} for a,b in zip(before,after) if a!=b]})
result={'method':'Phase 7 full/session captures and fresh hash-verified pre-refactor application/keyboard/collections/translation captures in the current native scrollbar environment; full images retained. Automated pixel comparison excludes only the animated top 72 pixels. Nonexact images require review; no new baseline is accepted automatically.','paired':len(rows),'exact_below_header':sum(x['difference_bbox_relative_to_region'] is None for x in rows),'rows':rows}
(r/'visual-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
(r/'keyboard-comparison.json').write_text(json.dumps({'excluded':'Generated DOM IDs and focus-helper animation opacity only; all semantic properties, geometry and other indicator properties compared.','browsers':focus},indent=2)+'\n')
print('paired',len(rows),'exact below header',result['exact_below_header'],'focus differences',sum(len(x['differences']) for x in focus))
for row in rows:
 if row['difference_bbox_relative_to_region'] is not None:print(row['scope'],row['browser'],row['image'],row['difference_bbox_relative_to_region'],row['different_pixels_luminance'])
