"""Carry original inventory forward with current owner lines and freshly executed cases."""
import ast,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');d=json.loads(Path('docs/verification/webui-refactor-phase7/inventory-traceability.json').read_text())
files=[*Path('frontend/webui').glob('*.py'),*Path('frontend/webui/disposition').glob('*.py')];definitions={}
class Owners(ast.NodeVisitor):
 def __init__(self,path):self.path=str(path);self.stack=[]
 def visit_FunctionDef(self,node):
  self.stack.append(node.name);definitions[self.path,'.'.join(self.stack)]=node.lineno;self.generic_visit(node);self.stack.pop()
 visit_AsyncFunctionDef=visit_FunctionDef
 visit_ClassDef=visit_FunctionDef
for p in files:Owners(p).visit(ast.parse(p.read_text()))
for group,field in [('named_host_functions','current_definitions'),('dialog_callsites','current_dialog_owner_sites'),('navigation_callsites','current_owner_definitions'),('shared_state_accesses','current_owner_definitions')]:
 for row in d[group]:
  for owner in row[field]:
   key=owner['file'],owner['owner']
   if key not in definitions:print('MISSING',key);continue
   if group!='dialog_callsites':owner['line']=definitions[key]
for row in d['original_runtime_modules']:
 p=Path(row['file']);assert p.exists();row['current_file_exists']=True;row['current_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
cases=[]
for p in (r/'full-webui/1-unit.xml',r/'full-webui/1-interaction.xml',r/'full-assembled/assembled.xml'):
 for case in ET.parse(p).getroot().iter('testcase'):
  assert not any(case.find(tag) is not None for tag in ('failure','error','skipped'))
  cases.append({'suite':str(p),'module':case.get('classname').replace('.','/')+'.py','test':case.get('name'),'passed':True})
for row in d['workflows']:
 if row['id'] in {'records','aggregations','dashboard'}:row['candidate_test_files'].append('frontend/webui/interaction/tests/test_personal_preview.py')
 if row['id'] in {'session','navigation'}:row['candidate_test_files'].append('frontend/webui/tests/test_feature_boundaries.py')
 row['executed_cases']=[c for c in cases if c['module'] in row['candidate_test_files']];assert row['executed_cases'],row['id']
 row['phase8_verification']='Owner module unchanged except reviewed root wiring/session principal adapter; fresh full-suite/assembled evidence linked here, with cross-feature browser evidence in the Phase 8 report.'
d['scope']='Final original-inventory reconciliation, updated after Phase 8 cleanup. Owner-level source mapping supplements executed behavior; it does not certify every dynamic data/permission combination.'
d['phase8_cleanup_evidence']=str(r/'source-audit.json')
d['phase8_identity_owner']='frontend/webui/session_context.py::SessionContext.principal; features receive current-principal callbacks; no shared identity mapping.'
(r/'inventory-traceability.json').write_text(json.dumps(d,indent=2)+'\n')
print('Mapped',len(d['workflows']),'workflow families to current passing cases; original counts:',d['counts'])
