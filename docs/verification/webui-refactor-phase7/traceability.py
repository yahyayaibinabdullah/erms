"""Account for the original inventory without claiming static matches are tests."""
import ast,json,re
from pathlib import Path
r=Path('.runtime/webui-refactor-phase7');base=json.loads(Path('docs/verification/webui-refactor-phase1/source-inventory.json').read_text());functions=json.loads((r/'current-functions.json').read_text());dialogs=json.loads((r/'current-dialogs.json').read_text())
# Original Phase 1 workflow rows, in their recorded order.
rows=[line for line in Path('docs/webui-refactor-phase1-baseline.md').read_text().splitlines() if line.startswith('| ') and ' — [' in line]
features=[
 ('session',['session_context','account_sign_in','account_password','account_bootstrap','api_client'],['login','session','account','api_client'],['5','6f','6i']),
 ('navigation',['navigation_controller','navigation_drawer','shell','app'],['navigation','application','shell','settings'],['5']),
 ('dashboard',['dashboard','dashboard_state','personal_resources'],['dashboard'],['6s']),
 ('search',['global_search','advanced_search','saved_search'],['search'],['6q','6r']),
 ('records',['record_','digital_components','component_','resource_','entity_editor','collection_'],['record','capture','component','preview','resource_','entities'],['6l','6n']),
 ('aggregations',['aggregation_'],['aggregation','medium','collection','hold','retention'],['6m']),
 ('classification',['classification_'],['classification','retention'],['6d']),
 ('organization',['organization_'],['organization','membership','user','role','entity'],['6g']),
 ('security',['access_control','security_','governance_custody','authorization_ui','acl_editor'],['security','acl','authorization','profile','governance','custody'],['6e','6o','6p']),
 ('settings',['application_settings'],['application_settings','settings','phase4_configuration','phase6_search_configuration'],['3']),
 ('administration',['audit_','login_sessions','text_indexers'],['audit','login_sessions','text_indexer'],['6b','6f','6h']),
 ('holds',['hold'],['hold'],['6k']),
 ('disposition',['disposition'],['disposition'],['6t']),
 ('messaging',['messaging','message_','notification_'],['messaging','message_stream','notification','capture_preparation'],['6u']),
 ('relationships',['relationship_types','resource_relationship','resource_picker','resource_inspector'],['relationship','resource_picker','resource_inspector'],['6a']),
 ('localization',['account_preferences','account_user_menu','translation_','locale_','i18n_','rtl'],['translation','locale','i18n','rtl','account'],['6i','6j'])]
assert len(rows)==len(features)==16
runtime=[p for p in Path('frontend/webui').rglob('*.py') if not any(x in p.parts for x in ('.venv','tests','interaction','assembled','__pycache__'))]
tests=list(Path('frontend/webui/tests').glob('test_*.py'))+list(Path('frontend/webui/interaction/tests').glob('test_*.py'))+list(Path('frontend/webui/assembled/tests').glob('test_*.py'))
workflow=[]
for row,(identity,patterns,test_patterns,phases) in zip(rows,features):
 fields=row.split('|')[1:-1];modules=[str(p) for p in runtime if any(p.stem.startswith(x) or x=='disposition' and 'disposition' in p.parts for x in patterns)]
 matches=[str(p) for p in tests if any(x in p.stem for x in test_patterns)]
 assert modules and matches,identity
 workflow.append({'id':identity,'original_requirement':fields[0].strip(),'original_implementation':fields[1].strip(),'original_gap':fields[2].strip(),'current_modules':sorted(modules),'candidate_test_files':sorted(matches),'feature_reports':['docs/webui-refactor-phase'+p+'-'+('verification' if p!='3' else 'verification')+'.md' for p in phases], 'coverage_note':'Test files identify evidence to inspect; per-case executed coverage is recorded separately. Static linkage does not prove every dynamic variant.'})
# Preserve all named source entries, including their original location.
explicit={'persist_navigation_trail':('persist','frontend/webui/navigation_controller.py'),'select_application_settings':('open','frontend/webui/application_settings_controller.py'),'select_relationship_types':('open','frontend/webui/relationship_types_controller.py')}
closures=[]
for old in base['index_closures']:
 name=old['name']
 if name in ('lambda','listcomp','dictcomp','genexpr'):continue
 if name in explicit:
  alias,path=explicit[name];locations=[f for f in functions[alias] if f['file']==path]
 else:locations=functions.get(name,[])
 assert locations,name
 closures.append({'original':old,'current_definitions':locations,'mapping':'explicit method adapter' if name in explicit else 'preserved function name; see extraction proof for behavior'})
explicit_dialog={
 'index.open_editor.browse_classification_tree':('frontend/webui/classification_selectors.py','browse_classification_tree'),
 'index.select_advanced_search.browse_advanced_classification':('frontend/webui/classification_selectors.py','browse_advanced_classification'),
 'index':('frontend/webui/account_sign_in.py','build_sign_in'),
 'index.render_table.change_suspension':('frontend/webui/organization_collection_actions.py','change_suspension'),
 'index.render_table.confirm_lifecycle':('frontend/webui/organization_collection_actions.py','confirm_lifecycle'),
 'index.render_table.issue_password':('frontend/webui/organization_collection_actions.py','issue_password')}
linked=[]
for old in base['dialog_callsites']:
 suffix=old['owner'].removeprefix('index.')
 if old['file'].endswith('/app.py') and old['owner'] in explicit_dialog:
  path,owner=explicit_dialog[old['owner']];matches=[x for x in dialogs if x['file']==path and (x['owner'].endswith(owner) or old['owner']=='index')]
 else:matches=[x for x in dialogs if x['owner'].endswith(suffix) and (old['file'].endswith('/app.py') or x['file']==old['file'])]
 assert matches,old
 linked.append({'original':old,'current_dialog_owner_sites':matches,'mapping':'Owner-level mapping; repeated construction sites and dynamic dialog variants are not separate verified user journeys.'})
result={'baseline_commit':base['baseline_commit'],'scope':'Original inventory reconciliation; source matches supplement executed workflow tests, never replace them.','workflows':workflow,'named_host_functions':closures,'dialog_callsites':linked,'counts':{'workflow_families':len(workflow),'named_host_functions':len(closures),'dialog_callsites':len(linked)},'phase7_browser_destinations':json.loads((r/'destinations.json').read_text())}
(r/'inventory-traceability.json').write_text(json.dumps(result,indent=2)+'\n');print(result['counts'])
