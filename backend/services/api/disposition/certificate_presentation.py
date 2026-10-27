"""Concise certificate statement and actual participants, without a scope listing."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .document_snapshots import bilingual,request_language,request_organization,wording

AR_MONTHS=('يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر')
EN_MONTHS=('January','February','March','April','May','June','July','August','September','October','November','December')


def date_text(value,timezone,arabic=False):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    local=value.astimezone(ZoneInfo(timezone));offset=local.strftime('%z')
    offset=offset[:3]+':'+offset[3:]
    if arabic:return f'{local.day} {AR_MONTHS[local.month-1]} {local.year}، الساعة {local:%H:%M} (UTC{offset})'
    return f'{local.day} {EN_MONTHS[local.month-1]} {local.year} at {local:%H:%M} (UTC{offset})'


def participants(c,job,proof,language):
    """Completed preparation, approved round decisions and actual executors.

    Role queues and present-day role membership do not prove participation.
    Omit skipped stages and decisions from rejected earlier rounds.
    """
    rows=[]
    def add(role,person,unit,recorded_name=None):
        name=bilingual(person,language=language) if not recorded_name or person['name']==recorded_name else recorded_name
        rows.append({'participant.role':wording(role,language),'participant.name':name,
                     'participant.org_unit':bilingual(unit,language=language)})
    def person_unit(row):
        return ({'name':row['name'],'translations':row['translations']},
                {'name':row['org_name'],'translations':row['org_translations']})
    if job['review_route']!='records_manager_only':
        officer=c.execute("""SELECT u.name,u.translations,o.name org_name,o.translations org_translations
          FROM disposition_tasks t JOIN users u ON u.id=t.completed_by_user_id
          LEFT JOIN LATERAL (
            SELECT (e.metadata->>'acting_role_id')::bigint role_id
            FROM event_history e WHERE e.entity_type='disposition_task' AND e.entity_id=t.id
              AND e.actor_user_id=t.completed_by_user_id
              AND e.metadata->'after'->>'task_state'='completed'
              AND e.metadata->>'acting_role_id' IS NOT NULL
            ORDER BY e.id DESC LIMIT 1
          ) attribution ON true
          LEFT JOIN roles r ON r.id=attribution.role_id
          LEFT JOIN org_units o ON o.id=r.org_unit_id
          WHERE t.job_id=%s AND t.task_state='completed'
            AND t.workflow_stage IN ('officer_preparation','officer_correction')
            AND coalesce(t.review_round,1)<=%s ORDER BY t.completed_at DESC,t.id DESC LIMIT 1""",
          (job['id'],job['current_review_round'])).fetchone()
        if officer:add('مسؤول الوثائق / Records Officer',*person_unit(officer))
    decisions=c.execute("""SELECT d.review_stage,u.name,u.translations,o.name org_name,o.translations org_translations
      FROM disposition_review_decisions d JOIN disposition_review_rounds rr ON rr.id=d.round_id
      JOIN users u ON u.id=d.actor_user_id JOIN roles r ON r.id=d.acting_role_id
      JOIN org_units o ON o.id=r.org_unit_id WHERE d.job_id=%s AND rr.round_number=%s
        AND d.decision='approved' AND d.review_stage IN ('file_administrator_review','unit_manager_review')
      ORDER BY CASE d.review_stage WHEN 'file_administrator_review' THEN 1 ELSE 2 END,d.id""",
      (job['id'],job['current_review_round'])).fetchall()
    for row in decisions:
        role='مسؤول الملفات / File Administrator' if row['review_stage']=='file_administrator_review' else 'مدير الوحدة / Unit Manager'
        add(role,*person_unit(row))
    executors=c.execute("""SELECT DISTINCT p.executor_user_id,p.executor_name,u.name,u.translations,
      o.name org_name,o.translations org_translations FROM disposition_retained_records p
      JOIN users u ON u.id=p.executor_user_id
      LEFT JOIN disposition_destruction_runs run ON run.id=p.run_id
      LEFT JOIN roles r ON r.id=run.acting_role_id
      JOIN org_units o ON o.id=coalesce(r.org_unit_id,%s)
      WHERE p.job_id=%s AND p.method='postgresql_transactional_erasure'
      ORDER BY p.executor_user_id,p.executor_name""",(job['owning_org_unit_id'],job['id'])).fetchall()
    for row in executors:add('مدير الوثائق / Records Manager',*person_unit(row),recorded_name=row['executor_name'])
    return rows


def presentation(c,job,proof,settings,generated_at):
    language=request_language(c,settings);timezone=settings['DEFAULT_WORKING_TIMEZONE']
    completed=max(p['destroyed_at'] for p in proof if p['method']=='postgresql_transactional_erasure')
    statement_ar=(f"عملاً بموافقة لجنة الفرز والإتلاف في دار الوثائق في إمارة الشارقة على إتلاف الوثائق "
                  f"ضمن عملية الإتلاف رقم {job['job_number']} وبرقم الإتلاف {job['destruction_number']}، "
                  f"أتمّ تطبيق وثق الإتلاف الرقمي للوثائق بتاريخ {date_text(completed,timezone,True)}.")
    statement_en=(f"Pursuant to the approval of the Committee for Appraisal and Destruction of Sharjah Archives "
                  f"for the destruction of records under Job No. {job['job_number']} and Destruction Number "
                  f"{job['destruction_number']}, the Wathiq application completed the digital destruction of "
                  f"the records on {date_text(completed,timezone)}.")
    fields={'organization.name':request_organization(c,job['id'],settings,language)['organization.name'],
            'certificate.statement.ar':statement_ar,'certificate.statement.en':statement_en,
            'generated_at':wording('بتاريخ '+date_text(generated_at,timezone,True)+' / On '+date_text(generated_at,timezone),language)}
    return fields,participants(c,job,proof,language),language
