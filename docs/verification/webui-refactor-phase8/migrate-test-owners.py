import ast,json
from pathlib import Path
removed=json.loads(Path('.runtime/webui-refactor-phase8/import-cleanup.json').read_text())['removed']
changes=[]
for p in [*Path('frontend/webui/tests').glob('*.py'),*Path('frontend/webui/interaction/tests').glob('*.py')]:
 s=p.read_text();tree=ast.parse(s);aliases=set()
 for n in ast.walk(tree):
  if isinstance(n,ast.ImportFrom) and n.module=='frontend.webui':
   aliases.update(a.asname or a.name for a in n.names if a.name=='app')
 if not aliases:continue
 lines=s.splitlines(keepends=True);offset=[0]
 for line in lines:offset.append(offset[-1]+len(line))
 edits=[];imports={}
 for n in ast.walk(tree):
  if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id in aliases and n.attr in removed:
   item=removed[n.attr];alias='_owner_'+n.attr;imports[alias]=item
   edits.append((offset[n.lineno-1]+n.col_offset,offset[n.end_lineno-1]+n.end_col_offset,alias))
 for start,end,text in sorted(edits,reverse=True):s=s[:start]+text+s[end:]
 if edits:
  # These files have no future imports; keep their module docstring first.
  tree=ast.parse(s);first=tree.body[0];end=first.end_lineno if isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant) and isinstance(first.value.value,str) else 0
  lines=s.splitlines(keepends=True)
  text=''.join((f"from {item['module']} import {item['name']} as {alias}\n" if item['module'] else f"import {item['name']} as {alias}\n") for alias,item in sorted(imports.items()))
  lines[end:end]=[text];p.write_text(''.join(lines));changes.append(str(p))
# AST-isolated function tests resolve module globals from the real feature owner.
for name,alias,owner in [('test_advanced_search_retention.py','webui','advanced_search'),('test_capture_preparation.py','webapp','record_capture'),('test_dashboard_identity.py','webui','dashboard')]:
 p=Path('frontend/webui/interaction/tests')/name;s=p.read_text();s=s.replace(f'from frontend.webui import app as {alias}',f'from frontend.webui import app as {alias}\nfrom frontend.webui import {owner} as feature_owner')
 s=s.replace(f'dict(vars({alias}),',f'dict({{**vars({alias}), **vars(feature_owner)}},');p.write_text(s)
Path('.runtime/webui-refactor-phase8/test-owner-migration.json').write_text(json.dumps(changes,indent=2)+'\n')
print('Explicit owner imports:',len(changes),'test files')
