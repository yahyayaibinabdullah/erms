"""Negative controls for the integrated requirement-to-test acceptance gate."""
from copy import deepcopy
import pytest

from tools.check_disposition_acceptance import check_requirements


@pytest.fixture
def evidence(tmp_path):
    (tmp_path / 'test_flow.py').write_text('def test_complete_journey():\n    pass\n')
    entry = {'id': 'DISP-example', 'phases': [22, 23, 24],
             'implementation': [{'phase': 22, 'locations': ['service.py']}],
             'verification': [{'phase': phase, 'result': 'passed', 'run': 'acceptance',
                               'tests': ['test_flow.py::test_complete_journey']} for phase in (22, 23)]}
    return entry, {'acceptance': {'result': 'passed'}}, tmp_path


def test_future_rollout_is_not_falsely_claimed_or_required(evidence):
    entry, runs, root = evidence
    assert check_requirements([entry], runs, root) == []
    assert '24' in '\n'.join(check_requirements([entry], runs, root, through_phase=24))


@pytest.mark.parametrize('failure', ['missing_phase', 'planned_only', 'failed_run', 'missing_run', 'missing_symbol', 'missing_file', 'no_implementation'])
def test_incomplete_or_unsupported_acceptance_cannot_pass(evidence, failure):
    entry, runs, root = deepcopy(evidence)
    if failure == 'missing_phase':
        entry['verification'].pop()
    elif failure == 'planned_only':
        entry['verification'][0]['result'] = 'planned'
    elif failure == 'failed_run':
        runs['acceptance']['result'] = 'failed'
    elif failure == 'missing_run':
        runs.clear()
    elif failure == 'missing_symbol':
        entry['verification'][0]['tests'] = ['test_flow.py::test_invented']
    elif failure == 'missing_file':
        entry['verification'][0]['tests'] = ['missing.py::test_complete_journey']
    else:
        entry['implementation'] = []
    assert check_requirements([entry], runs, root)


def test_historical_nonpassing_result_does_not_replace_current_passing_scope(evidence):
    entry, runs, root = evidence
    entry['verification'].insert(0, {'phase': 22, 'result': 'pending_live_rtl', 'run': 'old'})
    assert check_requirements([entry], runs, root) == []
