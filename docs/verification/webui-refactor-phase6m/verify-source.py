import ast,copy,json,hashlib,textwrap
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6m');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in [*t.body,*index(t).body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
hooks={h['name']:h for h in json.loads((r/'editor-hook-map.json').read_text())}
class Restore(ast.NodeTransformer):
 def visit_Name(self,n):
  if n.id=='aggregation_state':n.id='state'
  return n
 def visit_Call(self,n):
  expressions={'principal':'auth_state.get("principal")','get_resource':'state.get("resource")','get_record_detail_id':'state.get("record_detail_id")','get_relationship_page_token':'state.get("relationship_page_token")'}
  if isinstance(n.func,ast.Name) and n.func.id in expressions:return ast.parse(expressions[n.func.id],mode='eval').body
  n=self.generic_visit(n)
  if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='state' and n.func.attr=='update':n.keywords.sort(key=lambda k:k.arg or '')
  return n
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name):
   name=n.value.func.id
   if name in hooks:return ast.parse(textwrap.dedent(hooks[name]['original'])).body
   if name=='enter_details':return ast.parse('state["resource"] = "aggregation-details"').body[0]
   if name=='set_relationship_page_token':return ast.Assign(targets=[ast.Subscript(value=ast.Name(id='state',ctx=ast.Load()),slice=ast.Constant('relationship_page_token'),ctx=ast.Store())],value=n.value.args[0])
  return self.generic_visit(n)
 def visit_Assign(self,n):
  value=n.value.value if isinstance(n.value,ast.Await) else n.value
  if isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and value.func.id in hooks:return ast.parse(textwrap.dedent(hooks[value.func.id]['original'])).body
  return self.generic_visit(n)
 def visit_If(self,n):
  if len(n.body)==1 and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Call) and isinstance(n.body[0].value.func,ast.Name) and n.body[0].value.func.id=='prepare_aggregation_payload':return ast.parse(textwrap.dedent(hooks['prepare_aggregation_payload']['original'])).body
  return self.generic_visit(n)
 def generic_visit(self,n):
  n=super().generic_visit(n)
  for field,value in ast.iter_fields(n):
   if isinstance(value,list):
    merged=[]
    for item in value:
     def update(x):return isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and isinstance(x.value.func,ast.Attribute) and isinstance(x.value.func.value,ast.Name) and x.value.func.value.id=='state' and x.value.func.attr=='update'
     if merged and update(item) and update(merged[-1]) and len(item.value.keywords)==1 and item.value.keywords[0].arg=='aggregation_detail':
      assert isinstance(item.value.keywords[0].value,ast.Constant) and item.value.keywords[0].value.value is None
      merged[-1].value.keywords.extend(item.value.keywords);merged[-1].value.keywords.sort(key=lambda k:k.arg or '')
     else:merged.append(item)
    setattr(n,field,merged)
  return n
def restored(n):return dump(Restore().visit(copy.deepcopy(n)))
a,b=funcs(before),funcs(after);checked=[]
for module in ['aggregation_actions','aggregation_selector','aggregation_details','aggregation_browser','aggregation_toolbar','aggregation_presentation','relationship_select_styles']:
 for n in ast.walk(ast.parse(Path('frontend/webui',module+'.py').read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in a:
   assert restored(n)==restored(a[n.name]),n.name;checked.append(n.name)
for n in ast.parse(Path('frontend/webui/aggregation_editor.py').read_text()).body:
 if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
  h=hooks[n.name];expected=ast.parse(h['helper_body']).body
  if h['returns']:expected+=ast.parse('return '+h['returns']).body
  assert dump(ast.Module(body=n.body,type_ignores=[]))==dump(ast.Module(body=expected,type_ignores=[])),n.name
others=[name for name in a if name not in checked]
for name in others:
 assert restored(a[name])==restored(b[name]),name
manifest=json.loads((r/'source-before.json').read_text());changed=[p for p,h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'moved_functions_reconstructed':checked,'editor_blocks_reconstructed':list(hooks),'other_functions_reconstructed':len(others),'existing_runtime_changes':changed,'state_change':'Seven aggregation-only keys now have their own per-client owner; narrow shared page/token callbacks preserve access order.','catalogue_and_inspector_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
