import ast,json
from pathlib import Path
from nicegui import Client,ui
from frontend.webui import app as host
r=Path('.runtime/webui-refactor-phase6r');observations=[]
for label,path in [('original',r/'app-before.py'),('extracted',Path('frontend/webui/advanced_search.py'))]:
 tree=ast.parse(path.read_text());node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='render_group');scope=dict(vars(host))
 exec(compile(ast.Module(body=[node],type_ignores=[]),'<existing-leaf-observation>','exec'),scope)
 client=Client(ui.page('/leaf-observation-'+label),request=None)
 try:
  with client:
   try:scope['render_group']({'type':'condition','kind':'structured','field':'title','operator':'contains_ci','value':'Test'})
   except ValueError as error:
    assert str(error)=='Invalid value: contains_ci';observations.append({'implementation':label,'exception':type(error).__name__,'message':str(error)})
   else:raise AssertionError('Existing behavior changed')
 finally:client.delete()
(r/'bare-leaf-observation.json').write_text(json.dumps({'preserved':True,'runtime_fix':False,'observations':observations,'scope':'Synthetic saved definition with a bare condition. Normal UI-produced definitions have an outer Boolean group. Record for later product review; no refactor behavior change.'},indent=2)+'\n')
print('Original and extracted bare-condition behavior match.')
