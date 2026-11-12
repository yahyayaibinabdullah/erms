"""Verify final saved-search regression evidence and source identity."""
from pathlib import Path
import hashlib,json,subprocess
import xml.etree.ElementTree as ET
p=Path('.runtime/saved-search-reopen-fix');start=json.loads((p/'start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
a={'status':'Saved-search reopening fixed and locally verified','date':'2026-11-12',
   'branch':start['branch'],'head':start['head'],'git_mutations':False,'tests':{},'browsers':{}}
for name,count in [('unit',63),('interaction',37)]:
 suites=list(ET.parse(p/name/'tests.xml').getroot().iter('testsuite'))
 assert all(all(int(s.get(k,'0'))==0 for k in ['errors','failures','skipped']) for s in suites)
 assert sum(int(s.get('tests')) for s in suites)==count
 a['tests'][name]=count
for name in ['chrome','edge']:
 d=p/name;r=json.loads((d/'browser-results.json').read_text());life=json.loads((d/'lifecycle.json').read_text())
 assert r['complete'] and life['test_exit_code']==0 and life['database_dropped']
 assert len(r['checks'])==9 and all(c['status']=='pass' for c in r['checks'])
 assert len(r['screenshots'])==22 and not r['browser_errors']
 cases=r['bare_condition_reopening'];assert len(cases)==4
 assert {(x['resource'],x['language']) for x in cases}=={(r,l) for r in ['records','aggregations'] for l in ['en','ar']}
 for case in cases:
  assert all(case[k] for k in ['stored_definition_unchanged_on_open','clean_navigation','saved_execution_matches_api','edited_value_retained'])
  assert case['after_version']>case['before_version']
 hashes=json.loads((d/'source-environment.json').read_text())['sha256']
 assert all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in hashes.items())
 for s in r['screenshots']:assert hashlib.sha256((d/s['file']).read_bytes()).hexdigest()==s['sha256']
 requests=[json.loads(x) for x in (d/'requests.jsonl').read_text().splitlines()]
 assert all(e['status'] is not None and e['status']<400 for e in requests)
 updates=[e for e in requests if e['method']=='PUT' and e['path'].startswith('/api/v1/saved-searches/')]
 assert len(updates)==4 and all(e['status']==200 for e in updates)
 a['browsers'][name]={'version':r['version'],'checks':9,'screenshots':22,
     'bare_condition_reopening':cases,'saved_updates':4,'source_files_matched':len(hashes),'unexpected_errors':0}
failures=list(ET.parse(p/'before-corrected/tests.xml').getroot().iter('failure'));assert len(failures)==16
cleanup=json.loads((p/'database-cleanup.json').read_text());assert not cleanup['remaining_databases']
proc=json.loads((p/'process-cleanup.json').read_text());assert not proc['test_path_processes'] and not proc['driver_processes']
a['disposable_databases_removed']=len(cleanup['runs'])
assert a['disposable_databases_removed']==3
assert all(v['exit_code']==0 for v in json.loads((p/'validation.json').read_text()))
for f,h in start['sha256'].items():
 if '/i18n/' in f:assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==h
a['catalogues_unchanged']=True
a['excluded_attempts']={'before':'Absence check used a finder that requires a dialog to exist; assertion corrected',
 'before-corrected':'16 expected standalone failures, 16 grouped passes; structured page exceptions also reported at teardown',
 'chrome-first-attempt':'English passed; timeout closing saved picker at first Arabic standalone query. Screen remained on picker; no browser or server exception. Cause unproven; retained separately.'}
a['test_source_sha256']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path('frontend/webui/interaction/tests/test_saved_search_reopening.py'),Path('tools/webui_browser_advanced_search.py')]}
(p/'acceptance.json').write_text(json.dumps(a,indent=2)+'\n')
print('Accepted: 100 focused tests; Chrome/Edge English/Arabic opening, execution, eight saved edits and reopening; cleanup verified.')
