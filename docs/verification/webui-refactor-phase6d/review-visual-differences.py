"""Verify observed differences are confined to the inspected fixture timestamps.

Original screenshots remain intact. The full pixel comparison is preserved;
this supplemental check identifies the differing existing timestamp fields.
"""
from pathlib import Path
import json
from PIL import Image,ImageChops
root=Path('.runtime/webui-refactor-phase6d');review=[]
for browser in ('chrome','edge'):
 result=json.loads((root/f'{browser}-comparison.json').read_text())
 for scene in result['screenshots']:
  name=scene['file']
  if not scene['changed_pixels_below_header']:continue
  assert name in {'classification-scheme-detail-en.png','classification-scheme-detail-ar.png','classification-word-dialog-en.png','classification-word-dialog-ar.png'}
  before=Image.open(root/f'before-{browser}-4'/name).convert('RGB')
  after=Image.open(root/f'after-{browser}-1'/name).convert('RGB')
  diff=ImageChops.difference(before,after)
  rtl=name.endswith('-ar.png')
  # Full-image coordinates: existing First used and Last updated value rows.
  left,right=(480,640) if rtl else (800,950)
  regions=[(left,568,right,588),(left,620,right,644)]
  checked=0
  for y in range(72,diff.height):
   for x in range(diff.width):
    if diff.getpixel((x,y))!=(0,0,0):
     assert any(l<=x<r and t<=y<b for l,t,r,b in regions),(name,x,y)
     checked+=1
  assert checked==scene['changed_pixels_below_header']
  review.append({'browser':browser,'file':name,'changed_pixels':checked,'reviewed_fields':['First used','Last updated'],'cause':'Disposable fixture first-use trigger recorded the separate run times (17:03 baseline; 17:06 extracted).','timestamp_regions_full_image':regions,'changed_pixels_outside_timestamp_fields_below_header':0})
(root/'visual-review.json').write_text(json.dumps({'identical_scenes_per_browser':14,'timestamp_only_scenes_per_browser':4,'review':review},indent=2)+'\n')
print('All differing pixels are within the two inspected timestamp values; no other changes below the animated header.')
