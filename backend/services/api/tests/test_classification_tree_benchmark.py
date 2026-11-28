"""Verify the representative tree fixture/oracle before running large timings."""
import json
import os

from backend.services.api.application_settings import cache
from .test_code_generator_database import c


def test_representative_tree_uses_real_batches_and_permissions(client,c,tmp_path,monkeypatch):
    from tools import check_search_performance as base
    from tools.classification_tree_performance import seed,exercise
    from backend.services.api.main import app
    monkeypatch.setattr(base,'AGGREGATIONS',1509)
    monkeypatch.setattr(base,'RECORDS',4527)
    base.seed(c,typed=True,include_chunks=False)
    refs=seed(c,tmp_path,root_count=1000)
    cache.invalidate()
    exercise(os.environ['DATABASE_URL'],tmp_path,1,refs,app,base.PASSWORD,http_client=client)
    fixture=json.loads((tmp_path/'tree-fixture.json').read_text())
    result=json.loads((tmp_path/'tree-results.json').read_text())
    assert fixture['counts']['maximum_child_aggregations']==100
    assert fixture['counts']['maximum_roots_per_classification']==100
    assert result['correctness_complete'] is True
    assert all(row['parameters']['limit']==50 for row in result['samples'])
    assert {row['identity'] for row in result['samples']}=={'reader','denied'}
    assert all(row['status'] in (200,404) for row in result['samples'])
    assert len(result['expansion_pairs'])==4
    assert len(list(tmp_path.glob('tree-plan-*.json')))>10
