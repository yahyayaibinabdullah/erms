import ast,json,hashlib,collections
from pathlib import Path
r=Path('.runtime/webui-refactor-phase6h');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
def index(tree):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='index')
def funcs(tree):return {n.name:n for n in index(tree).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b=funcs(before),funcs(after)
def dump(node):return ast.dump(node,include_attributes=False)
checked=[]
for name,file,resource in [('reveal_text_indexer_key','text_indexer_credentials',None),('select_text_indexers','text_indexers','text-indexers'),('select_text_indexer_details','text_indexer_details','text-indexer-details')]:
 tree=ast.parse(Path(f'frontend/webui/{file}.py').read_text());node=next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
 class Restore(ast.NodeTransformer):
  def visit_Expr(self,n):
   if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='enter':
    return ast.parse(f'state.update(resource={resource!r}, rows=[], searched=True, aggregation_detail=None)').body[0]
   return self.generic_visit(n)
  def visit_Call(self,n):
   if isinstance(n.func,ast.Name) and n.func.id=='direction':return ast.parse('current_direction["value"]',mode='eval').body
   return self.generic_visit(n)
 assert dump(Restore().visit(node))==dump(a[name]),name
 checked.append(name)
unchanged=[name for name in a if name not in checked]
assert all(dump(a[name])==dump(b[name]) for name in unchanged)
old=json.loads((r/'source-before.json').read_text());changed=[p for p,h in old.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed==['frontend/webui/app.py'],changed
artifacts=[p for p in old if '/i18n/' in p]
result={'moved_functions_reconstructed':checked,'other_host_functions_identical':len(unchanged),'existing_runtime_files_changed':changed,'translation_artifacts_byte_identical':artifacts,'whole_state_passed':False,'new_routes_or_cache':False}
(r/'source-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
