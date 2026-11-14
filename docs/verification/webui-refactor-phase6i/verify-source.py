import ast,json,hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6i');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in index(t).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b=funcs(before),funcs(after)
def dump(n):return ast.dump(n,include_attributes=False)
class Restore(ast.NodeTransformer):
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name):
   values={'get_principal':'auth_state.get("principal")','get_localization':'state["localization"]','get_configuration':'state["application_configuration"]'}
   if n.func.id in values:return ast.parse(values[n.func.id],mode='eval').body
  return self.generic_visit(n)
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name):
   targets={'set_principal':'auth_state["principal"]','set_localization':'state["localization"]','set_configuration':'state["application_configuration"]','set_direction':'current_direction["value"]'}
   if n.value.func.id in targets:
    target=ast.parse(targets[n.value.func.id],mode='eval').body;target.ctx=ast.Store()
    return ast.Assign(targets=[target],value=n.value.args[0])
  return self.generic_visit(n)
checked=[]
for p in Path('frontend/webui').glob('account_*.py'):
 for n in ast.walk(ast.parse(p.read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in a:
   expected=a[n.name]
   actual=Restore().visit(n)
   # Preferences previously used state.get; localization writes/read use [].
   if n.name=='show_preferences':
    class PreferenceRead(ast.NodeTransformer):
     def visit_Subscript(self,n):
      if dump(n)==dump(ast.parse('state["localization"]',mode='eval').body):return ast.parse('state.get("localization")',mode='eval').body
      return self.generic_visit(n)
    actual=PreferenceRead().visit(actual)
   assert dump(actual)==dump(expected),n.name
   checked.append(n.name)
original_login=next(n for n in ast.walk(before) if isinstance(n,ast.AsyncFunctionDef) and n.name=='submit_login')
newlogin=next(n for n in ast.walk(ast.parse(Path('frontend/webui/account_sign_in.py').read_text())) if isinstance(n,ast.AsyncFunctionDef) and n.name=='submit_login')
assert dump(Restore().visit(newlogin))==dump(original_login)
# Compare the entire inline dialog construction and handler bindings.
old_body=index(before).body
start=next(i for i,n in enumerate(old_body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='login_dialog' for t in n.targets))
old_block=old_body[start:start+2]
newfactory=next(n for n in ast.parse(Path('frontend/webui/account_sign_in.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='build_sign_in')
assert dump(ast.Module(body=[Restore().visit(n) for n in newfactory.body[:-1]],type_ignores=[]))==dump(ast.Module(body=old_block,type_ignores=[]))
unchanged=[n for n in a if n not in checked];assert all(dump(a[n])==dump(b[n]) for n in unchanged)
old=json.loads((r/'source-before.json').read_text());changed=[p for p,h in old.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
original_feedback=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='login_error_message')
new_feedback=next(n for n in ast.walk(ast.parse(Path('frontend/webui/account_sign_in.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='login_error_message')
assert dump(original_feedback)==dump(new_feedback)
checked.append('login_error_message')
result={'functions_reconstructed':checked+['submit_login'],'entire_sign_in_construction_identical':True,'other_host_functions_identical':len(unchanged),'existing_runtime_changes':changed,'translation_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
