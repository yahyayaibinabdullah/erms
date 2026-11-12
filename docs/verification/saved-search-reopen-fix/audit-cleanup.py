"""Read-only audit of this task's disposable DBs and test processes."""
import json
import os
import subprocess
from pathlib import Path
import psycopg
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
p = Path('.runtime/saved-search-reopen-fix')
runs = {f.parent.name: json.loads(f.read_text()) for f in p.glob('*/lifecycle.json')}
names = [v['database'] for v in runs.values()]
assert len(names) == len(set(names)) == 3
assert all(n.startswith('erms_webui_test_') for n in names)
assert all(v['database_dropped'] for v in runs.values())
config = {**dotenv_values('.env'), **os.environ}
with psycopg.connect(make_conninfo(config['DATABASE_URL'], dbname='postgres')) as conn:
    with conn.cursor() as cursor:
        cursor.execute('SELECT datname FROM pg_database WHERE datname = ANY(%s)', (names,))
        remaining = [r[0] for r in cursor.fetchall()]
(p/'database-cleanup.json').write_text(json.dumps({'runs': runs, 'remaining_databases': remaining,
    'audit': 'Independent read-only PostgreSQL catalogue query'}, indent=2)+'\n')
assert not remaining
processes = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True).splitlines()
owned = [line for line in processes if '.runtime/saved-search-reopen-fix/' in line
         and 'audit-cleanup.py' not in line]
drivers = [line for line in processes if 'chromedriver' in line or 'msedgedriver' in line]
(p/'process-cleanup.json').write_text(json.dumps({'test_path_processes': owned,
    'driver_processes': drivers, 'action': 'Read-only audit; no processes stopped'}, indent=2)+'\n')
assert not owned and not drivers
print('All three test databases removed; no owned test processes or native drivers remain.')
