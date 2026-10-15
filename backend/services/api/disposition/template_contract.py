"""The four destruction document contracts (destruction §§10.1, 11, 14.1, 16).

Names describe snapshot values, not new business facts. Action services supply
their committed/approved snapshot; the template layer cannot approve a job.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    filename: str
    arabic: str
    english: str
    fields: dict[str, tuple[str, str]]
    group: str
    columns: tuple[dict[str, tuple[str, str]], ...]


JOB = {
    'job.number': ('رقم عملية الإتلاف', 'Destruction job number'),
    'job.id': ('معرّف العملية', 'Internal job identifier'),
    'job.type': ('نوع الإتلاف', 'Destruction type'),
    'job.owner': ('الوحدة التنظيمية المالكة', 'Owning organizational unit'),
    'job.officer': ('مسؤول الوثائق المكلّف', 'Assigned Records Officer'),
    'job.created_at': ('تاريخ إنشاء العملية', 'Job creation date'),
    'generated_at': ('تاريخ إصدار المستند', 'Document generation date'),
}
COUNTS = {
    'counts.roots': ('عدد الملفات الجذرية الحاكمة', 'Governing root aggregations'),
    'counts.descendant_aggregations': ('عدد الملفات التابعة', 'Descendant aggregations'),
    'counts.records': ('عدد الوثائق', 'Records'),
    'counts.physical': ('عدد العناصر الورقية', 'Physical items'),
    'counts.digital': ('عدد العناصر الإلكترونية', 'Digital items'),
    'counts.mixed': ('عدد العناصر المختلطة', 'Mixed items'),
}
PHYSICAL_COUNTS = {
    'physical_aggregations': ('ملفات ورقية', 'Physical aggregations'),
    'mixed_aggregations': ('ملفات مختلطة', 'Mixed aggregations'),
    'physical_records': ('وثائق ورقية', 'Physical records'),
    'mixed_records': ('وثائق مختلطة', 'Mixed records'),
}
CONTRACTS = {
    'destruction_request': Contract(
        'request-for-destruction.default.v1.docx', 'طلب الموافقة على الإتلاف', 'Request for destruction',
        {'authority.name': ('اسم الجهة المختصة', 'External authority name'), **JOB, **COUNTS,
         'review.file_administrator': ('ملخص مراجعة مسؤول الملفات', 'File Administrator review summary'),
         'review.unit_manager': ('ملخص مراجعة مدير الوحدة', 'Unit Manager review summary'),
         'review.records_manager': ('ملخص اعتماد مدير الوثائق', 'Records Manager approval summary'),
         'review.round': ('جولة المراجعة', 'Approval review round'),
         'form.version': ('إصدار الطلب', 'Form version'),
         'membership.checksum': ('بصمة العضوية المعتمدة', 'Approved membership checksum')},
        'groups', (
            {'group.classification_code': ('رمز التصنيف', 'Classification code'),
             'group.classification_title': ('عنوان التصنيف', 'Classification title'),
             'group.rule_source': ('مصدر قاعدة الاستبقاء', 'Retention rule source')},
            {'group.final_disposition': ('التصرف النهائي الفعلي', 'Effective final disposition'),
             'group.current_years': ('مدة المرحلة الجارية بالسنوات', 'Current period in years'),
             'group.intermediate_years': ('مدة المرحلة الوسيطة بالسنوات', 'Intermediate period in years')},
            {('group.'+k.removeprefix('counts.')): v for k,v in COUNTS.items() if k in ('counts.roots','counts.descendant_aggregations','counts.records')},
            {('group.'+k.removeprefix('counts.')): v for k,v in COUNTS.items() if k in ('counts.physical','counts.digital','counts.mixed')},
        )),
    'digital_destruction_certificate': Contract(
        'digital-destruction-certificate.default.v1.docx', 'شهادة الإتلاف الإلكتروني', 'Digital destruction certificate',
        {**JOB, 'external.destruction_number': ('رقم الإتلاف المعتمد', 'Approved external destruction number'),
         'approved_request.reference': ('مرجع طلب الإتلاف المعتمد', 'Approved destruction request reference'),
         'completed_at': ('وقت إتمام الإتلاف', 'Destruction completion time'),
         'execution.manager': ('مدير الوثائق المنفّذ', 'Executing Records Manager'),
         'execution.scope': ('نطاق الإتلاف', 'Destruction scope'), **COUNTS,
         'physical.confirmation': ('تأكيد الإتلاف الورقي عند الاقتضاء', 'Physical destruction confirmation if applicable'),
         'integrity.value': ('قيمة التحقق من سلامة العملية المكتملة', 'Completed job integrity value')}, '', ()),
    'proposal_execution_report': Contract(
        'proposal-execution-report.default.v1.docx', 'تقرير تنفيذ المقترحات', 'Proposal execution report',
        {**JOB, 'review.round': ('جولة الاعتماد', 'Approval review round'),
         'execution.manager': ('مدير الوثائق المنفّذ', 'Executing Records Manager'),
         'execution.reference': ('مرجع التنفيذ', 'Execution reference'),
         'membership.checksum': ('بصمة العضوية', 'Membership checksum')}, 'proposals', (
            {'proposal.id': ('معرّف المقترح', 'Proposal identifier'),
             'proposal.action': ('الإجراء', 'Action'), 'proposal.target': ('العنصر المستهدف', 'Target resource'),
             'proposal.proposer': ('صاحب المقترح الأصلي', 'Original proposer')},
            {'proposal.result': ('نتيجة التنفيذ', 'Execution result'),
             'proposal.executor': ('المنفّذ ودوره', 'Executor and acting role'),
             'proposal.reason': ('السبب المستخدم ومصدره', 'Applied reason and its source')},
            {'proposal.removed_units': ('الوحدات المستبعدة بسبب المقترح', 'Units removed because of this proposal'),
             'proposal.history': ('مراجع سجل تغييرات المقترح', 'Preserved proposal history references')},
        )),
    'physical_preparation_report': Contract(
        'physical-preparation-report.default.v1.docx', 'تقرير التحضير للإتلاف الورقي', 'Physical destruction preparation report',
        {**JOB, 'report.version': ('إصدار التقرير', 'Report version'),
         'membership.checksum': ('بصمة العضوية', 'Membership checksum'),
         'classification.totals': ('إجماليات مجموعات التصنيف دون تكرار', 'Classification group totals without double counting'),
         **{'totals.'+k:v for k,v in PHYSICAL_COUNTS.items()}}, 'aggregations', (
            {'aggregation.classification_code': ('رمز التصنيف النهائي', 'Terminal classification code'),
             'aggregation.classification_title': ('عنوان التصنيف', 'Classification title'),
             'aggregation.identifier': ('معرّف الملف', 'Aggregation identifier'),
             'aggregation.title': ('عنوان الملف', 'Aggregation title')},
            {'aggregation.owner': ('الوحدة التنظيمية المالكة', 'Owning organizational unit'),
             'aggregation.assigned_location': ('الموقع المعيّن', 'Assigned location'),
             'aggregation.current_location': ('الموقع الحالي', 'Current location')},
            {'aggregation.descendants.'+k:v for k,v in PHYSICAL_COUNTS.items()},
        )),
}


def row_fields(contract):
    return {key:label for column in contract.columns for key,label in column.items()}
