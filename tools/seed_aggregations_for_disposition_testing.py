#!/usr/bin/env python3
"""Create demo roots under 1141 with 1141 domestic-official meeting content through APIs only."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from getpass import getpass
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import random
import uuid
import httpx

OMI = 'omi@sa.gov.ae'
YYA = 'yya@sa.gov.ae'


def meeting_text(meeting_number: int, record_number: int) -> str:
    """Exactly 100 whitespace-separated words; fictional meetings with domestic officials."""
    text = f'''Meeting {meeting_number} briefing {record_number} documents a consultation with officials from within the country. Participants discuss public service priorities, coordination responsibilities, proposed initiatives, and practical arrangements for cooperation. The agenda identifies matters requiring clarification before decisions can be endorsed by the responsible authorities. Secretariat staff record attendance, summarize presentations, capture questions, and distinguish agreed actions from proposals requiring further consideration. Followup notes assign responsibilities, establish reporting dates, and identify supporting correspondence for the official meeting file. Reviewers check factual accuracy, confirm approved minutes, and track outstanding commitments. This synthetic example contains no real officials, personal information, confidential discussions, or actual decisions.'''
    words = text.split()
    # Stable meeting-specific content, with an explicit word-count invariant.
    assert len(words) == 100
    return ' '.join(words) + '\n'


class ApiFailure(RuntimeError):
    def __init__(self, response, method, path):
        self.status = response.status_code
        super().__init__(f'{method} {path}: HTTP {self.status}: {response.text[:2000]}')


class Api:
    def __init__(self, url, email, password):
        self.client = httpx.Client(base_url=url, timeout=90, headers={
            'X-Event-Source': 'seeding',
            'X-Change-Reason': 'User-requested synthetic domestic-official meeting demonstration dataset',
        })
        response = self.call('POST', '/auth/login', json={'email': email, 'password': password})
        token = self.client.cookies.get('erms_session')
        if token:
            self.client.headers['Authorization'] = 'Bearer ' + token
        self.me = self.call('GET', '/auth/me')
        if self.me['user']['email'].lower() != email or self.me['must_change_password']:
            raise RuntimeError('Unexpected identity or password change required')

    def call(self, method, path, **kwargs):
        response = self.client.request(method, '/api/v1' + path, **kwargs)
        if response.is_error:
            raise ApiFailure(response, method, path)
        return response.json() if response.content else None

    def close(self):
        try:
            self.call('POST', '/auth/logout')
        finally:
            self.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--confirm-demo', action='store_true', required=True,
                        help='Confirm this API instance is connected to demo')
    parser.add_argument('--credentials-file', type=Path,
                        help='Private JSON mapping account emails to passwords; otherwise prompt securely')
    parser.add_argument('--creator-role-id', type=int)
    parser.add_argument('--classification-id', type=int,
                        help='Disambiguate multiple classifications with code 1141')
    parser.add_argument('--resume', type=Path, help='Resume a previously recorded run')
    args = parser.parse_args()
    credentials = json.loads(args.credentials_file.read_text()) if args.credentials_file else {}
    clients = []
    try:
        for email in (OMI, YYA):
            clients.append(Api(args.api_url, email, credentials.get(email) or getpass(f'Password for {email}: ')))
        omi, admin = clients
        classification_page = omi.call('POST', '/classifications/search', json={
            'where': {'field': 'code', 'operator': 'eq', 'value': '1141'}, 'limit': 100})
        matches = [x for x in classification_page['items'] if args.classification_id is None or x['id'] == args.classification_id]
        if len(matches) != 1:
            raise RuntimeError('Classification 1141 is missing or ambiguous; use --classification-id')
        classification = matches[0]
        if not classification['is_terminal']:
            raise RuntimeError('Classification 1141 must be terminal')
        roles = omi.call('GET', '/creation-role-options')
        roles = [r for r in roles if args.creator_role_id is None or r['role_id'] == args.creator_role_id]
        if len(roles) != 1:
            raise RuntimeError('Choose --creator-role-id from: ' + json.dumps(roles, ensure_ascii=False))
        levels = {r['code']: r['id'] for r in omi.call('GET', '/security-levels')}
        if not {'G', 'R', 'S', 'TS'} <= levels.keys():
            raise RuntimeError('Expected General, Restricted, Secret and Top Secret security levels')
        types = omi.call('GET', '/relationships/types/aggregation', params={'q': 'related_to', 'limit': 100})
        related = [t for t in types['items'] if t['code'] == 'related_to' and t['is_active']]
        if len(related) != 1:
            raise RuntimeError('An active aggregation related_to relationship type is required')
        holds = []
        offset = 0
        while True:
            page = admin.call('GET', '/holds', params={'q': 'Test Legal Hold', 'limit': 100, 'offset': offset})
            holds += [h for h in page['items'] if h['name'] == 'Test Legal Hold']
            offset += len(page['items'])
            if offset >= page['total'] or not page['items']:
                break
        if len(holds) > 1 or holds and (not holds[0]['is_effective'] or not holds[0]['capabilities']['manage_held_items']):
            raise RuntimeError('Existing Test Legal Hold is ambiguous, inactive, or not manageable by Yahya')
        if args.resume:
            path = args.resume
            state = json.loads(path.read_text())
            if state['api_url'] != args.api_url or state['classification_id'] != classification['id']:
                raise RuntimeError('Run manifest target mismatch')
            if state.get('pending'):
                raise RuntimeError('Prior write outcome is uncertain. Inspect pending operation before resuming; do not retry blindly.')
        else:
            run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
            path = Path('.runtime/property-demo') / run / 'manifest.json'
            distribution = ['G'] * 40 + ['R'] * 40 + ['S'] * 15 + ['TS'] * 5
            random.SystemRandom().shuffle(distribution)
            state = {'run': run, 'api_url': args.api_url, 'classification_id': classification['id'],
                     'classification_title': classification['title'], 'content_subject_code': '1141', 'creator_role_id': roles[0]['role_id'],
                     'aggregations': [{'security': level, 'vital': i < 10, 'records': [{}, {}]} for i, level in enumerate(distribution)],
                     'relationships': [], 'held': [], 'pending': None}
        path.parent.mkdir(parents=True, exist_ok=True)
        def save():
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
            temporary.chmod(0o600)
            temporary.replace(path)
        def write(api, label, endpoint, **kwargs):
            state['pending'] = {'operation': label, 'endpoint': endpoint}
            save()
            try:
                result = api.call('POST', endpoint, **kwargs)
            except ApiFailure as error:
                # Keep uncertain outcomes (timeouts/server errors) pending for reconciliation.
                if error.status < 500:
                    state['pending'] = None
                    save()
                raise
            state['pending'] = None
            return result
        save()
        print(f'Run manifest: {path}', flush=True)
        if 'hold_id' not in state:
            hold = holds[0] if holds else write(admin, 'create hold', '/holds', json={
                'code': 'TEST-LEGAL-HOLD-' + state['run'], 'name': 'Test Legal Hold',
                'description': 'Synthetic domestic-official meeting demonstration legal hold',
                'valid_from': datetime.now(timezone.utc).isoformat(), 'owner_user_id': admin.me['user']['id']})
            state['hold_id'] = hold['id']; save()
        admin_roles = admin.call('GET', '/creation-role-options')
        # Prefer the same owning organization where Yahya has a creation role.
        owner_unit = roles[0].get('org_unit_id')
        same_unit = [r for r in admin_roles if r.get('org_unit_id') == owner_unit]
        admin_role = next((r for r in same_unit if r['role_id'] == state['creator_role_id']), None)
        admin_role = admin_role or (same_unit[0] if len(same_unit) == 1 else None)
        admin_role = admin_role or next((r for r in admin_roles if r['role_code'] == 'REC-MGR'), None)
        if admin_role is None:
            raise RuntimeError('Yahya needs an unambiguous creation role: ' + json.dumps(admin_roles, ensure_ascii=False))
        for i, aggregation in enumerate(state['aggregations'], 1):
            creator = admin if aggregation['security'] in ('R', 'S', 'TS') else omi
            creator_role = admin_role['role_id'] if creator is admin else state['creator_role_id']
            if 'aggregation_number' not in aggregation:
                if 'id' in aggregation:
                    aggregation['aggregation_number'] = creator.call('GET', f'/aggregations/{aggregation["id"]}')['aggregation_number']
                else:
                    year = state.setdefault('numbering_year', datetime.now(ZoneInfo('Asia/Dubai')).year)
                    serial = state.get('next_serial', 1)
                    while True:
                        candidate = f'1141/DEMO/{serial:03d}/{year}'
                        found = admin.call('POST', '/aggregations/search', json={
                            'where': {'field': 'aggregation_number', 'operator': 'eq', 'value': candidate}, 'limit': 1})
                        if not found['total']:
                            break
                        serial += 1
                    aggregation['aggregation_number'] = candidate
                    state['next_serial'] = serial + 1
                save()
            number = aggregation['aggregation_number']
            if 'id' not in aggregation:
                created = write(creator, f'aggregation {i}', '/aggregations', json={
                    'aggregation_number': number, 'title': f'Meetings with Domestic Officials — Demo {i:03d}',
                    'description': 'Synthetic aggregation under classification 1141; record content concerns classification 1141 (Meetings with Officials from Within the Country).',
                    'classification_id': state['classification_id'], 'creator_acl_role_id': creator_role,
                    'security_level_id': levels[aggregation['security']], 'medium': 'digital', 'is_vital': aggregation['vital']})
                aggregation['id'] = created['id']; save()
            for j, record in enumerate(aggregation['records'], 1):
                if 'id' not in record:
                    if 'draft_id' not in record:
                        draft = write(creator, f'draft {i}/{j}', '/record-drafts', json={
                            'aggregation_id': aggregation['id'], 'record_number': number + f'-R{j}',
                            'title': f'Domestic Officials Meeting {i:03d} — ' + ('Briefing and Agenda' if j == 1 else 'Minutes and Followup'),
                            'medium': 'digital', 'security_level_id': levels[aggregation['security']]})
                        record['draft_id'] = draft['id']; save()
                    if 'staged_component' not in record:
                        text = meeting_text(i, j)
                        record['staged_component'] = write(creator, f'stage {i}/{j}', f'/record-drafts/{record["draft_id"]}/components',
                            data={'component_order': '1'}, files={'file': (f'meeting-{i:03d}-{j}.txt', text.encode(), 'text/plain')})
                        record['word_count'] = len(text.split()); save()
                    created = write(creator, f'commit {i}/{j}', f'/record-drafts/{record["draft_id"]}/commit',
                                    params={'creator_acl_role_id': creator_role})
                    record['id'] = created['id']; save()
                if 'component' not in record:
                    page = creator.call('POST', '/digital-components/search', json={
                        'where': {'field': 'record_id', 'operator': 'eq', 'value': record['id']}, 'limit': 2})
                    if page['total'] != 1:
                        raise RuntimeError(f'Record {record["id"]} must have exactly one committed component; reconcile the legacy empty record before resuming')
                    record['component'] = page['items'][0]; save()
            print(f'Completed aggregation {i}/100', flush=True)
        for i in range(len(state['relationships']), 20):
            source = state['aggregations'][i]['id']; target = state['aggregations'][(i + 1) % 20]['id']
            link = write(admin, f'relationship {i}', f'/relationships/aggregation/{source}',
                         json={'relationship_type_id': related[0]['id'], 'target_id': target})
            state['relationships'].append(link); save()
        for aggregation in state['aggregations'][:10]:
            if aggregation['id'] not in state['held']:
                write(admin, f'hold aggregation {aggregation["id"]}', f'/holds/{state["hold_id"]}/held-items',
                      json={'resource_type': 'aggregation', 'resource_id': aggregation['id']})
                state['held'].append(aggregation['id']); save()
        # Read back every created resource using the requested creator identity.
        for aggregation in state['aggregations']:
            creator = admin if aggregation['security'] in ('R', 'S', 'TS') else omi
            actual = creator.call('GET', f'/aggregations/{aggregation["id"]}')
            assert actual['parent_aggregation_id'] is None
            assert actual['aggregation_number'] == aggregation['aggregation_number']
            assert actual['classification_id'] == state['classification_id']
            assert actual['security_level_id'] == levels[aggregation['security']]
            assert actual['is_vital'] == aggregation['vital']
            for record in aggregation['records']:
                actual_record = creator.call('GET', f'/records/{record["id"]}')
                assert actual_record['aggregation_id'] == aggregation['id']
                component_id = record['component']['id']
                response = creator.client.get(f'/api/v1/digital-components/{component_id}/content')
                response.raise_for_status()
                assert len(response.content.decode('utf-8').split()) == record['word_count'] == 100
        state['complete'] = True; save()
        print('Complete: 100 roots, 200 records/files, 10 vital roots, 20 relationship links, 10 held roots.', flush=True)
    finally:
        for api in clients:
            try:
                api.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
