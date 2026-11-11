"""Check runner ownership and independently confirm disposable databases are absent."""
import json
from pathlib import Path
import psycopg
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
root=Path('.runtime/webui-refactor-phase8');runs=[]
for path in sorted(root.glob('*/lifecycle.json')):
 data=json.loads(path.read_text());assert data['database'].startswith(('erms_webui_test_','erms_messaging_test_acl_'))
 assert data['database_dropped'],path
 runs.append({'run':path.parent.name,'database':data['database'],'database_dropped':True,'test_exit_code':data.get('test_exit_code'),'interrupted':data.get('interrupted',False),'recovered_cleanup':data.get('recovered_cleanup',False)})
names=[r['database'] for r in runs];assert len(set(names))==len(names)
with psycopg.connect(make_conninfo(dotenv_values('.env')['DATABASE_URL'],dbname='postgres')) as conn:
 remaining=[r[0] for r in conn.execute('SELECT datname FROM pg_database WHERE datname = ANY(%s)',(names,))]
assert not remaining,remaining
result={'created_runs':len(runs),'unique_names':True,'all_cleanup_confirmed':True,'independent_catalogue_audit':True,'remaining_databases':remaining,'runs':runs}
(root/'database-cleanup.json').write_text(json.dumps(result,indent=2)+'\n')
print(f'All {len(runs)} uniquely named disposable databases were removed; independent catalogue audit passed.')
