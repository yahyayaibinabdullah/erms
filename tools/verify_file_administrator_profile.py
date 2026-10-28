"""Verify FILE_ADMIN provisioning only in a newly created disposable database.

Run from the project root with the API virtualenv Python. Reads the local
connection configuration to create a unique test database; never mutates demo.
"""
import os,uuid
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.initialize_database import initialize


url={**dotenv_values('.env'),**os.environ}['DATABASE_URL'];name='erms_test_file_admin_'+uuid.uuid4().hex
admin=psycopg.connect(make_conninfo(url,dbname='postgres'),autocommit=True)
admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
print('Created',name,flush=True)
try:
 with psycopg.connect(make_conninfo(url,dbname=name),autocommit=True) as c:
  initialize(c)
  row=c.execute("SELECT id,is_system FROM profiles WHERE code='FILE_ADMIN'").fetchone();assert row and row[1]
  codes=c.execute('SELECT v.code FROM privileges v JOIN profile_privileges pp ON pp.privilege_id=v.id WHERE pp.profile_id=%s ORDER BY v.code',(row[0],)).fetchall();assert len(codes)==34
  assert not c.execute('SELECT 1 FROM privilege_dependencies d JOIN profile_privileges p ON p.privilege_id=d.privilege_id WHERE p.profile_id=%s AND NOT EXISTS(SELECT 1 FROM profile_privileges r WHERE r.profile_id=p.profile_id AND r.privilege_id=d.required_privilege_id)',(row[0],)).fetchall()
  assert c.execute("SELECT translations#>>'{ar,name}' FROM profiles WHERE code='FILE_ADMIN'").fetchone()[0]=='مسؤول الملفات'
  migration=Path('database/migrations/073_file_administrator_profile.sql').read_text()
  c.execute(migration,prepare=False)
  c.execute("SELECT set_config('app.change_reason','Verify translation preservation',false)")
  c.execute("INSERT INTO supported_languages(language_tag,english_name,native_name,direction) VALUES('fr','French','Français','ltr')")
  c.execute("UPDATE profiles SET is_system=false,translations=jsonb_build_object('ar',jsonb_build_object('description','وصف'),'fr',jsonb_build_object('name','Responsable')) WHERE code='FILE_ADMIN'")
  c.execute(migration,prepare=False)
  assert c.execute("SELECT id,is_system FROM profiles WHERE code='FILE_ADMIN'").fetchone()==row
  assert c.execute("SELECT translations#>>'{ar,name}',translations#>>'{ar,description}',translations#>>'{fr,name}' FROM profiles WHERE code='FILE_ADMIN'").fetchone()==('مسؤول الملفات','وصف','Responsable')
  c.execute("UPDATE profiles SET translations=jsonb_set(translations,'{ar,name}','\"اسم مخصص\"'::jsonb) WHERE code='FILE_ADMIN'")
  c.execute(migration,prepare=False)
  assert c.execute("SELECT translations#>>'{ar,name}' FROM profiles WHERE code='FILE_ADMIN'").fetchone()[0]=='اسم مخصص'

  c.execute('DELETE FROM profile_privileges WHERE profile_id=%s AND privilege_id=(SELECT id FROM privileges WHERE code=%s)',(row[0],'security.resource.downgrade'))
  try:c.execute(migration,prepare=False)
  except psycopg.errors.RaiseException:c.execute('ROLLBACK')
  else:raise AssertionError('Conflict accepted')
  assert c.execute('SELECT count(*) FROM profile_privileges WHERE profile_id=%s',(row[0],)).fetchone()[0]==33
  c.execute('DELETE FROM profiles WHERE id=%s',(row[0],))
  c.execute(migration,prepare=False)
  assert c.execute("SELECT count(*) FROM profile_privileges pp JOIN profiles p ON p.id=pp.profile_id WHERE p.code='FILE_ADMIN'").fetchone()[0]==34
  print('PASS: canonical provisioning, dependencies, repeat migration, promotion, conflict rollback, absent-profile upgrade',flush=True)
finally:
 admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)));admin.close();print('Dropped',name,flush=True)
