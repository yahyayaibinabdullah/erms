"""Upgrade an occupied pre-082 database without rewriting review history."""
import os
from pathlib import Path
import pytest
from backend.services.api.tests.test_disposition_approval import manager,reach_manager,approve
from backend.services.api.tests.test_disposition_review import db,save,actor


@pytest.mark.skipif(not os.environ.get('ERMS_TEST_DEFERRED_MIGRATIONS'),reason='Requires explicit pre-082 disposable database')
def test_upgrade_preserves_old_notes_submission_decisions_and_events():
    with db() as c:
        job,root,mgr=manager(c,'simplified');reach_manager(c,job,'simplified')
        save(c,job,acting=mgr,review_notes='Earlier distinct manager notes',note_version=0)
        approve(c,job,mgr)
        assert c.execute('SELECT reason FROM disposition_review_decisions WHERE job_id=%s ORDER BY id DESC LIMIT 1',(job['id'],)).fetchone()['reason']=='Review the complete destruction job'
        def snapshot():
            return [c.execute('SELECT jsonb_agg(to_jsonb(t) ORDER BY id) value FROM '+table+' t').fetchone()['value'] for table in ('disposition_review_notes','disposition_review_rounds','disposition_review_decisions','event_history')]
        before=snapshot();c.commit();c.autocommit=True
        for path in os.environ['ERMS_TEST_DEFERRED_MIGRATIONS'].split(os.pathsep):c.execute(Path(path).read_text(),prepare=False)
        c.autocommit=False;actor(c)
        assert snapshot()==before
        assert c.execute("SELECT count(*) n FROM pg_trigger WHERE tgname='disposition_review_comments'").fetchone()['n']==1
