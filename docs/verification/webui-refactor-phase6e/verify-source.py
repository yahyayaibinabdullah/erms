import ast,copy,hashlib,json,collections
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6e');old=ast.parse((r/'app-before.py').read_text());new=ast.parse(Path('frontend/webui/app.py').read_text())
modules=['security_level_controls','access_control_dialogs','access_explanation_dialog','security_administration']
trees=[ast.parse(Path(f'frontend/webui/{m}.py').read_text()) for m in modules]
def funcs(t):return {n.name:n for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a=funcs(old);b=funcs(new)
for t in trees:b.update(funcs(t))
class Readers(ast.NodeTransformer):
 def visit_Subscript(self,n):
  if ast.unparse(n)=="current_direction['value']":return ast.Call(func=ast.Name(id='direction',ctx=ast.Load()),args=[],keywords=[])
  return self.generic_visit(n)
 def visit_Call(self,n):
  if ast.unparse(n)=="auth_state.get('principal')":return ast.Call(func=ast.Name(id='principal',ctx=ast.Load()),args=[],keywords=[])
  return self.generic_visit(n)
def norm(n):return ast.dump(Readers().visit(copy.deepcopy(n)),include_attributes=False)
names=['bind_resource_security_select','show_contextual_acl_roles','show_acl_editor','show_access_explanation','show_security_level_change','show_profile_privilege_editor','localized_privilege_name','localized_privilege_description','localized_privilege_category','localized_privilege_matches_search','localized_profile_value']
proof={name:norm(a[name])==norm(b[name]) for name in names}
assert all(proof.values()),proof
# Inline the narrow profile helpers back into the shared editor, then compare
# its entire AST. This proves that only the approved ownership boundaries moved.
editor=a['open_editor']
profile_test=next(n for n in ast.walk(editor) if isinstance(n,ast.BoolOp) and ast.unparse(n)=="spec.key == 'profiles' and row.get('code') == 'TEXT_INDEXER_SERVICE'")
field_rule=next(n for n in ast.walk(editor) if isinstance(n,ast.If) and ast.unparse(n.test)=="spec.key == 'profiles' and field.name == 'code' and (not creating)")
reason_field=next(n.value for n in ast.walk(editor) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='profile_change_reason' for t in n.targets) and isinstance(n.value,ast.Call))
pop_code=next(n for n in ast.walk(editor) if isinstance(n,ast.Expr) and ast.unparse(n)=="payload.pop('code', None)")
reason_rule=next(n for n in ast.walk(editor) if isinstance(n,ast.If) and ast.unparse(n.test)=='profile_change_reason is not None')
class InlineProfiles(ast.NodeTransformer):
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name) and n.func.id=='profile_translation_only':return copy.deepcopy(profile_test)
  if isinstance(n.func,ast.Name) and n.func.id=='profile_reason_input':return copy.deepcopy(reason_field)
  return self.generic_visit(n)
 def visit_If(self,n):
  if n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Call) and isinstance(n.body[0].value.func,ast.Name) and n.body[0].value.func.id=='configure_profile_field':return copy.deepcopy(field_rule)
  return self.generic_visit(n)
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='prepare_profile_update':return copy.deepcopy(pop_code)
  return self.generic_visit(n)
 def visit_Assign(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='validated_profile_change_reason':return copy.deepcopy(reason_rule.body)
  return self.generic_visit(n)
assert ast.dump(editor,include_attributes=False)==ast.dump(InlineProfiles().visit(copy.deepcopy(b['open_editor'])),include_attributes=False)

# Every unchanged host function retains its exact body.
def direct(t):return {n.name:n for n in funcs(t)['index'].body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
da,db=direct(old),direct(new)
changed=[name for name,n in da.items() if name not in db or ast.dump(n,include_attributes=False)!=ast.dump(db[name],include_attributes=False)]
assert set(changed)==set(names[:6])|{'open_editor'},changed
# All styling and user-visible message keys are conserved across the move.
def literals(ts,methods):
 return collections.Counter((n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id,ast.dump(arg,include_attributes=False)) for t in ts for n in ast.walk(t) if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in methods) or (isinstance(n.func,ast.Name) and n.func.id in methods)) for arg in n.args if isinstance(arg,ast.Constant) and isinstance(arg.value,str))
for methods in [{'classes','props','style','tooltip'},{'render_message','render_message_plain'}]:
 assert literals([old],methods)==literals([new,*trees],methods),methods
before=json.loads((r/'source-before.json').read_text())
changed_runtime=[p for p,h in before.items() if '/tests/' not in p and Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed_runtime==['frontend/webui/app.py'],changed_runtime
result={'identical_functions_after_principal_direction_readers':proof,'unchanged_direct_host_functions':len(da)-len(changed),'changed_host_adapters':changed,'shared_editor_identical_after_profile_helper_inlining':True,'styling_literals_identical':True,'message_key_literals_identical':True,'changed_existing_runtime_files':changed_runtime}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
