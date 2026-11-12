import ast,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import pytest
class Baseline:
 def pytest_configure(self,config):
  from frontend.webui import dashboard
  source=Path('.runtime/dashboard-favourite-fix/before-dashboard.py').read_text()
  node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='build_dashboard')
  exec(compile(ast.Module(body=[node],type_ignores=[]),'<pre-fix-dashboard>','exec'),vars(dashboard))
raise SystemExit(pytest.main(sys.argv[1:],plugins=[Baseline()]))
