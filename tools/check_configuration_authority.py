"""Reconcile production settings to approved ownership; never read private env."""
import ast,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
READERS={'os.getenv','os.environ.get','required_environment','integer_environment','boolean_environment','float_environment','choice_environment','_integer'}
TEMPLATES=['.env.example','backend/services/api/deploy/api.env.example','frontend/webui/deploy/webui.env.example','backend/services/text_indexer/deploy/text-indexer.env.example']

def inventory():
    ledger=json.loads((ROOT/'docs/disposition-requirement-ledger.json').read_text())
    from backend.services.api.application_settings_registry import REGISTRY
    owned_settings=[{**s,'setting':s.get('registry_key') or s['setting']} for s in ledger['settings']]
    contracts={s['setting']:s for s in owned_settings}
    result={s['setting']:{'setting':s['setting'],'authority':s['ownership'],'contract':'specs/application-configuration.md section '+s['section'],'default_or_requirement':s['contract_cells'][2] if s['ownership']=='database' else s['contract_cells'][1], 'category':s.get('registry_category'), 'consumers':[], 'templates':[]} for s in owned_settings}
    for name in TEMPLATES:
        for key in re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=',(ROOT/name).read_text(),re.M):
            if key=='DATABASE_DISPLAY_NAME_AR':key='DATABASE_DISPLAY_NAME_<LANGUAGE>'
            if key not in result:
                if not key.startswith('MESSAGING_'):raise ValueError('Unreconciled template setting: '+key)
                result[key]={'setting':key,'authority':'deployment','contract':'specs/notifications-and-messaging.md section 11.5 and backend/services/api/messaging/realtime.py','default_or_requirement':'See service template','category':None,'consumers':[],'templates':[]}
            result[key]['templates'].append(name)
            if result[key]['authority']=='database':raise ValueError('Database key in environment template: '+key)
    for folder in ('backend/services/api','frontend/webui','backend/services/text_indexer'):
        for path in (ROOT/folder).rglob('*.py'):
            if any(part in {'.venv','tests','interaction','__pycache__'} for part in path.parts):continue
            for node in ast.walk(ast.parse(path.read_text())):
                key=None
                if isinstance(node,ast.Call) and node.args and ast.unparse(node.func) in READERS and isinstance(node.args[0],ast.Constant):key=node.args[0].value
                elif isinstance(node,ast.Subscript) and ast.unparse(node.value)=='os.environ' and isinstance(node.slice,ast.Constant):key=node.slice.value
                if not isinstance(key,str):continue
                if key=='PATH':continue # Host runtime executable search path; no product setting.
                if key not in result:raise ValueError('Unreconciled production reader: '+key)
                if result[key]['authority']=='database':raise ValueError('Database key read from environment: '+key)
                result[key]['consumers'].append({'path':str(path.relative_to(ROOT)),'line':node.lineno})
    # Dynamic messaging reader is closed over the approved DEFAULTS map.
    tree=ast.parse((ROOT/'backend/services/api/messaging/config.py').read_text())
    defaults=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULTS' for t in n.targets))
    for key in defaults:
        item=result['MESSAGING_'+key];item['consumers'].append({'path':'backend/services/api/messaging/config.py','line':24});item['default_or_requirement']=defaults[key]
    for key,item in result.items():
        if item['authority']=='database':
            item['purpose']=REGISTRY[key].purpose
            item['consumers']=contracts[key]['current_consumers'] or [{'path':'backend/services/api/application_settings_registry.py','scope':'Registered Settings API/UI; workflow activation remains with the assigned phase'}]
            item['runtime_status']=contracts[key]['runtime_status']
        else:
            item['purpose']=contracts[key]['contract_cells'][-1] if key in contracts and len(contracts[key]['contract_cells'])>2 else 'Deployment process/extraction control; see the approved contract and service template'
        item['restart']='No; API 30-second cache (current committed capture at specified workflow boundaries)' if item['authority']=='database' else 'Restart/relaunch the consuming service after deployment changes'
        item['service']='WebUI' if key.startswith(('WEBUI_','NICEGUI_','DATABASE_DISPLAY_NAME')) else 'Text indexer' if key.startswith('TEXT_INDEXER_') and item['authority']=='deployment' and key not in {'TEXT_INDEXER_ENABLED','TEXT_INDEXER_API_KEY_FILE'} else 'Local orchestration' if key in {'TEXT_INDEXER_ENABLED','CONTENT_INDEXING_MAINTENANCE_ENABLED','TEXT_INDEXER_API_KEY_FILE'} else 'API'
    return {'settings':list(dict(sorted(result.items())).values()),'reconciliation':['All 51 database settings have explicit API registry categories.','WEBUI_FULL_TEXT_SEARCH_ENABLED is removed; API FULL_TEXT_SEARCH_ENABLED is the only authority.','MESSAGING_* retains its separately approved deployment ownership.','CONTENT_DOWNLOAD_DB_BATCH_SIZE has no current consumer/template; no unused setting was invented.','PATH is host runtime infrastructure, not a Wathiq product setting.','DATABASE_DISPLAY_NAME_<LANGUAGE> covers localized deployment display names.','Third-party library/internal process variables and test-only seams are not product-setting inventory.']}

if __name__=='__main__':
    data=inventory()
    assert data==json.loads((ROOT/'docs/configuration-authority-inventory.json').read_text()),'Reconcile the checked-in authority inventory deliberately'
    print(f"Configuration authority valid: {len(data['settings'])} settings, exactly one owner each.")
