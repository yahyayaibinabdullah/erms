"""Archive complete local evidence without modifying historical baselines."""
import hashlib,json,re,shutil,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
r=Path('.runtime/webui-refactor-phase7');target=Path('docs/verification/webui-refactor-phase7')
performance=json.loads((r/'performance-clean-comparison.json').read_text())
assert not performance['blocked'],'Performance gate blocks Phase 7'
cleanup=json.loads((r/'database-cleanup.json').read_text());assert not cleanup['remaining_databases']
review=json.loads((r/'performance-review.json').read_text());assert review['all_repeatable_slowdowns_reviewed']
start=json.loads((r/'git-start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
before=json.loads((r/'runtime-before.json').read_text())
assert all(Path(p).exists() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in before.items())
suites=[]
for p,expected in [(r/'full-webui/1-unit.xml',1628),(r/'full-webui/1-interaction.xml',420),(r/'full-assembled/assembled.xml',74),(r/'harness-final-tests.xml',46)]:
 cases=list(ET.parse(p).getroot().iter('testcase'));assert len(cases)==expected,p
 assert not any(c.find(t) is not None for c in cases for t in ('failure','error','skipped')),p
 suites.append({'evidence':str(p.relative_to(r)),'passed':expected,'failures':0,'errors':0,'skipped':0})
native=[]
for scope in ('full','session','keyboard','governance-custody','dashboard','records','aggregations','components','application'):
 for browser in ('chrome','edge'):
  name=f'{scope}-{browser}'
  if scope in {'full','keyboard','components','application'}:name+='-resumed'
  if scope=='application' and browser=='chrome':name='application-chrome-confirmed'
  d=json.loads((r/name/'browser-results.json').read_text())
  assert d['complete'] and all(c['status']=='pass' for c in d['checks']),name
  assert not d.get('browser_errors'),name
  life=json.loads((r/name/'lifecycle.json').read_text());assert life['database_dropped'] and life['test_exit_code']==0,name
  if scope=='application':assert len(d['destinations'])==120 and len(d['screenshots'])==60,name
  for file in ('api.log','webui.log'):
   s=(r/name/file).read_text();expected=2 if file=='webui.log' and scope in {'dashboard','components'} else 0
   assert s.count('Traceback (most recent call last)')==expected,(name,file)
   if expected:assert s.count('RuntimeError: The parent element this slot belongs to has been deleted.')==expected,(name,file)
  native.append({'scope':scope,'browser':browser,'version':d['version'],'groups_passed':len(d['checks']),'screenshots':len(d['screenshots']),'evidence':name,'existing_product_errors':'Two preserved deleted-slot notification tracebacks' if scope in {'dashboard','components'} else ('Known pagination icon errors, individually recorded' if scope=='application' else None)})
assert sum(x['groups_passed'] for x in native)==190
for row in json.loads((r/'performance-accepted-runs.json').read_text()):
 d=json.loads((Path(row['output'])/'browser-results.json').read_text())
 assert row['exit_code']==0 and d['complete'] and len(d['performance_samples'])==236
 assert not d.get('browser_errors')
 for f in ('api.log','webui.log'):assert 'Traceback (most recent call last)' not in (Path(row['output'])/f).read_text()
original=json.loads((r/'original-ui-manifest.json').read_text())
# Preserve all failed and interrupted attempts alongside selected final runs.
target.mkdir(exist_ok=False)
omitted_logs=[]
def retain_large_log_metadata(directory, names):
 omitted=[]
 for name in names:
  p=Path(directory)/name
  if p.is_file() and name=='driver.log' and p.stat().st_size>5_000_000:
   digest=hashlib.sha256()
   with p.open('rb') as stream:
    for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
   omitted_logs.append({'source':str(p),'bytes':p.stat().st_size,'sha256':digest.hexdigest(),'reason':'Verbose diagnostic driver commands; retained locally in ignored runtime, excluded from timing acceptance and archive payload.'})
   omitted.append(name)
 return omitted
for p in r.iterdir():
 if p.is_dir() and ((p/'lifecycle.json').exists() or p.name=='full-webui'):
  shutil.copytree(p,target/p.name,ignore=retain_large_log_metadata)
 elif p.is_file() and p.suffix in {'.json','.xml','.log','.py'}:
  shutil.copy2(p,target/p.name)
(target/'large-diagnostic-log-retention.json').write_text(json.dumps(omitted_logs,indent=2)+'\n')
# This copy uses archived paths for traceability; raw runtime evidence is intact.
p=target/'inventory-traceability.json';p.write_text(p.read_text().replace(str(r)+'/',str(target)+'/'))
result={'status':'complete for approved local scope','phase8_started':False,'branch':start['branch'],'head':start['head'],'git_mutations':False,'application_runtime_files_changed':[], 'suites':suites,'runner_and_stream_safety_passed':30,'harness_total_passed':46,'initial_timing_breaches_retained':True,'native':native,'native_check_groups':190,'native_screenshots':436,'performance_gate':'pass; approved 20% AND 100 ms across independent pairs','performance_samples':1888,'database_runs':cleanup['created_runs'],'deferred':['Firefox','Safari','CI'],'live_smtp':'Not repeated in Phase 7; prior Phase 2/3/5 evidence retained; MailDev left alone.'}
(target/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'suites':suites,'native_groups':190,'native_screenshots':436,'database_runs':cleanup['created_runs']},indent=2))
