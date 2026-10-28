"""Eligibility events use shared labels, including existing stored events."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from frontend.webui.event_labels import event_label

ROOT=Path(__file__).parents[3]


@pytest.fixture(params=['en','ar'])
def audit_catalogue(request,monkeypatch):
    path=ROOT/'frontend/webui/i18n'/('messages.en.json' if request.param=='en' else 'messages.ar.generated.json')
    rows=json.loads(path.read_text())
    if isinstance(rows,dict):rows=rows['items']
    catalogue={r['message_key']:r['default_text' if request.param=='en' else 'translated_text'] for r in rows}
    monkeypatch.setattr('frontend.webui.event_labels.render_message',catalogue.__getitem__)
    monkeypatch.setattr('frontend.webui.audit_labels.render_message_plain',catalogue.__getitem__)
    return catalogue


@pytest.mark.parametrize('entity,before,after,key',[
    ('disposition_task',{'task_type':'digital_destruction','task_state':'claimed'},
     {'task_type':'digital_destruction','task_state':'completed'},'audit.event.digital_destruction_task_completed'),
    ('disposition_job',{'lifecycle_state':'active','workflow_stage':'digital_destruction'},
     {'lifecycle_state':'completed','workflow_stage':'certificate_generation'},'audit.event.disposition_job_completion_recorded'),
    ('disposition_task',None,{'task_type':'certificate_download','task_state':'open'},'audit.event.certificate_task_created'),
    ('disposition_task',{'task_type':'certificate_download','task_state':'open'},
     {'task_type':'certificate_download','task_state':'completed'},'audit.event.certificate_task_completed'),
    ('disposition_job',{'lifecycle_state':'active'},
     {'lifecycle_state':'completed'},'audit.event.disposition_job_completion_recorded'),
    ('disposition_job',{'lifecycle_state':'active','workflow_stage':'digital_destruction'},
     {'lifecycle_state':'active','workflow_stage':'certificate_generation'},'audit.event.certificate_stage_started'),
])
@pytest.mark.parametrize('top_level',[False,True])
def test_completion_labels_describe_old_and_current_recorded_changes(audit_catalogue,entity,before,after,key,top_level):
    event={'operation':'FINAL_COMPLETE','entity_type':entity,'metadata':{}}
    if top_level:event.update(before_state=before,after_state=after)
    else:event['metadata'].update(before=before,after=after)
    original=deepcopy(event)
    assert event_label(event['operation'],event=event)==audit_catalogue[key]
    assert event==original


@pytest.mark.parametrize('event',[
    {},
    {'entity_type':'disposition_task','metadata':{}},
    {'entity_type':'disposition_task','metadata':{'after':{'task_type':'certificate_download','task_state':'open'}}},
    {'entity_type':'disposition_task','metadata':{'after':{'task_type':'certificate_download','task_state':'completed'}}},
    {'entity_type':'disposition_job','after_state':{'lifecycle_state':'completed'}},
    {'entity_type':'disposition_job','metadata':{'after':{'workflow_stage':'certificate_generation'}}},
    {'entity_type':'disposition_task','metadata':{'after':{'task_type':'certificate_download','task_state':'completed'},'redacted':True}},
    {'entity_type':'disposition_job','before_state':{'lifecycle_state':'active'},'after_state':{'lifecycle_state':'completed'},'metadata':{'redacted':True}},
    {'entity_type':'disposition_task','metadata':{'before':{'task_type':'certificate_download','task_state':'completed'},'after':{'task_type':'certificate_download','task_state':'completed'}}},
])
def test_redacted_incomplete_and_unchanged_events_do_not_invent_outcomes(audit_catalogue,event):
    assert event_label('FINAL_COMPLETE',event=event)==audit_catalogue['audit.event.final_completion_recorded']
    assert event_label('FINAL_COMPLETE')==audit_catalogue['audit.event.final_completion_recorded']


def test_business_outcome_and_final_task_completion_keep_distinct_labels(audit_catalogue):
    assert event_label('DESTRUCTION_JOB_COMPLETED')==audit_catalogue['audit.event.destruction_job_completed']
    assert event_label('CERTIFICATE_TASK_COMPLETED')==audit_catalogue['audit.event.certificate_task_completed']
    assert event_label('INTEGRATION_UNKNOWN')=='INTEGRATION_UNKNOWN'


def test_global_subject_names_are_localized_and_identifiers_stay_technical(audit_catalogue):
    from frontend.webui.audit_labels import audit_entity_type_label,disposition_event_identity
    job={'entity_type':'disposition_job','entity_id':1,'metadata':{'after':{'job_number':'DT-2026-1'}}}
    task={'entity_type':'disposition_task','entity_id':7,'metadata':{'after':{'job_id':1,'task_type':'certificate_download'}},'display_references':{'job:1':'DT-2026-1'}}
    assert disposition_event_identity(job)==(audit_catalogue['audit.entity.disposition_job'],'DT-2026-1')
    assert disposition_event_identity(task)==(audit_catalogue['audit.entity.disposition_task'],'DT-2026-1')
    task['metadata']['redacted']=True
    assert disposition_event_identity(task)==(audit_catalogue['audit.entity.disposition_task'],'')
    assert audit_entity_type_label('disposition_task')==audit_catalogue['audit.entity.disposition_task']


@pytest.mark.parametrize('language',['en','ar'])
def test_disposition_audit_operations_have_contextual_labels(language):
    definitions=json.loads((ROOT/'frontend/webui/i18n/messages.en.json').read_text())
    if language=='en': catalogue={r['message_key']:r['default_text'] for r in definitions}
    else: catalogue={r['message_key']:r['translated_text'] for r in json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}
    with patch('frontend.webui.event_labels.render_message',side_effect=catalogue.__getitem__):
        assert event_label('DISPOSITION_ELIGIBILITY_EVALUATED')==catalogue['audit.event.disposition_eligibility_evaluated']
        assert event_label('DISPOSITION_STATUS_CHANGED')==catalogue['audit.event.disposition_status_changed']


@pytest.mark.parametrize('language',['en','ar'])
def test_membership_recalculation_and_acceleration_use_shared_readable_labels(language):
    from frontend.webui.event_labels import EVENT_MESSAGE_KEYS
    operations=['DIGITAL_DESTRUCTION_REQUESTED','DIGITAL_DESTRUCTION_FAILED','DIGITAL_DESTRUCTION_UNIT_COMPLETED','DIGITAL_DESTRUCTION_SUCCEEDED','DIGITAL_DESTRUCTION_PROGRESS','DISPOSITION_RETAINED_RECORD_MIGRATED','DISPOSITION_UNIT_DESTROYED','DISPOSITION_PARTIALLY_DISPOSED','DISPOSITION_PARTIAL_RESOLVED','DISPOSITION_PARTIAL_BULK_RESOLVED','DISPOSITION_TERMINATION_OUTCOMES','PHYSICAL_DESTRUCTION_CONFIRMED','PHYSICAL_WORK_CHECKED','DISPOSITION_EMAIL_REQUESTED','DISPOSITION_EMAIL_OUTCOME','DESTRUCTION_REQUEST_GENERATED','DESTRUCTION_REQUEST_PENDING','EXTERNAL_APPROVAL_RECORDED','EXTERNAL_REJECTION_RECORDED','REVIEW_APPROVAL_INVALIDATED','REVIEW_PROPOSALS_APPROVED','REVIEW_PROPOSAL_EXECUTED','REVIEW_EXECUTION_REPORT_PENDING','REVIEW_SAVE','REVIEW_PROPOSAL_CREATED','REVIEW_PROPOSAL_REVISED','REVIEW_PROPOSAL_WITHDRAWN','REVIEW_PROPOSAL_CARRIED','REVIEW_NOTES_SAVED','TASK_CLAIM','TASK_RELEASE','TASK_REASSIGN','TASK_COMPLETE','TASK_ROUTED','REVIEW_SUBMIT','REVIEW_DECIDE','DOCUMENT_SAVE','ARTIFACT_SAVED','EVIDENCE_CORRECTED','JOB_CREATE','JOB_ASSIGN','JOB_OWNER_CHANGE','MEMBERSHIP_ADD','MEMBERSHIP_REMOVE',
                'JOB_TERMINATE','DISPOSITION_ACCELERATED','DISPOSITION_RECALCULATED',
                'DISPOSITION_REOPENED','DISPOSITION_REMOVAL_REQUIRED']
    if language=='en':
        catalogue={r['message_key']:r['default_text'] for r in json.loads((ROOT/'frontend/webui/i18n/messages.en.json').read_text())}
    else:
        catalogue={r['message_key']:r['translated_text'] for r in json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}
    with patch('frontend.webui.event_labels.render_message',side_effect=catalogue.__getitem__):
        for operation in operations:
            assert event_label(operation)==catalogue[EVENT_MESSAGE_KEYS[operation]]
            assert event_label(operation)!=operation
