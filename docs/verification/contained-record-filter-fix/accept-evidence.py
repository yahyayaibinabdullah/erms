"""Verify final local results and source identity before archiving."""
from pathlib import Path
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
p=Path('.runtime/contained-record-filter-fix')
start=json.loads((p/'start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
a={'status':'Contained-record empty-filter recovery fixed and locally verified',
   'date':'2026-11-11','branch':start['branch'],'head':start['head'],
   'git_mutations':False,'tests':{},'browsers':{}}
for name,count in [('unit',163),('interaction',4)]:
 suites=list(ET.parse(p/name/'tests.xml').getroot().iter('testsuite'))
 assert all(all(int(s.get(k,'0'))==0 for k in ['errors','failures','skipped']) for s in suites)
 assert sum(int(s.get('tests')) for s in suites)==count
 a['tests'][name]=count
for name in ['chrome','edge']:
 d=p/name;r=json.loads((d/'browser-results.json').read_text());life=json.loads((d/'lifecycle.json').read_text())
 assert r['complete'] and life['test_exit_code']==0 and life['database_dropped']
 assert len(r['checks'])==7 and all(c['status']=='pass' for c in r['checks'])
 assert len(r['screenshots'])==26 and not r['browser_errors']
 recovery=r['empty_filter_recovery']
 assert len(recovery)==2 and {x['language'] for x in recovery}=={'en','ar'}
 assert all(all(v is True for k,v in x.items() if k!='language') for x in recovery)
 hashes=json.loads((d/'source-environment.json').read_text())['sha256']
 assert all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in hashes.items())
 for s in r['screenshots']: assert hashlib.sha256((d/s['file']).read_bytes()).hexdigest()==s['sha256']
 requests=[json.loads(x) for x in (d/'requests.jsonl').read_text().splitlines()]
 assert all(e['status'] is not None and e['status']<400 for e in requests)
 a['browsers'][name]={'version':r['version'],'checks':7,'screenshots':26,
     'empty_filter_recovery':recovery,'source_files_matched':len(hashes),'unexpected_errors':0}
before=json.loads((p/'before-chrome/browser-results.json').read_text())
assert not before['complete'] and any(c['status']=='fail' and 'No records match this filter' in c.get('error','') for c in before['checks'])
a['pre_fix']='Chrome reproduces missing filtered-empty state; excluded from passing acceptance'
cleanup=json.loads((p/'database-cleanup.json').read_text());assert not cleanup['remaining_databases']
processes=json.loads((p/'process-cleanup.json').read_text());assert not processes['test_path_processes'] and not processes['driver_processes']
a['disposable_databases_removed']=len(cleanup['runs'])
assert all(v['exit_code']==0 for v in json.loads((p/'validation.json').read_text()))
for f,h in start['sha256'].items():
 if '/i18n/' in f: assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==h
a['catalogues_unchanged']=True
(p/'acceptance.json').write_text(json.dumps(a,indent=2)+'\n')
print('Accepted: 167 focused tests; Chrome/Edge English/Arabic recovery, paging and nearby workflows; cleanup verified.')
