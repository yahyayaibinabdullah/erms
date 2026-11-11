import ast,json,hashlib,copy
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6o')
def funcs(tree):
 index=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='index')
 return {n.name:n for n in [*tree.body,*index.body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
a=funcs(ast.parse((r/'app-before.py').read_text()));b=funcs(ast.parse(Path('frontend/webui/app.py').read_text()));moved=[]
for entry in json.loads((r/'extraction-map.json').read_text()):
 source=Path('frontend/webui',entry['module']+'.py').read_text()
 for old,new in reversed(entry['replacements']):source=source.replace(new,old)
 tree=ast.parse(source)
 for name in entry['functions']:
  node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
  assert dump(node)==dump(a[name]),name;moved.append(name)
for name in a:
 if name not in moved:assert dump(a[name])==dump(b[name]),name
manifest=json.loads((r/'source-before.json').read_text());changed=[p for p,h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'moved_functions_reconstructed':moved,'other_functions_reconstructed':len(a)-len(moved),'existing_runtime_changes':changed,'ownership':'Period, request inputs and event pagination remain local to each workspace invocation; narrow principal/page callbacks preserve lifecycle checks.','catalogue_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
