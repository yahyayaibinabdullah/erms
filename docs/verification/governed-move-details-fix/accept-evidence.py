"""Check final local evidence before archiving it."""
from pathlib import Path
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
p = Path('.runtime/governed-move-details-fix')
start = json.loads((p/'start.json').read_text())
assert subprocess.check_output(['git','branch','--show-current'], text=True).strip() == start['branch']
assert subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip() == start['head']
accept = {'date': '2026-11-11', 'status': 'Both display defects fixed and locally verified',
          'branch': start['branch'], 'head': start['head'], 'git_mutations': False,
          'tests': {}, 'browsers': {}}
for name, expected in [('interaction',48), ('unit',163), ('rendering',16)]:
    suites = list(ET.parse(p/name/'tests.xml').getroot().iter('testsuite'))
    assert all(all(int(s.get(k,'0')) == 0 for k in ['errors','failures','skipped']) for s in suites)
    count = sum(int(s.get('tests')) for s in suites)
    assert count == expected
    accept['tests'][name] = count
for name in ['chrome-final', 'edge-final']:
    r = json.loads((p/name/'browser-results.json').read_text())
    life = json.loads((p/name/'lifecycle.json').read_text())
    assert life['test_exit_code'] == 0 and life['database_dropped'] and r['complete'] and not r['browser_errors']
    assert len(r['checks']) == 14 and all(c['status'] == 'pass' for c in r['checks'])
    assert len(r['moves']) == 8 and len(r['screenshots']) == 12
    assert len(r['move_titles']) == 12 and len(r['subtree_previews']) == 6
    assert {x['title'] for x in r['move_titles']} == {'Move aggregation','Move record','نقل ملف','نقل وثيقة'}
    assert all(x['aggregations'] == 1 and x['records'] == 2 for x in r['subtree_previews'])
    assert {x['language'] for x in r['subtree_previews']} == {'en','ar'}
    source = json.loads((p/name/'source-environment.json').read_text())['sha256']
    assert all(hashlib.sha256(Path(f).read_bytes()).hexdigest() == h for f,h in source.items())
    for s in r['screenshots']:
        assert hashlib.sha256((p/name/s['file']).read_bytes()).hexdigest() == s['sha256']
    events = [json.loads(x) for x in (p/name/'requests.jsonl').read_text().splitlines()]
    errors = [e for e in events if e['status'] is None or e['status'] >= 400]
    assert errors == r['expected_denied_previews'] and len(errors) == 2 and all(e['status'] == 404 for e in errors)
    accept['browsers'][name] = {'version': r['version'], 'checks': 14, 'moves': 8, 'screenshots': 12,
        'localized_titles': 12, 'correct_subtree_previews': 6,
        'source_files_matched': len(source), 'expected_denials': 2, 'unexpected_errors': 0}
cleanup = json.loads((p/'database-cleanup.json').read_text())
assert not cleanup['remaining_databases']
proc = json.loads((p/'process-cleanup.json').read_text())
assert not proc['test_path_processes'] and not proc['driver_processes']
accept['disposable_databases_removed'] = len(cleanup['runs'])
for f,h in start['sha256'].items():
    if '/i18n/' in f: assert hashlib.sha256(Path(f).read_bytes()).hexdigest() == h
accept['catalogues_unchanged'] = True
assert all(v['exit_code'] == 0 for v in json.loads((p/'validation-final.json').read_text()))
accept['excluded_attempts'] = {'before': 'Assertions initially omitted existing Unicode isolation',
    'before-corrected': 'Expected pre-fix regression: six failures and four passes',
    'chrome': 'Test-helper import error before Move checks',
    'edge': 'Test-helper import error before Move checks',
    'validation.json': 'API validator import requires DB configuration; pure validator then passed without API imports'}
accept['test_source_sha256'] = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in [
    Path('frontend/webui/interaction/tests/test_governed_move.py'), Path('tools/webui_browser_governed_moves.py')]}
(p/'acceptance.json').write_text(json.dumps(accept,indent=2)+'\n')
print('Accepted: 227 focused tests, both native browsers, 16 saved moves, corrected titles and counts, clean databases.')
