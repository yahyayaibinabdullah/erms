import os,sys,subprocess
from pathlib import Path
r=Path('.runtime/dashboard-favourite-fix')
name=sys.argv[1];args=sys.argv[2:];output=r/name;output.mkdir(exist_ok=False)
env=dict(os.environ,DATABASE_URL='',MESSAGING_LISTENER_DATABASE_URL='',WEBUI_API_URL='http://127.0.0.1:1',PYTHON_DOTENV_DISABLED='1',NICEGUI_STORAGE_PATH=str(output.resolve()/'storage'),NICEGUI_REDIS_URL='',WEBUI_STORAGE_SECRET='disposable-webui-tests-only');env.pop('PYTEST_ADDOPTS',None)
with (output/'tests.log').open('w') as log:
 code=subprocess.call(['frontend/webui/.venv/bin/python','-m','pytest','-q','-p','tools.webui_no_network','-o','asyncio_mode=auto',f'--junitxml={output}/tests.xml',*args],env=env,stdout=log,stderr=subprocess.STDOUT)
print(name,code);raise SystemExit(code)
