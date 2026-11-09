"""The optional-reason upgrade preserves occupied job/proposal/note history."""
from pathlib import Path

from backend.services.api.tests.test_disposition_membership import db
from backend.services.api.tests.test_disposition_workflow import seeded
from backend.services.api.tests.test_disposition_review import save,create

ROOT=Path(__file__).resolve().parents[4]


def test_optional_reason_upgrade_preserves_saved_work_and_is_repeatable(client):
    with db() as c:
        # Reintroduce the former constraint to model existing saved work before
        # the optional-reason upgrade, without relying on a Git checkout at runtime.
        c.execute("ALTER TABLE disposition_review_proposals DROP CONSTRAINT disposition_review_proposals_check")
        c.execute("ALTER TABLE disposition_review_proposals ADD CONSTRAINT disposition_review_proposals_check CHECK (proposal_type<>'remove_from_job' OR (target_record_id IS NULL AND target_aggregation_id=governing_root_id AND reason IS NOT NULL AND reason !~ '^[[:space:]]*$'))")
        job,root,*_=seeded(c)
        save(c,job,changes=[create(c,root,'remove_from_job',reason='Keep for later')],review_notes='Partial review',note_version=0)
        tables=('disposition_jobs','disposition_tasks','disposition_job_memberships','disposition_review_proposals','disposition_review_notes','event_history')
        def snapshot():return {t:c.execute('SELECT to_jsonb(t) value FROM '+t+' t ORDER BY id').fetchall() for t in tables}
        before=snapshot()
        upgrade=(ROOT/'database/migrations/096_immediate_proposals_optional_reasons.sql').read_text().replace('BEGIN;\n','',1).removesuffix('COMMIT;\n')
        for _ in range(2):
            c.execute(upgrade,prepare=False)
            assert snapshot()==before
        assert c.execute("SELECT count(*) n FROM schema_migrations WHERE version='096_immediate_proposals_optional_reasons'").fetchone()['n']==1
