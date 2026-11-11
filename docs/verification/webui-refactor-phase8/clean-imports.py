import ast,json
from pathlib import Path
p=Path('frontend/webui/app.py');s=p.read_text();lines=s.splitlines(keepends=True);tree=ast.parse(s)
loads={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
removed={};edits=[]
for node in tree.body:
 if not isinstance(node,(ast.Import,ast.ImportFrom)) or getattr(node,'module',None)=='__future__':continue
 keep=[]
 for alias in node.names:
  name=alias.asname or alias.name.split('.')[0]
  if name in loads:keep.append(alias)
  else:
   module=getattr(node,'module',None)
   if isinstance(node,ast.ImportFrom) and node.level:module='frontend.webui.'+module
   removed[name]={'module':module,'name':alias.name,'alias':alias.asname}
 if len(keep)!=len(node.names):
  text=''
  if keep:
   new=ast.Import(names=keep) if isinstance(node,ast.Import) else ast.ImportFrom(module=node.module,names=keep,level=node.level)
   text=ast.unparse(new)+'\n'
  edits.append((node.lineno-1,node.end_lineno,text))
for start,end,text in reversed(edits):lines[start:end]=[text]
p.write_text(''.join(lines))
# Test-only reexports are replaced by imports from their actual owners.
changed=[]
for p in list(Path('frontend/webui/tests').glob('*.py'))+list(Path('frontend/webui/interaction/tests').glob('*.py')):
 s=p.read_text();lines=s.splitlines(keepends=True);edits=[]
 for node in ast.walk(ast.parse(s)):
  if not isinstance(node,ast.ImportFrom) or node.module!='frontend.webui.app':continue
  keep=[];imports=[]
  for alias in node.names:
   if alias.name not in removed:keep.append(alias);continue
   item=removed[alias.name];imports.append(ast.ImportFrom(module=item['module'],level=0,names=[ast.alias(name=item['name'],asname=alias.asname or (alias.name if item['name']!=alias.name else None))]))
  if len(keep)==len(node.names):continue
  if keep:imports.insert(0,ast.ImportFrom(module=node.module,level=0,names=keep))
  indent=' '*node.col_offset
  edits.append((node.lineno-1,node.end_lineno,''.join(indent+ast.unparse(n)+'\n' for n in imports)))
 for start,end,text in sorted(edits,reverse=True):lines[start:end]=[text]
 if edits:p.write_text(''.join(lines));changed.append(str(p))
Path('.runtime/webui-refactor-phase8/import-cleanup.json').write_text(json.dumps({'removed':removed,'direct_import_test_files':changed},indent=2)+'\n')
print('Removed',len(removed),'unused application imports; migrated',len(changed),'test import files')
