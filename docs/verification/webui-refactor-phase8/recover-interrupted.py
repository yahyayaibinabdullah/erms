import json,re
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
root=Path('.runtime/webui-refactor-phase8')
with psycopg.connect(make_conninfo(dotenv_values('.env')['DATABASE_URL'],dbname='postgres'),autocommit=True) as conn:
 for folder in ('session-chrome',):
  path=root/folder/'lifecycle.json';data=json.loads(path.read_text());name=data['database']
  assert re.fullmatch('erms_webui_test_[a-f0-9]{32}',name)
  exists=bool(conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone())
  if exists:conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
  assert not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone()
  (path.parent/'interruption-cleanup.json').write_text(json.dumps({'original_lifecycle':data,'database_existed':exists,'database_removed':True,'reason':'Execution interrupted; owned service/driver processes independently confirmed absent before recovery.'},indent=2)+'\n')
  data.update(database_dropped=True,interrupted=True,recovered_cleanup=True)
  path.write_text(json.dumps(data,indent=2)+'\n');print(folder,'cleanup confirmed')
