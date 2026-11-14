import ast,copy,hashlib,json
from pathlib import Path
root=Path.cwd();runtime=root/'.runtime/webui-refactor-phase6c'
before=ast.parse((runtime/'app-before.py').read_text());after=ast.parse((root/'frontend/webui/app.py').read_text())
modules=['entity_selectors','entity_editor_controls','resource_number_controls','collection_hydration','personal_resources','personal_resource_views','compact_resource_view','collection_controls','entity_translation_editor']
parsed={m:ast.parse((root/f'frontend/webui/{m}.py').read_text()) for m in modules}
keys={'favourites','favourite_ids','recent_created','recent_updated','recent_activity','personal_sections_loading','personal_section_hosts'}
class Normalize(ast.NodeTransformer):
 def visit_Subscript(self,n):
  n=self.generic_visit(n)
  if isinstance(n.value,ast.Name) and n.value.id=='state' and isinstance(n.slice,ast.Constant):
   if n.slice.value in keys:return ast.Attribute(value=ast.Name(id='personal',ctx=ast.Load()),attr=n.slice.value,ctx=n.ctx)
   if n.slice.value=='application_configuration':return ast.Call(func=ast.Name(id='get_configuration',ctx=ast.Load()),args=[],keywords=[])
  return n
 def visit_Call(self,n):
  n=self.generic_visit(n)
  if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.attr=='get' and n.args and isinstance(n.args[0],ast.Constant):
   name=n.func.value.id;key=n.args[0].value
   if name=='state' and key in keys:return ast.Attribute(value=ast.Name(id='personal',ctx=ast.Load()),attr=key,ctx=ast.Load())
   if (name,key) in [('auth_state','principal'),('state','resource')]:return ast.Call(func=ast.Name(id='get_principal' if key=='principal' else 'get_resource',ctx=ast.Load()),args=[],keywords=[])
  return n

def normalized(n):return ast.dump(Normalize().visit(copy.deepcopy(n)),include_attributes=False)
def functions(tree):return {n.name:n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
old=functions(before);new=functions(after)
for tree in parsed.values():new.update(functions(tree))
moved=['relationship_options','relationship_search_query','apply_relationship_selection','entity_metadata_label','medium_options','field_input','form_payload','bind_remote_relationship_select','rows_by_id','closure_flags','org_unit_context','add_number_suggestion','show_number_conflict','reload_favourites','favourite_state','apply_favourite_button','toggle_favourite','favourite_button','load_recent','render_recent_section','render_entity_favourites_section','render_resource_personal_sections','render_compact_resource_result','reload_governance_cards','move_card_page']
proof={name:normalized(old[name])==normalized(new[name]) for name in moved}
assert all(proof.values()),proof
oldindex=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='index')
newindex=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='index')
directold={n.name:n for n in oldindex.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
directnew={n.name:n for n in newindex.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
changed={name for name in directold.keys()&directnew.keys() if normalized(directold[name])!=normalized(directnew[name])}
assert changed=={'open_editor','render_table','decorate_for_spec'},changed
# Feature decoration below the three extracted lookup functions is unchanged.
a=copy.deepcopy(old['decorate_for_spec']);b=copy.deepcopy(new['decorate_for_spec'])
a.body=a.body[3:];b.body=b.body[3:];assert normalized(a)==normalized(b)
# Catalogue calls and UI styling literals are unchanged across the complete move.
def calls(t,method):
 return sorted(ast.literal_eval(n.args[0]) for n in ast.walk(t) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr==method and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str))
# Methods also occur in unrelated stdlib calls; moving adds no such literals.
for method in ('classes','props','style','tooltip'):
 a=calls(before,method);b=sorted(calls(after,method)+[x for t in parsed.values() for x in calls(t,method)])
 assert a==b,method
hashes=json.loads((runtime/'source-before.json').read_text())
print(type(hashes).__name__)
# source-before.json schema is retained without guessing.
result={'normalized_identical_moved_functions':proof,'unchanged_direct_host_functions':len(directold.keys()&directnew.keys())-len(changed),'changed_host_functions':sorted(changed),'decoration_feature_branches_identical':True,'styling_literal_multisets_identical':True}
(runtime/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
class TranslationNormalize(ast.NodeTransformer):
 def visit_Compare(self,n):
  if ast.unparse(n)=='spec.key == \'profiles\'':return ast.Name(id='uses_external_reason',ctx=ast.Load())
  return self.generic_visit(n)
 def visit_Attribute(self,n):
  if ast.unparse(n)=='spec.key':return ast.Name(id='resource',ctx=ast.Load())
  return self.generic_visit(n)
 def visit_Subscript(self,n):
  if ast.unparse(n)=='multilingual_fields[spec.key]':return ast.Name(id='fields',ctx=ast.Load())
  return self.generic_visit(n)
 def visit_Name(self,n):
  if n.id=='profile_change_reason':return ast.Call(func=ast.Name(id='get_external_reason',ctx=ast.Load()),args=[],keywords=[])
  return n
 def visit_Call(self,n):
  if ast.unparse(n)=="bootstrap.get('supported_languages', [])":return ast.Name(id='languages',ctx=ast.Load())
  return self.generic_visit(n)
 def visit_Assign(self,n):
  if any(isinstance(x,ast.Name) and x.id=='prepare_entity_translation_update' for x in n.targets):return None
  return self.generic_visit(n)
condition=next(n for n in ast.walk(old['open_editor']) if isinstance(n,ast.If) and ast.unparse(n.test)=='not creating and spec.key in multilingual_fields and translation_edit_allowed')
a=TranslationNormalize().visit(ast.Module(body=copy.deepcopy(condition.body[1:]),type_ignores=[]))
b=ast.Module(body=new['entity_translation_editor'].body[:-1],type_ignores=[])
result['translation_editor_body_identical_after_explicit_parameters']=ast.dump(a)==ast.dump(b)
assert result['translation_editor_body_identical_after_explicit_parameters']
# Runtime files from before this step, including 6A/6B and every catalogue byte.
changed_existing=[path for path,digest in hashes.items() if 'tests' not in Path(path).parts and hashlib.sha256((root/path).read_bytes()).hexdigest()!=digest]
assert changed_existing==['frontend/webui/app.py'],changed_existing
result['changed_existing_runtime_files']=changed_existing
result['all_other_existing_runtime_files_and_catalogues_byte_identical']=True
(runtime/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n')
