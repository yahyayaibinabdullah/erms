import ast, copy, json, collections, hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6f')
old=ast.parse((r/'app-before.py').read_text());new=ast.parse(Path('frontend/webui/app.py').read_text());module=ast.parse(Path('frontend/webui/login_sessions.py').read_text())
def functions(tree):return {n.name:n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b,m=functions(old),functions(new),functions(module)
class Restore(ast.NodeTransformer):
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name) and n.func.id=='principal':return ast.parse('auth_state["principal"]').body[0].value
  return self.generic_visit(n)
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name):
   if n.value.func.id=='enter':return copy.deepcopy(b['enter_login_sessions'].body)
   if n.value.func.id=='current_session_revoked':return copy.deepcopy(b['current_session_revoked'].body)
  return self.generic_visit(n)
assert ast.dump(a['select_login_sessions'])==ast.dump(Restore().visit(copy.deepcopy(m['select_login_sessions'])))
def direct(t):return {n.name:n for n in functions(t)['index'].body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
da,db=direct(old),direct(new)
changed=[name for name,n in da.items() if name not in db or ast.dump(n)!=ast.dump(db[name])]
assert changed==['select_login_sessions'],changed
def literals(ts,methods):
 return collections.Counter((n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id,ast.dump(arg)) for t in ts for n in ast.walk(t) if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in methods) or (isinstance(n.func,ast.Name) and n.func.id in methods)) for arg in n.args if isinstance(arg,ast.Constant) and isinstance(arg.value,str))
for methods in [{'classes','props','style','tooltip'},{'render_message','render_message_plain'}]:assert literals([old],methods)==literals([new,module],methods)
before=json.loads((r/'source-before.json').read_text())
changed_runtime=[p for p,h in before.items() if '/tests/' not in p and Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed_runtime==['frontend/webui/app.py'],changed_runtime
result={'session_function_identical_after_inlining_host_callbacks':True,'unchanged_direct_host_functions':len(da)-1,'styling_and_message_literals_identical':True,'changed_existing_runtime_files':changed_runtime}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
