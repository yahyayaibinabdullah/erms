"""Compare independent ABBA browser runs against the approved refactor gate.

Manifest rows contain browser, sequence (1..4), variant and output directory.
Sequences 1/4 are original; 2/3 are current. Inputs must be complete successful
browser reports. This tool does not run browsers or access a database.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def load_samples(report):
    if not report.get('complete') or not report.get('checks'):
        raise ValueError('Incomplete browser evidence')
    if any(check.get('status') != 'pass' for check in report['checks']):
        raise ValueError('Failed browser evidence')
    grouped = defaultdict(list)
    for sample in report['performance_samples']:
        if not sample['warmup']:
            grouped[(sample['workflow'], sample['language'])].append(sample['milliseconds'])
    if not grouped or any(not math.isfinite(value) or value <= 0
                          for values in grouped.values() for value in values):
        raise ValueError('Missing or invalid timings')
    return grouped


def compare_runs(runs):
    """Require both independent pairs to cross both limits for the same metric."""
    if set(runs) != {1, 2, 3, 4}:
        raise ValueError('Four independent ABBA runs are required')
    keys = set(runs[1])
    if not keys or any(set(run) != keys for run in runs.values()):
        raise ValueError('Workflow/language coverage differs between runs')
    results = []
    for workflow, language in sorted(keys):
        key = (workflow, language)
        counts = [len(runs[number][key]) for number in range(1, 5)]
        expected = 1 if workflow in {'page_to_sign_in', 'sign_in_to_dashboard'} else 12
        if counts != [expected] * 4:
            raise ValueError(f'Incomplete independent samples for {key}: {counts}')
        metrics = {'median': statistics.median}
        if expected > 1:
            metrics['p90'] = lambda values: percentile(values, .9)
        pairs = []
        for original_number, current_number in ((1, 2), (4, 3)):
            values = {}
            for metric, summarize in metrics.items():
                original = summarize(runs[original_number][key])
                current = summarize(runs[current_number][key])
                delta = current - original
                percent = delta / original * 100
                values[metric] = {
                    'original_ms': original, 'current_ms': current,
                    'delta_ms': delta, 'delta_percent': percent,
                    'crosses_both_limits': delta >= 100 and percent >= 20,
                }
            pairs.append({'original_sequence': original_number,
                          'current_sequence': current_number, 'metrics': values})
        blocking = [metric for metric in metrics if all(
            pair['metrics'][metric]['crosses_both_limits'] for pair in pairs)]
        slower = [metric for metric in metrics if all(
            pair['metrics'][metric]['delta_ms'] > 0 for pair in pairs)]
        results.append({'workflow': workflow, 'language': language,
                        'samples_per_run': expected, 'pairs': pairs,
                        'blocking_metrics': blocking,
                        'repeatable_slower_metrics_to_investigate': slower})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    browsers = defaultdict(dict)
    for row in json.loads(args.manifest.read_text()):
        if row['exit_code'] or row['sequence'] in browsers[row['browser']]:
            raise ValueError('Failed or duplicate run')
        expected = 'original' if row['sequence'] in (1, 4) else 'current'
        if row['variant'] != expected:
            raise ValueError('Run order differs from independent ABBA protocol')
        report = json.loads((Path(row['output']) / 'browser-results.json').read_text())
        browsers[row['browser']][row['sequence']] = load_samples(report)
    if set(browsers) != {'chrome', 'edge'}:
        raise ValueError('Both approved browsers are required')
    results = {browser: compare_runs(runs) for browser, runs in browsers.items()}
    blocked = any(row['blocking_metrics'] for rows in results.values() for row in rows)
    args.output.write_text(json.dumps({
        'threshold': {'relative_percent': 20, 'absolute_ms': 100, 'operator': 'and'},
        'independent_pairs': [[1, 2], [4, 3]],
        'blocked': blocked,
        'note': 'Investigate every repeatable slowdown, including below-threshold findings. '
                'Cold browser load/login has one sample per independent process. '
                'A passing timing gate does not certify unmeasured workloads.',
        'browsers': results,
    }, indent=2) + '\n')
    return 1 if blocked else 0


if __name__ == '__main__':
    raise SystemExit(main())
