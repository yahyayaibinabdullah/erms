"""Acceptance decisions must not hide slow tails or mistake noise for a trend."""
import pytest
from tools.compare_webui_performance import compare_runs, load_samples


def runs(original=500, current=600):
    return {number: {('settings', 'en'): [original if number in (1, 4) else current] * 12}
            for number in (1, 2, 3, 4)}


def test_both_limits_at_boundary_block_both_pairs():
    assert compare_runs(runs())[0]['blocking_metrics'] == ['median', 'p90']


@pytest.mark.parametrize('original,current', [(100, 150), (1000, 1100), (500, 500), (500, 400)])
def test_relative_only_absolute_only_unchanged_or_faster_do_not_block(original, current):
    assert compare_runs(runs(original, current))[0]['blocking_metrics'] == []


def test_one_slow_process_does_not_establish_repeatable_regression():
    evidence = runs()
    evidence[3][('settings', 'en')] = [490] * 12
    row = compare_runs(evidence)[0]
    assert not row['blocking_metrics']
    assert not row['repeatable_slower_metrics_to_investigate']


def test_slow_tail_blocks_even_when_medians_match():
    evidence = runs(current=500)
    for number in (2, 3):
        evidence[number][('settings', 'en')][-3:] = [800] * 3
    assert compare_runs(evidence)[0]['blocking_metrics'] == ['p90']


def test_small_repeatable_slowdown_remains_visible_for_investigation():
    row = compare_runs(runs(current=550))[0]
    assert not row['blocking_metrics']
    assert row['repeatable_slower_metrics_to_investigate'] == ['median', 'p90']


def test_incomplete_coverage_is_rejected():
    evidence = runs()
    evidence[3][('settings', 'en')].pop()
    with pytest.raises(ValueError, match='Incomplete independent samples'):
        compare_runs(evidence)


def test_missing_run_is_rejected():
    evidence = runs()
    del evidence[4]
    with pytest.raises(ValueError, match='Four independent'):
        compare_runs(evidence)


def test_failed_browser_report_cannot_become_passing_timings():
    with pytest.raises(ValueError, match='Failed browser'):
        load_samples({'complete': True, 'checks': [{'status': 'fail'}]})


def test_warmup_is_excluded():
    assert load_samples({'complete': True, 'checks': [{'status': 'pass'}],
                         'performance_samples': [
                             {'workflow': 'settings', 'language': 'en', 'warmup': True, 'milliseconds': 9999},
                             {'workflow': 'settings', 'language': 'en', 'warmup': False, 'milliseconds': 500},
                         ]}) == {('settings', 'en'): [500]}


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), 0, -1])
def test_invalid_measurements_cannot_pass(invalid):
    with pytest.raises(ValueError, match='invalid timings'):
        load_samples({'complete': True, 'checks': [{'status': 'pass'}],
                      'performance_samples': [{'workflow': 'settings', 'language': 'en',
                                               'warmup': False, 'milliseconds': invalid}]})
