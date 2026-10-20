"""Phase 23 gate: current named tests and passing evidence for every owned scope.

This audits recorded results; it does not turn planned checks into test results
or run against a database. Phase 24 rollout evidence remains separately owned.
"""
from functools import lru_cache
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_disposition_baseline import ROOT, LEDGER, check as check_baseline


@lru_cache(maxsize=None)
def test_symbols(path):
    return set(re.findall(r'^\s*(?:async\s+)?def\s+(test_\w+)\s*\(', path.read_text(), re.MULTILINE))


def check_requirements(entries, runs, root=ROOT, through_phase=23):
    errors = []
    for entry in entries:
        identity = entry['id']
        if not entry.get('implementation'):
            errors.append(f'{identity}: no implementation evidence')
        passing = set()
        named = False
        for result in entry.get('verification', []):
            if result.get('result') != 'passed':
                continue
            run = runs.get(result.get('run'), {})
            if run.get('result') != 'passed':
                errors.append(f'{identity}: passing claim has no passing registered run: {result.get("run")}')
                continue
            passing.add(result.get('phase'))
            for selector in result.get('tests', []):
                # Historical live browser checks are named scenarios, not
                # Python files. Their registered passing browser run remains
                # the evidence; screenshots/details stay in that run record.
                if selector.startswith('browser::'):
                    named = True
                    continue
                source, separator, symbol = selector.partition('::')
                path = root / source
                if not path.is_file() or separator and symbol not in test_symbols(path):
                    errors.append(f'{identity}: current test selector missing: {selector}')
                else:
                    named = True
        missing = {phase for phase in entry['phases'] if phase <= through_phase} - passing
        if missing:
            errors.append(f'{identity}: unverified phase scopes: {sorted(missing)}')
        if not named:
            errors.append(f'{identity}: no named passing verification')
    return errors


def check(ledger, root=ROOT, through_phase=23):
    errors = check_baseline(ledger, root)
    errors += check_requirements(ledger['requirements'], ledger['verification_runs'], root, through_phase)
    if through_phase == 24 and ledger.get('phase_24_completion', {}).get('status') != 'complete':
        errors.append('Phase 24: rollout preparation is not complete')
    for name, run in ledger['verification_runs'].items():
        evidence = run.get('evidence')
        if run.get('result') == 'passed' and isinstance(evidence, str) and not (root / evidence).is_file():
            errors.append(f'Passing run evidence missing: {name}: {evidence}')
        elif run.get('result') == 'passed' and isinstance(evidence, str) and evidence.endswith('.json'):
            report = json.loads((root / evidence).read_text())
            if isinstance(report, dict) and 'result' in report and report['result'] != 'passed':
                errors.append(f'Passing run evidence is not passed: {name}')
    phase = ledger.get('phase_23_completion', {})
    if not phase.get('full_api_runs'):
        errors.append('Phase 23: complete API acceptance runs not recorded')
    for name in phase.get('full_api_runs', []):
        run = ledger['verification_runs'].get(name, {})
        if run.get('result') != 'passed':
            errors.append(f'Phase 23: API acceptance not passed: {name}')
        evidence = run.get('evidence')
        if not evidence or not (root / evidence).is_file():
            errors.append(f'Phase 23: API acceptance evidence missing: {name}')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through-phase', type=int, choices=(23, 24), default=23)
    args = parser.parse_args()
    ledger = json.loads((ROOT / LEDGER).read_text())
    errors = check(ledger, through_phase=args.through_phase)
    if errors:
        print('\n'.join(errors))
        raise SystemExit(1)
    boundary = 'rollout remains Phase 24' if args.through_phase == 23 else 'rollout preparation complete; persistent deployment and destruction remain unauthorized'
    print(f"Disposition acceptance valid: {len(ledger['requirements'])} requirements have named passing evidence for every phase through {args.through_phase}; {boundary}.")
