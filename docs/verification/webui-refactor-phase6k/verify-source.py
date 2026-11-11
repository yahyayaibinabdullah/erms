import ast,json,hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6k');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in index(t).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
def dump(n):return ast.dump(n,include_attributes=False)
a,b=funcs(before),funcs(after)
class Restore(ast.NodeTransformer):
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name):
   replacements={'principal':'auth_state.get("principal")','enter_holds':'state.update(resource="holds", rows=[], searched=True)','enter_hold_details':'state.update(resource="hold-details", rows=[], searched=True)'}
   if n.func.id in replacements:return ast.parse(replacements[n.func.id],mode='eval').body
  return self.generic_visit(n)
checked=[]
for p in [Path('frontend/webui',name+'.py') for name in ('holds_people','hold_editor','hold_resources','holds','hold_details','hold_navigation')]:
 for n in ast.walk(ast.parse(p.read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in a:
   assert dump(Restore().visit(n))==dump(a[n.name]),n.name
   checked.append(n.name)
unchanged=[n for n in a if n not in checked];assert all(dump(a[n])==dump(b[n]) for n in unchanged)
old=json.loads((r/'source-before.json').read_text());changed=[p for p,h in old.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
original_style=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='style_person_select')
new_style=next(n for n in ast.parse(Path('frontend/webui/holds_people.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='style_person_select')
assert dump(original_style)==dump(new_style)
checked.append('style_person_select')
result={'functions_reconstructed':checked,'other_host_functions_identical':len(unchanged),'existing_runtime_changes':changed,'translation_and_inspector_JS_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
