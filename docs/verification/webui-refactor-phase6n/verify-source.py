import ast,copy,json,hashlib,textwrap
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6n')
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in [*t.body,*index(t).body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
helper=json.loads((r/'helper-map.json').read_text())
class Restore(ast.NodeTransformer):
 def visit_Name(self,n):
  if n.id in ('record_state','collection_state'):n.id='state'
  return n
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='configure_record_medium':
   return ast.parse(textwrap.dedent(helper['hook']['original'])).body
  return self.generic_visit(n)
 def generic_visit(self,n):
  n=super().generic_visit(n)
  for field,value in ast.iter_fields(n):
   if isinstance(value,list):
    merged=[]
    def update(x):return isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and isinstance(x.value.func,ast.Attribute) and isinstance(x.value.func.value,ast.Name) and x.value.func.value.id=='state' and x.value.func.attr=='update'
    for item in value:
     if merged and update(item) and update(merged[-1]):merged[-1].value.keywords.extend(item.value.keywords)
     else:merged.append(item)
    for item in merged:
     if update(item):item.value.keywords.sort(key=lambda k:k.arg or '')
    setattr(n,field,merged)
  return n
def restored(n):return dump(Restore().visit(copy.deepcopy(n)))
before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text());a,b=funcs(before),funcs(after);checked=[]
for entry in json.loads((r/'extraction-map.json').read_text()):
 source=Path('frontend/webui',entry['module']+'.py').read_text()
 for old,new in reversed(entry['replacements']):source=source.replace(new,old)
 tree=ast.parse(source)
 for name in entry['functions']:
  node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
  assert restored(node)==restored(a[name]),name
  checked.append(name)
for entry in helper['moved']:
 expected=ast.parse(entry['original']).body[0]
 node=next(n for n in ast.parse(Path('frontend/webui',entry['module']+'.py').read_text()).body if (isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==entry['name']) or (isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id==entry['name']))
 assert dump(node)==dump(expected),entry['name']
 if entry['name'] in a:checked.append(entry['name'])
hook=next(n for n in ast.parse(Path('frontend/webui/record_editor.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name==helper['hook']['name'])
assert dump(ast.Module(body=hook.body,type_ignores=[]))==dump(ast.Module(body=ast.parse(textwrap.dedent(helper['hook']['original'])).body,type_ignores=[]))
others=[name for name in a if name not in checked]
for name in others:
 assert restored(a[name])==restored(b[name]),name
def initial(t):
 node=next(n for n in index(t).body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='state')
 return {key.value:dump(value) for key,value in zip(node.value.keys,node.value.values)}
combined=initial(after)
for owner in ('record_state','collection_state'):
 tree=ast.parse(Path('frontend/webui',owner+'.py').read_text());factory=next(n for n in tree.body if isinstance(n,ast.FunctionDef));value=factory.body[0].value
 combined.update({key.value:dump(item) for key,item in zip(value.keys,value.values)})
 assert any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==owner for t in n.targets) and isinstance(n.value,ast.Call) and n.value.func.id=='new_'+owner for n in index(after).body)
assert combined==initial(before),'initial state defaults'
manifest=json.loads((r/'source-before.json').read_text());changed=[p for p,h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'moved_functions_reconstructed':checked,'editor_blocks_reconstructed':[helper['hook']['name']],'other_functions_reconstructed':len(others),'existing_runtime_changes':changed,'state_change':'Record detail and shared bounded collection state have independent per-client owners; narrow callbacks preserve shared access order.','catalogue_and_inspector_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
