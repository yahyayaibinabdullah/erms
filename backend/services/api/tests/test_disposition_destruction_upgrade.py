"""Run only with HEAD baseline and explicit deferred 066–068 upgrade files."""
import os
from pathlib import Path
import pytest,psycopg
from backend.services.api.tests.test_disposition_membership import db,actor
from backend.services.api.tests.test_disposition_recovery import mixed_done,terminate,content_rows
from backend.services.api.disposition import documents


def test_upgrade_retains_actual_physical_outcome_and_drains_legacy_workers(client,monkeypatch):
    files=os.environ.get('ERMS_TEST_DEFERRED_MIGRATIONS')
    if not files:pytest.skip('Requires explicit disposable baseline upgrade runner')
    from tools.preview_disposition import preview_pdf
    monkeypatch.setattr(documents.engine,'render',lambda *a:(preview_pdf(),{}))
    with db() as c:
        assert not c.execute("SELECT to_regclass('disposition_retained_records') available").fetchone()['available']
        job,a,b,done,untouched,mgr=mixed_done(c,monkeypatch);terminate(c,job);c.commit();actor(c)
        final=c.execute('SELECT final_disposition_at,final_disposition_by_user_id,final_disposition_event_id,destruction_number FROM aggregations WHERE id=%s',(done,)).fetchone()
        event=c.execute('SELECT * FROM event_history WHERE id=%s',(final['final_disposition_event_id'],)).fetchone()
        before=content_rows(c)
        paths=[Path(p) for p in files.split(os.pathsep)];assert len(paths)==3
        c.execute(paths[0].read_text(),prepare=False);c.commit()
        c.execute("INSERT INTO text_indexing_workers(service_user_id,worker_id,contract_version,extractor_version,extraction_config_version,index_config_version,capabilities,active_until) VALUES(1,'legacy','1','old','old','old','{}',CURRENT_TIMESTAMP+interval '10 minutes')");c.commit()
        with pytest.raises(psycopg.Error,match='requires_drained_indexers'),c.transaction():c.execute(paths[1].read_text(),prepare=False)
        c.execute('DELETE FROM text_indexing_workers');c.commit()
        c.execute(paths[1].read_text(),prepare=False);c.commit();c.execute(paths[2].read_text(),prepare=False);c.commit();actor(c)
        assert c.execute('SELECT final_disposition_at,final_disposition_by_user_id,final_disposition_event_id,destruction_number FROM aggregations WHERE id=%s',(done,)).fetchone()==final
        proof=c.execute("SELECT * FROM disposition_retained_records WHERE resource_kind='aggregation' AND resource_id=%s",(done,)).fetchone()
        assert proof['executor_user_id']==final['final_disposition_by_user_id'] and proof['destroyed_at']==final['final_disposition_at'] and proof['executor_name']==event['metadata']['executor_name']
        assert proof['run_id'] is None and proof['method']=='confirmed_physical' and proof['classification_snapshot']
        assert content_rows(c)==before
        assert c.execute('SELECT title,description,aggregation_number FROM aggregations WHERE id=%s',(done,)).fetchone()==dict(title=None,description=None,aggregation_number=None)
        assert not c.execute('SELECT current_user_can_view_aggregation(%s) visible',(done,)).fetchone()['visible']
        assert c.execute("SELECT source FROM event_history WHERE operation='DISPOSITION_RETAINED_RECORD_MIGRATED'").fetchone()['source']=='migration'
        assert not c.execute('SELECT disposition_private.digital_execution_released() yes').fetchone()['yes']
