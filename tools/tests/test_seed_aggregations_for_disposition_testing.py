"""Exercise the full API-only seed workflow without contacting a database."""
import json
from types import SimpleNamespace
from tools import seed_aggregations_for_disposition_testing as seed


def test_complete_run_and_resume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    credentials = tmp_path / 'accounts.json'
    credentials.write_text(json.dumps({seed.OMI: 'test', seed.YYA: 'test'}))
    resources = {'aggregations': {}, 'records': {}, 'components': {}, 'links': [], 'held': [], 'drafts': {}, 'record_components': {}}
    identities = []
    class FakeApi:
        def __init__(self, url, email, password):
            self.email = email
            identities.append(email)
            self.me = {'user': {'id': 6 if email == seed.YYA else 7}}
            self.client = self
        def close(self):
            pass
        def get(self, path):
            cid = int(path.split('/')[-2])
            return SimpleNamespace(content=resources['components'][cid], raise_for_status=lambda: None)
        def call(self, method, path, **kwargs):
            payload = kwargs.get('json', {})
            if path == '/classifications/search':
                assert payload['where']['value'] == '1141'
                return {'items': [{'id': 11, 'title': 'Classification 1141', 'is_terminal': True}]}
            if path == '/aggregations/search':
                number = payload['where']['value']
                exists = '/001/' in number or any(r['aggregation_number'] == number for r in resources['aggregations'].values())
                return {'total': int(exists), 'items': []}
            if path == '/creation-role-options':
                return [{'role_id': 3, 'role_code': 'RMD-EXE', 'org_unit_id': 6}]
            if path == '/security-levels':
                return [{'id': i, 'code': code} for i, code in enumerate(['G', 'R', 'S', 'TS'], 1)]
            if path == '/relationships/types/aggregation':
                return {'items': [{'id': 1, 'code': 'related_to', 'is_active': True}]}
            if path == '/holds' and method == 'GET':
                return {'items': [], 'total': 0}
            if path == '/holds':
                assert self.email == seed.YYA and payload['name'] == 'Test Legal Hold'
                return {'id': 1}
            if path.endswith('/held-items'):
                assert self.email == seed.YYA
                resources['held'].append(payload['resource_id'])
                return {}
            if path.startswith('/relationships/aggregation/'):
                resources['links'].append((int(path.rsplit('/', 1)[1]), payload['target_id']))
                return {'id': len(resources['links'])}
            if path == '/record-drafts':
                assert self.email == (seed.YYA if payload['security_level_id'] in (2, 3, 4) else seed.OMI)
                identity = len(resources['drafts']) + 1
                resources['drafts'][identity] = payload
                return {'id': identity}
            if path.startswith('/record-drafts/'):
                draft_id = int(path.split('/')[2])
                if path.endswith('/components'):
                    cid = len(resources['components']) + 1
                    resources['components'][cid] = kwargs['files']['file'][1]
                    resources['drafts'][draft_id]['component_id'] = cid
                    return {'id': cid}
                assert path.endswith('/commit')
                draft = resources['drafts'][draft_id]
                assert 'component_id' in draft
                identity = len(resources['records']) + 1
                resources['records'][identity] = {**draft, 'id': identity}
                resources['record_components'][identity] = draft['component_id']
                return resources['records'][identity]
            if path == '/digital-components/search':
                rid = payload['where']['value']
                return {'total': 1, 'items': [{'id': resources['record_components'][rid]}]}
            kind = path.split('/')[1]
            if method == 'POST':
                assert self.email == (seed.YYA if payload['security_level_id'] in (2, 3, 4) else seed.OMI)
                identity = len(resources[kind]) + 1
                resources[kind][identity] = {**payload, 'id': identity, 'parent_aggregation_id': None}
                return resources[kind][identity]
            return resources[kind][int(path.rsplit('/', 1)[1])]
    monkeypatch.setattr(seed, 'Api', FakeApi)
    args = ['seed', '--confirm-demo', '--credentials-file', str(credentials)]
    monkeypatch.setattr('sys.argv', args)
    seed.main()
    assert identities == [seed.OMI, seed.YYA]
    assert len(resources['aggregations']) == 100
    numbers = [r['aggregation_number'] for r in resources['aggregations'].values()]
    assert len(set(numbers)) == 100
    assert all(n.startswith('1141/DEMO/') for n in numbers)
    assert '/002/' in numbers[0] and '/101/' in numbers[-1]
    assert len(resources['records']) == len(resources['components']) == 200
    assert sum(a['is_vital'] for a in resources['aggregations'].values()) == 10
    assert [sum(a['security_level_id'] == i for a in resources['aggregations'].values()) for i in range(1, 5)] == [40, 40, 15, 5]
    assert len(resources['held']) == 10
    assert len(resources['links']) == 20
    assert len({i for pair in resources['links'] for i in pair}) == 20
    assert all(len(content.decode().split()) == 100 for content in resources['components'].values())
    assert all('officials from within the country' in content.decode() for content in resources['components'].values())
    assert all('property' not in content.decode().lower() for content in resources['components'].values())
    manifest = next(tmp_path.glob('.runtime/property-demo/*/manifest.json'))
    assert json.loads(manifest.read_text())['complete']
    monkeypatch.setattr('sys.argv', args + ['--resume', str(manifest)])
    seed.main()
    assert len(resources['aggregations']) == 100 and len(resources['links']) == 20
