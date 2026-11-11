import ast,json
from pathlib import Path
baseline=json.loads(Path('docs/verification/webui-refactor-phase1/source-inventory.json').read_text())
functions={};calls=[]
class Walk(ast.NodeVisitor):
 def __init__(self,path):self.path=str(path);self.owner=[]
 def visit_FunctionDef(self,n):
  self.owner.append(n.name);functions.setdefault(n.name,[]).append({'file':self.path,'owner':'.'.join(self.owner),'line':n.lineno});self.generic_visit(n);self.owner.pop()
 visit_AsyncFunctionDef=visit_FunctionDef
 def visit_ClassDef(self,n):self.owner.append(n.name);self.generic_visit(n);self.owner.pop()
 def visit_Call(self,n):
  if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='ui' and n.func.attr=='dialog':calls.append({'file':self.path,'line':n.lineno,'owner':'.'.join(self.owner)})
  self.generic_visit(n)
for p in Path('frontend/webui').rglob('*.py'):
 if any(x in p.parts for x in ('.venv','tests','interaction','assembled')):continue
 Walk(p).visit(ast.parse(p.read_text()))
missing=sorted({x['name'] for x in baseline['index_closures'] if x['name'] not in ('lambda','listcomp','dictcomp') and x['name'] not in functions})
print('Missing original named closures:',missing)
for x in baseline['dialog_callsites']:
 suffix=x['owner'].removeprefix('index.');candidates=[c for c in calls if c['owner'].endswith(suffix) and (x['file'].endswith('/app.py') or c['file']==x['file'])]
 if not candidates:print('Dialog owner needs explicit mapping:',x['owner'],x['file'])
Path('.runtime/webui-refactor-phase7/current-functions.json').write_text(json.dumps(functions,indent=2)+'\n')
Path('.runtime/webui-refactor-phase7/current-dialogs.json').write_text(json.dumps(calls,indent=2)+'\n')
