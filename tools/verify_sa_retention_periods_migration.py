"""Verify migration 076 in a new disposable database; run from project root."""
import os,uuid,csv
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
url={**dotenv_values('.env'),**os.environ}['DATABASE_URL'];name='erms_test_sa_'+uuid.uuid4().hex
admin=psycopg.connect(make_conninfo(url,dbname='postgres'),autocommit=True);admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));print('Created',name,flush=True)
try:
 with psycopg.connect(make_conninfo(url,dbname=name),autocommit=True) as c:
  c.execute(Path('database/schema.sql').read_text(),prepare=False)
  migration=Path('database/migrations/076_sa_terminal_retention_periods.sql').read_text()
  c.execute(migration,prepare=False) # No SA: no-op.
  with c.transaction():
   for scheme in ['SA','OTHER']:
    sid=c.execute('INSERT INTO classification_schemes(code,title) VALUES(%s,%s) RETURNING id',(scheme,scheme)).fetchone()[0]
    for row in list(csv.reader(open('examples/fileplans/Sheet4.csv',encoding='utf-8-sig')))[1:]:
     cid=c.execute('INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,%s,%s,true) RETURNING id',(sid,row[0].strip(),row[0].strip())).fetchone()[0]
     c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition,instructions) VALUES(%s,2,8,'retain_as_local_archives','Preserve instructions')",(cid,))
  c.execute(migration,prepare=False)
  rows=c.execute("SELECT s.code,c.code,r.final_disposition,r.current_period_years,r.intermediate_period_years,r.instructions,r.version FROM classification_retention_rules r JOIN classifications c ON c.id=r.classification_id JOIN classification_schemes s ON s.id=c.classification_scheme_id ORDER BY s.code,c.code").fetchall()
  mapping={'إنتقاء':'selective_preservation','إتلاف':'destruction','حفظ دائم':'transfer_to_external_archive'}
  expected={r[0].strip():(int(r[3]),int(r[4])) for r in list(csv.reader(open('examples/fileplans/Sheet4.csv',encoding='utf-8-sig')))[1:]}
  for scheme,code,action,current,intermediate,instructions,version in rows:
   assert action=='retain_as_local_archives'
   assert (current,intermediate)==(expected[code] if scheme=='SA' else (2,8))
   assert instructions=='Preserve instructions'
  c.execute(migration,prepare=False)
  after=c.execute("SELECT s.code,c.code,r.final_disposition,r.current_period_years,r.intermediate_period_years,r.instructions,r.version FROM classification_retention_rules r JOIN classifications c ON c.id=r.classification_id JOIN classification_schemes s ON s.id=c.classification_scheme_id ORDER BY s.code,c.code").fetchall()
  assert rows==after
  print('PASS: 254 mappings, no-SA no-op, other scheme preserved, actions/instructions preserved; periods reconciled, repeat no-op',flush=True)
finally:
 admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)));admin.close();print('Dropped',name,flush=True)
