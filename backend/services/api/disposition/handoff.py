"""Current routed recipients after a stage finishes; no inferred assignments/cache."""
from .proposals import submission_recipients


def describe(c, result, language_tag, *, job_id=None):
    if result is None:
        return None
    identity = job_id or result.get('job_id')
    if identity is None:
        return result
    job = c.execute('SELECT workflow_stage,current_review_round,lifecycle_state FROM disposition_jobs WHERE id=%s', (identity,)).fetchone()
    if not job:
        return result
    stage = job['workflow_stage']
    # Digital resource work finishes before the certificate worker changes the
    # job state. Its durable queue is the next work, not the old digital task.
    if stage == 'digital_destruction' and result.get('state') == 'succeeded':
        queued = c.execute("SELECT 1 FROM disposition_private.completion_work WHERE job_id=%s AND state IN ('queued','running')", (identity,)).fetchone()
        if queued:
            stage = 'certificate_generation'
    # Compatibility for historical completed jobs; 091 repairs outstanding tasks.
    if job['lifecycle_state'] == 'completed':
        download = c.execute("SELECT workflow_stage FROM disposition_tasks WHERE job_id=%s AND task_type='certificate_download' AND task_state IN ('open','claimed') LIMIT 1", (identity,)).fetchone()
        stage = download['workflow_stage'] if download else None
    context = dict(job_id=identity, workflow_stage=stage, review_round=job['current_review_round'])
    return {**result, 'next_stage': stage, 'workflow_completed': job['lifecycle_state'] == 'completed',
            'next_recipients': submission_recipients(c, context, language_tag) if stage else []}
