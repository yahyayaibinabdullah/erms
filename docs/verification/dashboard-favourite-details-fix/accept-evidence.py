"""Validate focused tests, native evidence, source identity and cleanup."""
from pathlib import Path
import hashlib,json,subprocess
import xml.etree.ElementTree as ET
p=Path('.runtime/dashboard-favourite-details-fix');start=json.loads((p/'start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
a={'status':'Favourite identity labels and persistent View all fixed and locally verified','date':'2026-11-12',
   'branch':start['branch'],'head':start['head'],'git_mutations':False,'tests':{},'browsers':{}}
for name,count in [('unit',28),('interaction',36)]:
 suites=list(ET.parse(p/name/'tests.xml').getroot().iter('testsuite'))
 assert all(all(int(s.get(k,'0'))==0 for k in ['errors','failures','skipped']) for s in suites)
 assert sum(int(s.get('tests')) for s in suites)==count
 a['tests'][name]=count
for name in ['chrome','edge']:
 d=p/name;r=json.loads((d/'browser-results.json').read_text());life=json.loads((d/'lifecycle.json').read_text())
 assert r['complete'] and life['test_exit_code']==0 and life['database_dropped']
 assert len(r['checks'])==9 and all(c['status']=='pass' for c in r['checks'])
 assert len(r['screenshots'])==16 and not r['browser_errors']
 cases=r['favourite_removal'];assert len(cases)==8
 assert {(x['resource'],x['language'],x['surface']) for x in cases}=={(r,l,s) for r in ['records','aggregations'] for l in ['en','ar'] for s in ['dashboard','dialog']}
 assert all(x['localized_notification'] and x['single_delete'] and x['persisted'] and x['correct_identity'] for x in cases)
 assert all(x['dialog_stayed_open'] for x in cases if x['surface']=='dialog')
 hashes=json.loads((d/'source-environment.json').read_text())['sha256']
 assert all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in hashes.items())
 for s in r['screenshots']:assert hashlib.sha256((d/s['file']).read_bytes()).hexdigest()==s['sha256']
 requests=[json.loads(x) for x in (d/'requests.jsonl').read_text().splitlines()]
 assert all(e['status'] is not None and e['status']<400 for e in requests)
 deletes=[e for e in requests if e['method']=='DELETE' and e['path'].startswith('/api/v1/favourites/')]
 assert len(deletes)==12 and all(e['status']<300 for e in deletes)
 server=(d/'webui.log').read_text()
 assert 'Traceback' not in server and 'The parent element this slot belongs to has been deleted' not in server
 a['browsers'][name]={'version':r['version'],'checks':9,'screenshots':16,
     'favourite_removal':cases,'successful_deletes':12,'ui_deletes':10,'fixture_api_deletes':2,
     'source_files_matched':len(hashes),'unexpected_errors':0}
failures=list(ET.parse(p/'before/tests.xml').getroot().iter('failure'));assert len(failures)==20
assert all('AssertionError' in f.get('message','') or 'assert' in f.get('message','') for f in failures)
cleanup=json.loads((p/'database-cleanup.json').read_text());assert not cleanup['remaining_databases']
proc=json.loads((p/'process-cleanup.json').read_text());assert not proc['test_path_processes'] and not proc['driver_processes']
a['disposable_databases_removed']=len(cleanup['runs']);assert a['disposable_databases_removed']==4
assert all(v['exit_code']==0 for v in json.loads((p/'validation.json').read_text()))
for f,h in start['sha256'].items():
 if '/i18n/' in f:assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==h
a['catalogues_unchanged']=True
a['excluded_attempts']={'before':'20 expected failures: incorrect record identity or deleted dialog',
 'interaction-edit-attempt':'Initial label edit matched an unrelated occurrence; restored it and corrected favourite renderer',
 'native-interrupted':'Stopped both initial browser runs after focused tests identified incorrect edit location; databases cleaned up'}
a['test_source_sha256']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path('frontend/webui/interaction/tests/test_dashboard_favourites.py'),Path('tools/webui_browser_dashboard.py')]}
(p/'acceptance.json').write_text(json.dumps(a,indent=2)+'\n')
print('Accepted: 64 focused tests; Chrome/Edge English/Arabic, dashboard/dialog, records/aggregations; cleanup verified.')
