import ast,copy,json,textwrap,collections,hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6g');old_source=(r/'app-before.py').read_text();old=ast.parse(old_source);new=ast.parse(Path('frontend/webui/app.py').read_text())
names=['organization_units','organization_roles','organization_users','organization_memberships','organization_deletion','organization_browser','organization_editor','organization_collections','organization_collection_actions','organization_table','administration_cards','identity_presentation']
trees={name:ast.parse(Path('frontend/webui',name+'.py').read_text()) for name in names}
def functions(t):return {n.name:n for n in ast.walk(t) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
def direct(t):return {n.name:n for n in functions(t)['index'].body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
def dump(n):return ast.dump(n,include_attributes=False)
a,b=direct(old),direct(new);proof={}
for name,meta in json.loads((r/'view-extraction.json').read_text()).items():
 n=a[name];body=''.join(old_source.splitlines(True)[n.lineno-1:n.end_lineno])
 for before,after in meta['reader_replacements'].items():body=body.replace(before,after)
 updates=[e for e in ast.walk(n) if isinstance(e,ast.Expr) and isinstance(e.value,ast.Call) and isinstance(e.value.func,ast.Attribute) and ast.unparse(e.value.func)=='state.update']
 if updates:
  replacement='enter_'+meta['module']+'()'
  if name=='select_user_details':
   replacement+='\n        view_token = token'
   body=body.replace('state.get("user_details_token")','view_token').replace('        """Render the extensible single-user management view."""','        """Render the extensible single-user management view."""\n        nonlocal view_token')
  body=body.replace(ast.get_source_segment(old_source,updates[0]),replacement)
 expected=ast.parse("def holder():\n"+body).body[0].body[0]
 assert dump(expected)==dump(functions(trees[meta['module']])[name]),name
 proof[name]='identical after explicit shell/read callbacks and per-client token ownership'
all_old_nodes={dump(n) for n in ast.walk(old)}
for file,module in [('editor-extraction.json','organization_editor'),('table-extraction.json','organization_table')]:
 for item in json.loads((r/file).read_text()):
  expected=ast.parse('def holder():\n'+textwrap.indent(textwrap.dedent(item['original']),'    ')).body[0].body
  actual=[n for n in functions(trees[module])[item['helper']].body if isinstance(n,ast.If)]
  if item['helper']=='organization_table_filters':
   source=textwrap.dedent(item['original']).replace('state.get("lifecycle_filter", "all")','get_lifecycle_filter()').replace('state.get("account_type_filter", "all")','get_account_type_filter()').replace('state["lifecycle_filter"] = "all"','reset_lifecycle_filter()')
   expected=ast.parse(source).body
  assert [dump(n) for n in expected]==[dump(n) for n in actual],item['helper']
  proof[item['helper']]='original conditional body retained'
render_old=functions(old)['render_table']
for item in json.loads((r/'list-actions-extraction.json').read_text()):
 original=next(n for n in ast.walk(render_old) if isinstance(n,ast.AsyncFunctionDef) and n.name==item['name'])
 assert dump(original)==dump(ast.parse(textwrap.dedent(item['original'])).body[0])
 assert dump(ast.parse(textwrap.dedent(item['extracted'])).body[0])==dump(functions(trees['organization_collection_actions'])[item['name']])
 proof['table_'+item['name']]='original workflow with explicit row/identity callbacks'
for name,module in {'filter_membership_rows':'organization_memberships','user_avatar':'identity_presentation','render_user_avatar':'identity_presentation','inactive_org_unit_source':'organization_editor','role_change_requires_reason':'organization_editor','deletion_identity':'organization_deletion','deletion_blocked_report':'organization_deletion'}.items():
 assert dump(functions(old)[name])==dump(functions(trees[module])[name]),name
 proof[name]='identical pure helper'
for original in a['decorate_for_spec'].body:
 if isinstance(original,ast.If) and ast.unparse(original.test) in {"spec.key == 'org-units'","spec.key == 'roles'","spec.key == 'users'"}:
  assert any(dump(original)==dump(n) for n in ast.walk(trees['organization_collections']))
proof['organization_hydration']='all three original bounded projection branches identical'
class RestoreCards(ast.NodeTransformer):
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name):
   if n.func.id=='get_rows':return ast.parse('state["rows"]').body[0].value
  return self.generic_visit(n)
 def visit_Name(self,n):
  if n.id=='pages':return ast.parse('state["collection_pages"]').body[0].value
  return n
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='reset_lifecycle_filter':return ast.parse('state["lifecycle_filter"] = "all"').body[0]
  return self.generic_visit(n)
card_old=next(n for n in ast.walk(render_old) if isinstance(n,ast.If) and ast.unparse(n.test)=="spec.key in {'security-levels', 'profiles', 'users', 'roles', 'org-units'}")
card_new=copy.deepcopy(functions(trees['administration_cards'])['render_administration_cards'])
card_new=RestoreCards().visit(card_new);card_new.body[-1]=ast.Return(value=None)
assert [dump(n) for n in card_old.body]==[dump(n) for n in card_new.body]
proof['shared_administration_cards']='entire original body identical after page/result accessors'
# Reconstruct the complete shared editor to verify placement and arguments,
# not only the bodies of the extracted helpers.
editor_replacements={}
old_lines=old_source.splitlines(True)
for item in json.loads((r/'editor-extraction.json').read_text()):
 replacement=ast.parse(textwrap.dedent(item['replacement'])).body[0]
 original=next(n for n in ast.walk(a['open_editor']) if isinstance(n,ast.If) and ''.join(old_lines[n.lineno-1:n.end_lineno])==item['original'])
 editor_replacements[dump(replacement)]=original
class RestoreEditor(ast.NodeTransformer):
 def visit(self,n):
  if dump(n) in editor_replacements:return copy.deepcopy(editor_replacements[dump(n)])
  return super().visit(n)
 def visit_Call(self,n):
  if isinstance(n.func,ast.Name) and n.func.id=='protected_organization_role':
   assert [ast.unparse(arg) for arg in n.args]==['spec.key','row']
   return ast.parse('spec.key == "roles" and row.get("is_system")').body[0].value
  if isinstance(n.func,ast.Name) and n.func.id=='read_organization_editor_row':
   assert [ast.unparse(arg) for arg in n.args]==['api','row']
   return ast.parse('api.get("org-units", row["id"])').body[0].value
  return self.generic_visit(n)
assert dump(a['open_editor'])==dump(RestoreEditor().visit(copy.deepcopy(b['open_editor'])))
proof['shared_editor']='complete original AST restored by inlining verified helpers'
changed=[name for name,n in a.items() if name not in b or dump(n)!=dump(b[name])]
expected=set(json.loads((r/'view-extraction.json').read_text()))|{'open_editor','render_table','decorate_for_spec'}
assert set(changed)==expected,changed
def literals(ts,methods):
 return collections.Counter((n.func.attr if isinstance(n.func,ast.Attribute) else n.func.id,argument.value) for t in ts for n in ast.walk(t) if isinstance(n,ast.Call) and ((isinstance(n.func,ast.Attribute) and n.func.attr in methods) or (isinstance(n.func,ast.Name) and n.func.id in methods)) for argument in n.args if isinstance(argument,ast.Constant) and isinstance(argument.value,str))
for methods in [{'classes','props','style','tooltip'},{'render_message','render_message_plain'}]:
 assert literals([old],methods)==literals([new,*trees.values()],methods),methods
def slots(ts):
 return collections.Counter((method,textwrap.dedent(value).strip()) for (method,value),count in literals(ts,{'add_slot'}).items() for _ in range(count))
assert slots([old])==slots([new,*trees.values()])
proof['table_slot_markup']='original markup preserved, allowing only common source indentation'
before=json.loads((r/'source-before.json').read_text());changed_runtime=[p for p,h in before.items() if '/tests/' not in p and Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed_runtime==['frontend/webui/app.py'],changed_runtime
result={'verified_boundaries':proof,'unchanged_direct_host_functions':len(a)-len(changed),'styling_and_message_literals_identical':True,'changed_existing_runtime_files':changed_runtime,'shared_state_dictionary_passed':False}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
