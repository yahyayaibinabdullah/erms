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
    optional: tuple[str, ...] = ()
    extra_groups: tuple = ()


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
        'request-for-destruction.default.v2.docx', 'طلب الموافقة على الإتلاف', 'Request for destruction',
        {'organization.name': ('اسم الجهة الطالبة', 'Requesting organization'),
         'organization.email': ('البريد الإلكتروني للتواصل', 'Contact email'),
         'organization.phone': ('هاتف التواصل', 'Contact phone'),
         'authority.name': ('اسم الجهة المختصة', 'External authority name'), **JOB, **COUNTS,
         'counts.roots': ('عدد الملفات', 'Aggregations'),
         'records.from_year': ('من سنة', 'From Year'),
         'records.to_year': ('إلى سنة', 'To Year'),
         'review.file_administrator': ('ملخص مراجعة مسؤول الملفات', 'File Administrator review summary'),
         'review.unit_manager': ('ملخص مراجعة مدير الوحدة', 'Unit Manager review summary'),
         'review.records_manager': ('ملخص اعتماد مدير الوثائق', 'Records Manager approval summary'),
         'review.round': ('جولة المراجعة', 'Approval review round'),
         'form.version': ('إصدار الطلب', 'Form version'),
         'membership.checksum': ('بصمة العضوية المعتمدة', 'Approved membership checksum')},
        'aggregations', (
            {'aggregation.serial_number': ('م', 'No.'),
             'aggregation.number': ('رقم الملف', 'Aggregation number'),
             'aggregation.title': ('عنوان الملف', 'Aggregation title')},
            {'aggregation.from_year': ('من سنة', 'From Year'),
             'aggregation.to_year': ('إلى سنة', 'To Year')},
            {'aggregation.classification_code': ('رقم التصنيف', 'Classification number'),
             'aggregation.records': ('إجمالي الوثائق', 'Total records')},
            {'aggregation.assigned_location': ('الموقع المعيّن للملفات الورقية أو المختلطة', 'Assigned location for physical or mixed aggregations')},
        ), ('job.id','job.type','job.created_at','counts.descendant_aggregations','review.round','membership.checksum')),
    'digital_destruction_certificate': Contract(
        'digital-destruction-certificate.default.v2.docx', 'شهادة الإتلاف الرقمي', 'Digital Destruction Certificate',
        {'organization.name': ('اسم الجهة', 'Organization name'),
         'certificate.statement.ar': ('إفادة إتمام الإتلاف بالعربية', 'Arabic destruction completion statement'),
         'certificate.statement.en': ('إفادة إتمام الإتلاف بالإنجليزية', 'English destruction completion statement'),
         'generated_at': ('تاريخ إصدار الشهادة', 'Certificate generation date')}, 'participants', (
            {'participant.role': ('الدور', 'Role'),
             'participant.name': ('الاسم', 'Name'),
             'participant.org_unit': ('الوحدة التنظيمية', 'Organizational unit')},
        )),
    'proposal_execution_report': Contract(
        'proposal-execution-report.default.v2.docx', 'تقرير تنفيذ المقترحات', 'Proposal execution report',
        {'organization.name': ('اسم الجهة', 'Organization name'), 'execution.count': ('عدد المقترحات المنفّذة', 'Executed proposals'), **JOB, 'review.round': ('جولة الاعتماد', 'Approval review round'),
         'execution.manager': ('مدير الوثائق المنفّذ', 'Executing Records Manager'),
         'execution.reference': ('مرجع التنفيذ', 'Execution reference'),
         'membership.checksum': ('بصمة العضوية', 'Membership checksum')}, 'proposals', (
            {'proposal.serial_number': ('الرقم التسلسلي', 'No.'),
             'proposal.id': ('معرّف المقترح', 'Proposal identifier'),
             'proposal.change': ('التغيير المنفّذ', 'Executed change'),
             'proposal.action': ('الإجراء', 'Action'), 'proposal.target': ('العنصر المستهدف', 'Target resource'),
             'proposal.proposer': ('صاحب المقترح الأصلي', 'Original proposer')},
            {'proposal.result': ('نتيجة التنفيذ', 'Execution result'),
             'proposal.executor': ('المنفّذ ودوره', 'Executor and acting role'),
             'proposal.reason': ('السبب المستخدم ومصدره', 'Applied reason and its source')},
            {'proposal.removed_units': ('الوحدات المستبعدة بسبب المقترح', 'Units removed because of this proposal'),
             'proposal.history': ('مراجع سجل تغييرات المقترح', 'Preserved proposal history references')},
        ), ('job.id','job.type','job.created_at','execution.reference','membership.checksum','proposal.id','proposal.history'),
        (('aggregations', {
            'aggregation.serial_number': ('الرقم التسلسلي', 'No.'),
            'aggregation.number': ('رقم الملف', 'Aggregation number'),
            'aggregation.title': ('عنوان الملف', 'Aggregation title'),
            'aggregation.from_year': ('من سنة', 'From Year'),
            'aggregation.to_year': ('إلى سنة', 'To Year'),
            'aggregation.classification_code': ('رقم التصنيف', 'Classification number'),
            'aggregation.records': ('إجمالي الوثائق', 'Total records'),
            'aggregation.assigned_location': ('الموقع المعيّن', 'Assigned location'),
        }),)),
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


def group_fields(contract):
    return {**({contract.group: row_fields(contract)} if contract.group else {}), **dict(contract.extra_groups)}
