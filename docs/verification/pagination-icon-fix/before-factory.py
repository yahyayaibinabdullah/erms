import ast,importlib,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import pytest
class Baseline:
 def pytest_configure(self,config):
  for name in ['administration_cards','login_sessions','text_indexer_details']:
   owner=importlib.import_module('frontend.webui.'+name)
   source=Path('.runtime/pagination-icon-fix/before-'+name+'.py').read_text()
   node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='build_'+name)
   exec(compile(ast.Module(body=[node],type_ignores=[]),'<pre-fix-'+name+'>','exec'),vars(owner))
raise SystemExit(pytest.main(sys.argv[1:],plugins=[Baseline()]))
