import ast,copy,json,hashlib
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6q')
def index(t):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(t):return {n.name:n for n in [*t.body,*index(t).body] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='index'}
def dump(n):return ast.dump(n,include_attributes=False)
owners=[o['name'] for o in json.loads((r/'state-map.json').read_text())['owners']]
class Restore(ast.NodeTransformer):
 def visit_Name(self,n):
  if n.id in owners:n.id='state'
  return n
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
 source=Path('frontend/webui',entry['module']+'.py').read_text();tree=ast.parse(source)
 for name in entry['functions']:
  node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
  body=ast.get_source_segment(source,node)
  for old,new in reversed(entry['replacements']):
   if not new.isidentifier():body=body.replace(new,old)
  node=ast.parse(body).body[0]
  names={new:old for old,new in entry['replacements'] if new.isidentifier()}
  class Names(ast.NodeTransformer):
   def visit_Name(self,n):return ast.parse(names[n.id],mode='eval').body if n.id in names else n
  node=Names().visit(node)
  assert restored(node)==restored(a[name]),name;checked.append(name)
for name in a:
 if name not in checked:assert restored(a[name])==restored(b[name]),name
def initial(t):
 n=next(n for n in index(t).body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='state')
 return {k.value:dump(v) for k,v in zip(n.value.keys,n.value.values)}
combined=initial(after)
for owner in owners:
 tree=ast.parse(Path('frontend/webui',owner+'.py').read_text());factory=next(n for n in tree.body if isinstance(n,ast.FunctionDef));value=factory.body[0].value
 combined.update({k.value:dump(v) for k,v in zip(value.keys,value.values)})
 assert any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==owner for t in n.targets) and isinstance(n.value,ast.Call) and n.value.func.id=='new_'+owner for n in index(after).body)
assert combined==initial(before),'initial defaults'
manifest=json.loads((r/'source-before.json').read_text());changed=[p for p,h in manifest.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h];assert changed==['frontend/webui/app.py'],changed
result={'moved_functions_reconstructed':checked,'other_functions_reconstructed':len(a)-len(checked),'existing_runtime_changes':changed,'state_owners':owners,'catalogue_bytes_unchanged':True}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
