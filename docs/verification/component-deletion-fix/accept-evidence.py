"""Verify local deletion-fix evidence and source identity before archiving."""
from pathlib import Path
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
p=Path('.runtime/component-deletion-fix')
start=json.loads((p/'start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
a={'status':'Component deletion notification and refresh fixed and locally verified',
   'date':'2026-11-11','branch':start['branch'],'head':start['head'],
   'git_mutations':False,'tests':{},'browsers':{}}
for name,count in [('unit',170),('interaction',27)]:
 suites=list(ET.parse(p/name/'tests.xml').getroot().iter('testsuite'))
 assert all(all(int(s.get(k,'0'))==0 for k in ['errors','failures','skipped']) for s in suites)
 assert sum(int(s.get('tests')) for s in suites)==count
 a['tests'][name]=count
for name in ['chrome','edge-final']:
 d=p/name;r=json.loads((d/'browser-results.json').read_text());life=json.loads((d/'lifecycle.json').read_text())
 assert r['complete'] and life['test_exit_code']==0 and life['database_dropped']
 assert len(r['checks'])==7 and all(c['status']=='pass' for c in r['checks'])
 assert len(r['screenshots'])==16 and not r['browser_errors']
 recovery=r['deletion_refresh']
 assert len(recovery)==2 and {x['language'] for x in recovery}=={'en','ar'}
 assert all(all(v is True for k,v in x.items() if k!='language') for x in recovery)
 hashes=json.loads((d/'source-environment.json').read_text())['sha256']
 assert all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in hashes.items())
 for s in r['screenshots']: assert hashlib.sha256((d/s['file']).read_bytes()).hexdigest()==s['sha256']
 requests=[json.loads(x) for x in (d/'requests.jsonl').read_text().splitlines()]
 assert all(e['status'] is not None and e['status']<400 for e in requests)
 deletes=[e for e in requests if e['method']=='DELETE' and e['path'].startswith('/api/v1/digital-components/')]
 assert len(deletes)==4 and all(e['status']==204 for e in deletes)
 assert 'RuntimeError: The parent element this slot belongs to has been deleted.' not in (d/'webui.log').read_text()
 a['browsers'][name]={'version':r['version'],'checks':7,'screenshots':16,
     'deletion_refresh':recovery,'successful_deletions':4,
     'source_files_matched':len(hashes),'unexpected_errors':0}
failures=list(ET.parse(p/'before-corrected/tests.xml').getroot().iter('failure'))
assert len(failures)==16 and all('The parent element this slot belongs to has been deleted.' in (f.text or '') for f in failures)
a['pre_fix']='All 16 new context-sensitive cases reproduced the deleted-slot failure'
cleanup=json.loads((p/'database-cleanup.json').read_text());assert not cleanup['remaining_databases']
processes=json.loads((p/'process-cleanup.json').read_text());assert not processes['test_path_processes'] and not processes['driver_processes']
a['disposable_databases_removed']=len(cleanup['runs'])
assert all(v['exit_code']==0 for v in json.loads((p/'validation.json').read_text()))
for f,h in start['sha256'].items():
 if '/i18n/' in f: assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==h
a['catalogues_unchanged']=True
a['excluded_attempts']={'before':'Incorrectly awaited a synchronous test event wrapper; corrected',
 'before-corrected':'Expected failing regression evidence',
 'edge':'Installed patch version differed from prior snapshot; stopped before journeys and reran with verified installed version and matching cached driver'}
a['test_source_sha256']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path('frontend/webui/interaction/tests/test_components_feature.py'),Path('tools/webui_browser_components.py')]}
(p/'acceptance.json').write_text(json.dumps(a,indent=2)+'\n')
print('Accepted: 197 focused tests; Chrome/Edge English/Arabic deletion notifications, automatic refresh, empty state and nearby workflows; cleanup verified.')
