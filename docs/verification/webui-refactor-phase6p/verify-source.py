import ast,json,hashlib,copy,re
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6p')
def funcs(tree):
 index=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='index')
 return {n.name:n for n in [*tree.body,*index.body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
a=funcs(ast.parse((r/'app-before.py').read_text()));b=funcs(ast.parse(Path('frontend/webui/app.py').read_text()));moved=[]
for entry in json.loads((r/'extraction-map.json').read_text()):
 source=Path('frontend/webui',entry['module']+'.py').read_text()
 tree=ast.parse(source)
 for name in entry['functions']:
  node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
  body=ast.get_source_segment(source,node)
  for old,new in reversed(entry['replacements']):
   if not new.isidentifier():body=body.replace(new,old)
  node=ast.parse(body).body[0]
  names={new:old for old,new in entry['replacements'] if new.isidentifier()}
  class Names(ast.NodeTransformer):
   def visit_Name(self,n):return ast.parse(names[n.id],mode='eval').body if n.id in names else n
  node=Names().visit(node)
  assert dump(node)==dump(a[name]),name;moved.append(name)
for name in a:
 if name not in moved:assert dump(a[name])==dump(b[name]),name
feature=ast.parse(Path('frontend/webui/governance_custody.py').read_text())
factory=next(n for n in feature.body if isinstance(n,ast.FunctionDef) and n.name=='build_governance_custody')
assert isinstance(factory.body[0],ast.Assign) and factory.body[0].targets[0].id=='custody_state'
assert isinstance(factory.body[0].value,ast.Dict) and not factory.body[0].value.keys
assert 'custody_page_token' not in Path('frontend/webui/app.py').read_text()
manifest=json.loads((r/'source-before.json').read_text());changed=[p for p,h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'moved_functions_reconstructed':moved,'other_functions_reconstructed':len(a)-len(moved),'existing_runtime_changes':changed,'ownership':'Custody refresh token is private to each per-client factory; report pagers remain private to each render. Narrow principal/page and Settings callbacks preserve lifecycle checks.','catalogue_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
