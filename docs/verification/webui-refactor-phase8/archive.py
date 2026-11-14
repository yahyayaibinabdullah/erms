"""Validate and retain final local acceptance evidence without altering old baselines."""
import hashlib,json,shutil,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');target=Path('docs/verification/webui-refactor-phase8')
start=json.loads((r/'git-start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()==start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==start['head']
audit=json.loads((r/'source-audit.json').read_text())
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in audit['current_hashes'].items())
suites=[]
for p,count in [(r/'full-webui/1-unit.xml',1630),(r/'full-webui/1-interaction.xml',432),(r/'full-assembled/assembled.xml',74)]:
 cases=list(ET.parse(p).getroot().iter('testcase'));assert len(cases)==count,p
 assert not any(c.find(tag) is not None for c in cases for tag in ('failure','error','skipped')),p
 suites.append({'evidence':str(p.relative_to(r)),'passed':count,'failures':0,'errors':0,'skipped':0})
functional=json.loads((r/'functional-runs.json').read_text());assert len(functional)==12
native=[]
for row in functional:
 assert row['exit_code']==0
 output=Path(row['output']);data=json.loads((output/'browser-results.json').read_text())
 assert data['complete'] and all(c['status']=='pass' for c in data['checks']) and not data.get('browser_errors'),output
 assert json.loads((output/'lifecycle.json').read_text())['database_dropped']
 for file in ('api.log','webui.log'):assert 'Traceback (most recent call last)' not in (output/file).read_text(),(output,file)
 if row['scope']=='application':assert len(data['destinations'])==120
 native.append({**row,'version':data['version'],'groups_passed':len(data['checks']),'screenshots':len(data['screenshots'])})
original_visual=json.loads((r/'original-visual-runs.json').read_text());assert len(original_visual)==8
for row in original_visual:
 output=Path(row['output']);data=json.loads((output/'browser-results.json').read_text())
 assert row['exit_code']==0 and data['complete'] and all(c['status']=='pass' for c in data['checks']) and not data.get('browser_errors')
 assert json.loads((output/'lifecycle.json').read_text())['database_dropped']
 assert (output/'original-overlay.json').exists()
performance=json.loads((r/'performance-comparison.json').read_text());assert not performance['blocked']
review=json.loads((r/'performance-review.json').read_text());assert review['all_repeatable_slowdowns_reviewed']
request=json.loads((r/'performance-request-comparison.json').read_text());assert not request['differences']
runs=json.loads((r/'performance-runs.json').read_text());assert len(runs)==8
for row in runs:
 output=Path(row['output']);data=json.loads((output/'browser-results.json').read_text())
 assert row['exit_code']==0 and data['complete'] and len(data['performance_samples'])==236
 assert all(c['status']=='pass' for c in data['checks']) and not data.get('browser_errors')
 for file in ('api.log','webui.log'):assert 'Traceback (most recent call last)' not in (output/file).read_text(),(output,file)
cleanup=json.loads((r/'database-cleanup.json').read_text());assert cleanup['all_cleanup_confirmed'] and not cleanup['remaining_databases']
assert json.loads((r/'process-cleanup.json').read_text())['owned_test_processes_absent']
assert json.loads((r/'visual-review.json').read_text())['all_differences_reviewed']
assert all(not b['differences'] for b in json.loads((r/'keyboard-comparison.json').read_text())['browsers'])
target.mkdir(exist_ok=False)
for p in r.iterdir():
 if p.is_dir() and ((p/'lifecycle.json').exists() or (p/'tests.xml').exists() or (p/'summary.json').exists() or p.name=='visual-review'):
  shutil.copytree(p,target/p.name)
 elif p.is_file() and p.suffix in {'.json','.xml','.log','.py'}:shutil.copy2(p,target/p.name)
p=target/'inventory-traceability.json';p.write_text(p.read_text().replace(str(r)+'/',str(target)+'/'))
result={'status':'complete for approved local Chrome/Edge scope','branch':start['branch'],'head':start['head'],'git_mutations':False,'suites':suites,'native':native,'native_check_groups':sum(x['groups_passed'] for x in native),'supplementary_original_comparison_runs':8,'native_screenshots':sum(x['screenshots'] for x in native),'performance_gate':'pass: no repeated 20% AND 100 ms breach across independent pairs','performance_samples':1888,'excluded_warmups':144,'request_comparisons':80,'changed_runtime_files':audit['changed_runtime_files'],'all_translation_keys_preserved':4071,'database_runs':cleanup['created_runs'],'deferred':['Firefox','Safari','CI','production-scale performance'],'live_smtp':'Not repeated; earlier accepted MailDev evidence retained. Existing MailDev/Safari/local stack left alone.','final_defect_register':'docs/webui-refactor-existing-observations.md'}
(target/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({key:value for key,value in result.items() if key!='native'},indent=2))
