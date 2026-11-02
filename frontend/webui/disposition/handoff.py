"""Localized stage outcomes and actual next recipients, using response data only."""
from nicegui import ui
from .messages import text


def notify_completion(result, message_key, *, type='positive'):
    message = text('job_completed') if result.get('workflow_completed') else text(message_key)
    recipients = ' · '.join(text('next_role_queue', name=r['name']) if r['kind'] == 'role_queue' else r['name']
                            for r in result.get('next_recipients', []) if r.get('name'))
    if recipients:
        if message_key in ('submitted', 'review_completed') and not result.get('workflow_completed'):
            message = text('submitted_to' if message_key == 'submitted' else 'review_completed_to', recipients=recipients)
        else:
            message = text('completion_next_task', message=message, recipients=recipients)
    elif result.get('next_stage') == 'certificate_generation' and not result.get('workflow_completed'):
        message = text('completion_next_automatic', message=message, stage=text('certificate_generation'))
    ui.notify(message, type=type, timeout=8000)


async def task_finished(form, result):
    """Return completed task views to the inbox; retain progress/final views."""
    if not form.alive():
        return
    task_type = (form.task or {}).get('task_type')
    keep_open = (result.get('workflow_completed') or result.get('completed') is True
                 or task_type in ('digital_destruction', 'certificate_download')
                 or form.job.get('workflow_stage') == 'certificate_generation')
    inbox = getattr(form, 'on_submitted', None)
    if inbox and not keep_open:
        await inbox()
    else:
        await form.after(result)
