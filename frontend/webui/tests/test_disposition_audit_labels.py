"""Eligibility events use shared labels, including existing stored events."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from frontend.webui.event_labels import event_label

ROOT=Path(__file__).parents[3]


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
    operations=['DISPOSITION_UNIT_DESTROYED','DISPOSITION_PARTIALLY_DISPOSED','DISPOSITION_PARTIAL_RESOLVED','DISPOSITION_PARTIAL_BULK_RESOLVED','DISPOSITION_TERMINATION_OUTCOMES','PHYSICAL_DESTRUCTION_CONFIRMED','PHYSICAL_WORK_CHECKED','DISPOSITION_EMAIL_REQUESTED','DISPOSITION_EMAIL_OUTCOME','DESTRUCTION_REQUEST_GENERATED','DESTRUCTION_REQUEST_PENDING','EXTERNAL_APPROVAL_RECORDED','EXTERNAL_REJECTION_RECORDED','REVIEW_APPROVAL_INVALIDATED','REVIEW_PROPOSALS_APPROVED','REVIEW_PROPOSAL_EXECUTED','REVIEW_EXECUTION_REPORT_PENDING','REVIEW_SAVE','REVIEW_PROPOSAL_CREATED','REVIEW_PROPOSAL_REVISED','REVIEW_PROPOSAL_WITHDRAWN','REVIEW_PROPOSAL_CARRIED','REVIEW_NOTES_SAVED','TASK_CLAIM','TASK_RELEASE','TASK_REASSIGN','TASK_COMPLETE','TASK_ROUTED','REVIEW_SUBMIT','REVIEW_DECIDE','DOCUMENT_SAVE','ARTIFACT_SAVED','EVIDENCE_CORRECTED','JOB_CREATE','JOB_ASSIGN','JOB_OWNER_CHANGE','MEMBERSHIP_ADD','MEMBERSHIP_REMOVE',
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
