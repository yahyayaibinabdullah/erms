import ast,copy,hashlib,json,collections
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6d');old=ast.parse((r/'app-before.py').read_text());new=ast.parse(Path('frontend/webui/app.py').read_text())
modules=['classification_controller','classification_editor','classification_selectors']
trees=[ast.parse(Path(f'frontend/webui/{m}.py').read_text()) for m in modules]
def funcs(t):return {n.name:n for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a=funcs(old);b=funcs(new)
for t in trees:b.update(funcs(t))
class Direction(ast.NodeTransformer):
 def visit_Subscript(self,n):
  if ast.unparse(n)=='current_direction[\'value\']':return ast.Call(func=ast.Name(id='direction',ctx=ast.Load()),args=[],keywords=[])
  return self.generic_visit(n)
def norm(n):return ast.dump(Direction().visit(copy.deepcopy(n)),include_attributes=False)
selector_names=['bind_remote_scheme_select','browse_classification_tree','browse_advanced_classification']
proof={name:norm(a[name])==norm(b[name]) for name in selector_names}
assert all(proof.values()),proof
# The legacy handlers differ only by the explicit refresh callback.
class Refresh(ast.NodeTransformer):
 def visit_Await(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='load_rows':
   return ast.Await(value=ast.Call(func=ast.Name(id='refresh',ctx=ast.Load()),args=[],keywords=[]))
  return self.generic_visit(n)
for name in ('publish_scheme','change_scheme_lifecycle'):
 assert ast.dump(Refresh().visit(copy.deepcopy(a[name])),include_attributes=False)==ast.dump(b[name],include_attributes=False)
# The retained rule payload and decoration statements are identical.
rule=next(n for n in ast.walk(a['open_editor']) if isinstance(n,ast.If) and ast.unparse(n.test)=="spec.key == 'classifications'" and any(isinstance(x,ast.Name) and x.id=='rule_values' for x in ast.walk(n)))
assert ast.dump(ast.Module(body=rule.body,type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=b['prepare_retention_payload'].body[1:-1],type_ignores=[]),include_attributes=False)
decor=next(n for n in a['decorate_for_spec'].body if isinstance(n,ast.If) and ast.unparse(n.test)=="spec.key == 'classifications'")
assert ast.dump(ast.Module(body=decor.body,type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=b['decorate_classifications'].body,type_ignores=[]),include_attributes=False)
# Existing direct host functions outside the explicit adapters remain exact.
def direct(t):return {n.name:n for n in funcs(t)['index'].body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
da,db=direct(old),direct(new)
changed=[name for name,n in da.items() if name not in db or ast.dump(n,include_attributes=False)!=ast.dump(db[name],include_attributes=False)]
assert set(changed)=={'bind_remote_scheme_select','clear_signed_in_identity','decorate_for_spec','open_editor','render_table','select_advanced_search','select_classification_workspace'},changed
# All literal styling and user-visible message keys are conserved across the move.
def literals(ts,methods):
 return collections.Counter((n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id,ast.dump(arg,include_attributes=False)) for t in ts for n in ast.walk(t) if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in methods) or (isinstance(n.func,ast.Name) and n.func.id in methods)) for arg in n.args if isinstance(arg,ast.Constant) and isinstance(arg.value,str))
for names in [{'classes','props','style','tooltip'},{'render_message','render_message_plain'}]:
 assert literals([old],names)==literals([new,*trees],names),names
before=json.loads((r/'source-before.json').read_text())
# Test fixtures change separately; no existing runtime file other than app.py changes.
changed_runtime=[p for p,h in before.items() if '/tests/' not in p and Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed_runtime==['frontend/webui/app.py'],changed_runtime
result={'identical_selectors_after_direction_reader_substitution':proof,'unchanged_direct_host_functions':len(da)-len(changed),'changed_host_adapters':changed,'retention_payload_and_decoration_identical':True,'legacy_actions_identical_after_refresh_adapter':True,'styling_literals_identical':True,'message_key_literals_identical':True,'changed_existing_runtime_files':changed_runtime}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
