"""Check every changed pixel against the inspected fixture timestamp locations."""
from pathlib import Path
import json
from PIL import Image,ImageChops
root=Path('.runtime/webui-refactor-phase6e');review=[]
for browser in ('chrome','edge'):
 result=json.loads((root/f'{browser}-comparison.json').read_text())
 assert sum(not s['changed_pixels_below_header'] for s in result['screenshots'])==16
 for scene in result['screenshots']:
  name=scene['file']
  if not scene['changed_pixels_below_header']:continue
  assert name in {'security-profile-privileges-en.png','security-profile-filter-en.png','security-profile-privileges-ar.png','security-profile-filter-ar.png'}
  before=Image.open(root/f'before-{browser}-final'/name).convert('RGB')
  after=Image.open(root/f'after-{browser}'/name).convert('RGB')
  diff=ImageChops.difference(before,after);rtl=name.endswith('-ar.png')
  left,right=(70,225) if rtl else (1130,1280)
  regions=[(left,408,right,426),(left,611,right,631),(left,813,right,832)]
  checked=0
  for y in range(72,diff.height):
   for x in range(diff.width):
    if diff.getpixel((x,y))!=(0,0,0):
     assert any(l<=x<r and t<=y<b for l,t,r,b in regions),(name,x,y)
     checked+=1
  assert checked==scene['changed_pixels_below_header']
  review.append({'browser':browser,'file':name,'changed_pixels':checked,'reviewed_fields':['Last updated on the three visible background profile cards'], 'cause':'Disposable seed timestamps differ between runs: 08:02 PM baseline, 08:05 PM extracted.','timestamp_regions_full_image':regions,'changed_pixels_outside_timestamp_fields_below_header':0})
(root/'visual-review.json').write_text(json.dumps({'identical_scenes_per_browser':16,'timestamp_only_scenes_per_browser':4,'review':review},indent=2)+'\n')
print('Every differing pixel below the animated header is inside the three inspected Last updated timestamp fields.')
