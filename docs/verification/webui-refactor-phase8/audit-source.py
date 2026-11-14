"""Verify cleanup changes only the explicitly reviewed imports, dead bindings and identity adapter."""
import ast,hashlib,json
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');before=ast.parse((r/'app-before.py').read_text());after=ast.parse(Path('frontend/webui/app.py').read_text())
removed=json.loads((r/'import-cleanup.json').read_text())['removed']
class ReviewedCleanup(ast.NodeTransformer):
 def visit_Import(self,node):
  node.names=[a for a in node.names if (a.asname or a.name.split('.')[0]) not in removed]
  return node if node.names else None
 def visit_ImportFrom(self,node):
  if node.module=='__future__':return node
  return self.visit_Import(node)
 def visit_Assign(self,node):
  if any(isinstance(t,ast.Name) and t.id in {'auth_state','CLASSIFICATION_WORKSPACE_SEARCH_FIELDS','entity_types','render_entity_favourites_section'} for t in node.targets):return None
  return self.generic_visit(node)
 def visit_FunctionDef(self,node):
  return None if node.name=='favourite_preview' else self.generic_visit(node)
 def visit_Subscript(self,node):
  if isinstance(node.value,ast.Name) and node.value.id=='auth_state':
   assert isinstance(node.slice,ast.Constant) and node.slice.value=='principal'
   return ast.Attribute(value=ast.Name(id='session',ctx=ast.Load()),attr='principal',ctx=node.ctx)
  return self.generic_visit(node)
 def visit_Call(self,node):
  if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='auth_state':
   assert node.args[0].value=='principal'
   if node.func.attr=='get':return ast.Attribute(value=ast.Name(id='session',ctx=ast.Load()),attr='principal',ctx=ast.Load())
   assert node.func.attr=='__setitem__'
   return ast.Call(func=ast.Attribute(value=ast.Name(id='session',ctx=ast.Load()),attr='set_principal',ctx=ast.Load()),args=node.args[1:],keywords=[])
  return self.generic_visit(node)
 def visit_Lambda(self,node):
  node=self.generic_visit(node)
  if isinstance(node.body,ast.Call) and ast.unparse(node.body.func)=='session.set_principal':
   assert len(node.args.args)==1 and ast.unparse(node.body.args[0])==node.args.args[0].arg
   return node.body.func
  return node
normalized=ReviewedCleanup().visit(before)
assert ast.dump(normalized,include_attributes=False)==ast.dump(after,include_attributes=False),'Unexpected executable root change'
def presentation_literals(tree):
 return [ast.literal_eval(n.args[0]) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'add_css','add_head_html'}]
old=ast.parse((r/'app-before.py').read_text());assert presentation_literals(old)==presentation_literals(after)
files=json.loads((r/'runtime-before.json').read_text());changed=[p for p,h in files.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
assert changed==['frontend/webui/app.py','frontend/webui/session_context.py'],changed
keys=lambda t:sorted(n.value for n in ast.walk(t) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith(('webui.','navigation.','dashboard.','entity_metadata.')))
assert keys(old)==keys(after)
result={'only_reviewed_root_transformations':True,'removed_unused_imports':len(removed),'removed_dead_bindings':['CLASSIFICATION_WORKSPACE_SEARCH_FIELDS (owner: classification_workspace.py)','entity_types (audit owner has its own mapping)','render_entity_favourites_section (unused root alias)','favourite_preview (no runtime caller; rendered preview coverage replaces its test)'],'identity':'Replace one-key session.identity mapping with per-page principal; preserve all reads, writes and callback ordering.','unchanged_css_and_head_html':True,'unchanged_root_message_keys':True,'changed_runtime_files':changed,'other_runtime_files_preserved':len(files)-len(changed),'current_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files}}
(r/'source-audit.json').write_text(json.dumps(result,indent=2)+'\n');print({k:v for k,v in result.items() if k!='current_hashes'})
