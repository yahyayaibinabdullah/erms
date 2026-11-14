"""Make labelled, full-resolution before/after crops for every pixel difference."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
r=Path('.runtime/webui-refactor-phase8');out=r/'visual-review';out.mkdir(exist_ok=True)
rows=json.loads((r/'visual-comparison.json').read_text())['rows'];manifest=[]
for i,row in enumerate(rows):
 box=row['difference_bbox_relative_to_region']
 if box is None:continue
 a=Image.open(row['baseline']).convert('RGB');b=Image.open(row['current']).convert('RGB')
 x0,y0,x1,y1=box;box=(max(0,x0-16),max(0,y0+72-16),min(a.width,x1+16),min(a.height,y1+72+16))
 a=a.crop(box);b=b.crop(box)
 sheet=Image.new('RGB',(max(a.width,b.width),a.height+b.height+60),'white');d=ImageDraw.Draw(sheet)
 d.text((4,4),f"{i}: {row['scope']} {row['browser']} {row['image']} — BASELINE",fill='black');sheet.paste(a,(0,24))
 d.text((4,a.height+30),'CURRENT',fill='black');sheet.paste(b,(0,a.height+54))
 path=out/f'difference-{i:03}.png';sheet.save(path)
 manifest.append({'index':i,'scope':row['scope'],'browser':row['browser'],'image':row['image'],'crop':box,'review_image':str(path),'difference_pixels':row['different_pixels_luminance']})
(out/'difference-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
