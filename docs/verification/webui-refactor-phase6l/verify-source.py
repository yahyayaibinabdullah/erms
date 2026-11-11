import ast,json,hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6l');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in [*t.body,*index(t).body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
a,b=funcs(before),funcs(after);checked=[]
for name in ('component_presentation','component_cards','component_preview','components','upload_buffers'):
 for n in ast.walk(ast.parse(Path('frontend/webui',name+'.py').read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in a:
   assert dump(n)==dump(a[n.name]),n.name
   checked.append(n.name)
unchanged=[n for n in a if n not in checked];assert all(dump(a[n])==dump(b[n]) for n in unchanged)
old=json.loads((r/'source-before.json').read_text());changed=[p for p,h in old.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'functions_identical':checked,'other_host_functions_identical':len(unchanged),'existing_runtime_changes':changed,'translation_and_inspector_JS_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
