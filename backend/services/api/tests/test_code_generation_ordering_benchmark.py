"""Check benchmark oracles/requests on a small disposable corpus, not an SLA run."""
import json

from backend.services.api.application_settings import cache
from .test_code_generator_database import c


def test_natural_order_benchmark_harness_smoke(client,c,tmp_path,monkeypatch):
    from tools import check_search_performance as base
    from tools.code_generation_ordering_performance import seed,exercise
    monkeypatch.setattr(base,'AGGREGATIONS',1509)
    monkeypatch.setattr(base,'RECORDS',4527)
    base.seed(c,typed=True)
    definitions=seed(c,tmp_path)
    cache.invalidate()
    failures=exercise(client,c,tmp_path,1,definitions)
    # This reduced fixture checks the harness, including complete ordered IDs,
    # scores, missing values, denied scopes and actual plans. The full runner
    # alone enforces the measured 50,000/150,000-row acceptance gate.
    assert failures==[]
    report=json.loads((tmp_path/'code-order-results.json').read_text())
    assert len(report['samples'])>100
    assert len(list(tmp_path.glob('*-plan.json')))>=24

