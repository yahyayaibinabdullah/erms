"""Reconcile production settings to approved ownership; never read private env."""
import ast,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
READERS={'os.getenv','os.environ.get','required_environment','integer_environment','boolean_environment','float_environment','choice_environment','_integer'}
TEMPLATES=['.env.example','.env.example.api','.env.example.text_indexer','backend/services/api/deploy/api.env.example','frontend/webui/deploy/webui.env.example','backend/services/text_indexer/deploy/text-indexer.env.example']
TEMPLATE_SERVICES={
    '.env.example.api':'API',
    'backend/services/api/deploy/api.env.example':'API',
    'frontend/webui/deploy/webui.env.example':'WebUI',
    '.env.example.text_indexer':'Text indexer',
    'backend/services/text_indexer/deploy/text-indexer.env.example':'Text indexer',
}
SERVICE_TEMPLATES={
    'backend/services/api':'backend/services/api/deploy/api.env.example',
    'frontend/webui':'frontend/webui/deploy/webui.env.example',
    'backend/services/text_indexer':'backend/services/text_indexer/deploy/text-indexer.env.example',
}
# Approved after the original phase ledger: retain its historical evidence and
# reconcile these later contracts explicitly, rather than silently ignoring keys.
REQUEST_PRESENTATION_SETTINGS={
    'DISPOSITION_ORGANIZATION_NAME', 'DISPOSITION_RECORDS_UNIT_EMAIL',
    'DISPOSITION_RECORDS_UNIT_PHONE', 'DISPOSITION_REQUEST_LANGUAGE',
}


def service_for(key, authority):
    if key.startswith(('WEBUI_','NICEGUI_','DATABASE_DISPLAY_NAME')):
        return 'WebUI'
    if key in {'TEXT_INDEXER_ENABLED','CONTENT_INDEXING_MAINTENANCE_ENABLED','TEXT_INDEXER_API_KEY_FILE'}:
        return 'Local orchestration'
    if key.startswith('TEXT_INDEXER_') and authority=='deployment':
        return 'Text indexer'
    return 'API'

def inventory():
    ledger=json.loads((ROOT/'docs/disposition-requirement-ledger.json').read_text())
    from backend.services.api.application_settings_registry import REGISTRY
    owned_settings=[{**s,'setting':s.get('registry_key') or s['setting']} for s in ledger['settings']]
    contracts={s['setting']:s for s in owned_settings}
    result={s['setting']:{'setting':s['setting'],'authority':s['ownership'],'contract':'specs/application-configuration.md section '+s['section'],'default_or_requirement':s['contract_cells'][2] if s['ownership']=='database' else s['contract_cells'][1], 'category':s.get('registry_category'), 'consumers':[], 'templates':[]} for s in owned_settings}
    for key in sorted(REQUEST_PRESENTATION_SETTINGS):
        setting=REGISTRY[key]
        contracts[key]={
            'current_consumers':[{'path':'backend/services/api/disposition/document_snapshots.py','scope':'Captures current database presentation settings for new documents.'}],
            'runtime_status':'database_only_request_presentation_consumer',
        }
        if key in {'DISPOSITION_REQUEST_LANGUAGE','DISPOSITION_ORGANIZATION_NAME'}:
            contracts[key]['current_consumers'].append({'path':'backend/services/api/disposition/email.py','scope':'Captures correspondence language and organization at deliberate send.'})
        result[key]={
            'setting':key,'authority':'database',
            'contract':'specs/administration-settings.md#disposition-request-presentation-amendment--27-october-2026',
            'default_or_requirement':setting.default,'category':setting.category,
            'consumers':[],'templates':[],
        }
    registered={key for key,item in result.items() if item['authority']=='database'}
    if registered!=set(REGISTRY):
        raise ValueError('Database registry/ownership contracts differ: '+', '.join(sorted(registered ^ set(REGISTRY))))
    result['SSL_CERT_FILE']={
        'setting':'SSL_CERT_FILE','authority':'deployment',
        'contract':'docs/local-tooling.md#certificate-trust-and-local-files',
        'default_or_requirement':'Unset; platform trust. Optional CA file for local MailDev or an operator-managed private CA.',
        'category':None,
        'consumers':[{'path':'backend/services/api/disposition/communications.py','scope':'Python/OpenSSL TLS trust in API and communications sending processes; no application-settings fallback.'}],
        'templates':[],
    }
    for name in TEMPLATES:
        for key in re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=',(ROOT/name).read_text(),re.M):
            if key=='DATABASE_DISPLAY_NAME_AR':key='DATABASE_DISPLAY_NAME_<LANGUAGE>'
            if key not in result:
                if not key.startswith('MESSAGING_'):raise ValueError('Unreconciled template setting: '+key)
                result[key]={'setting':key,'authority':'deployment','contract':'specs/notifications-and-messaging.md section 11.5 and backend/services/api/messaging/realtime.py','default_or_requirement':'See service template','category':None,'consumers':[],'templates':[]}
            result[key]['templates'].append(name)
            if result[key]['authority']=='database':raise ValueError('Database key in environment template: '+key)
            if name in TEMPLATE_SERVICES and service_for(key,result[key]['authority'])!=TEMPLATE_SERVICES[name]:
                raise ValueError('Wrong service environment template: '+key+' in '+name)
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
                # Offline catalogue-maintenance scripts can use an API-owned
                # database URL without making it a WebUI process setting.
                if 'scripts' not in path.relative_to(ROOT/folder).parts and SERVICE_TEMPLATES[folder] not in result[key]['templates']:
                    raise ValueError('Production reader absent from service template: '+key)
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
        if key=='SSL_CERT_FILE':
            item['purpose']='Optional process TLS trust override; leave unset for valid public certificates. Never disables certificate verification.'
        item['restart']='No; API 30-second cache (current committed capture at specified workflow boundaries)' if item['authority']=='database' else 'Restart/relaunch the consuming service after deployment changes'
        item['service']=service_for(key,item['authority'])
    return {'settings':list(dict(sorted(result.items())).values()),'reconciliation':[f'All {len(REGISTRY)} database settings have explicit API registry categories.','All six environment templates are checked, including the generated API and standalone indexer examples.','Later request-presentation settings follow the approved Administration Settings amendment; original phase evidence remains historical.','SSL_CERT_FILE is optional process TLS infrastructure; public certificates use platform trust.','WEBUI_FULL_TEXT_SEARCH_ENABLED is removed; API FULL_TEXT_SEARCH_ENABLED is the only authority.','MESSAGING_* retains its separately approved deployment ownership.','CONTENT_DOWNLOAD_DB_BATCH_SIZE has no current consumer/template; no unused setting was invented.','PATH is host runtime infrastructure, not a Wathiq product setting.','DATABASE_DISPLAY_NAME_<LANGUAGE> covers localized deployment display names.','Third-party library/internal process variables and test-only seams are not product-setting inventory.']}

if __name__=='__main__':
    data=inventory()
    assert data==json.loads((ROOT/'docs/configuration-authority-inventory.json').read_text()),'Reconcile the checked-in authority inventory deliberately'
    print(f"Configuration authority valid: {len(data['settings'])} settings, exactly one owner each.")
