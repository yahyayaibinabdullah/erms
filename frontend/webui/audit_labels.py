"""Localized audit entity labels; technical filter values remain unchanged."""
from .i18n_catalogue import render_message_plain


def audit_entity_type_label(value: str) -> str:
    labels = {
        'application_setting': render_message_plain('audit.entity.application_setting'),
        'disposition_job': render_message_plain('audit.entity.disposition_job'),
        'disposition_task': render_message_plain('audit.entity.disposition_task'),
        'aggregation': render_message_plain('dashboard.resource.aggregation'),
        'record': render_message_plain('dashboard.resource.record'),
        'classification': render_message_plain('entity_metadata.field.classification'),
        'classification_scheme': render_message_plain('entity_metadata.field.classification_scheme'),
        'org_unit': render_message_plain('entity_metadata.field.organization_unit'),
        'user': render_message_plain('entity_metadata.field.user'),
        'role': render_message_plain('entity_metadata.field.role'),
        'security_level': render_message_plain('entity_metadata.field.security_level'),
        'profile': render_message_plain('entity_metadata.field.profile'),
        'privilege': render_message_plain('authorization.explanation.gate.global_privilege'),
        'profile_privilege': render_message_plain('entity_metadata.field.profile') + " — " + render_message_plain('webui.render_governance_cards.text.privileges_228b97c0'),
        'digital_component': render_message_plain('privilege.category.component'),
        'classification_retention_rule': render_message_plain('entity_metadata.field.classification') + " — " + render_message_plain('classification_transfer.retention_rule'),
        'aggregation_retention_rule': render_message_plain('dashboard.resource.aggregation') + " — " + render_message_plain('classification_transfer.retention_rule'),
        'aggregation_acl_grant': render_message_plain('dashboard.resource.aggregation') + " — " + render_message_plain('authorization.explanation.gate.resource_acl'),
        'record_acl_grant': render_message_plain('dashboard.resource.record') + " — " + render_message_plain('authorization.explanation.gate.resource_acl'),
        'aggregation_child_aggregation_acl_default': render_message_plain('webui.show_acl_editor.text.default_child_aggregation_acl_bdf05df3'),
        'aggregation_child_record_acl_default': render_message_plain('webui.show_acl_editor.text.default_child_record_acl_316d787d'),
        'hold': render_message_plain('webui.add_resource_to_hold_dialog.select.hold_77a90801'),
        'hold_contributor': render_message_plain('webui.add_resource_to_hold_dialog.select.hold_77a90801') + " — " + render_message_plain('webui.select_hold_details.label.contributors_008a0e27'),
        'hold_aggregation_assignment': render_message_plain('webui.select_hold_details.label.held_items_244f35b3') + " — " + render_message_plain('dashboard.resource.aggregation'),
        'hold_record_assignment': render_message_plain('webui.select_hold_details.label.held_items_244f35b3') + " — " + render_message_plain('dashboard.resource.record'),
        'user_role_assignment': render_message_plain('webui.select_user_details.label.role_assignments_f60546c5'),
        'saved_search': render_message_plain('webui.select_advanced_search.label.saved_search_6ccb135c'),
        'supported_language': render_message_plain('webui.select_translation_administration.label.supported_languages_0a3fd31a'),
        'ui_message_definition': render_message_plain('navigation.item.translations') + " — " + render_message_plain('webui.select_translation_administration.input.key_16b82d81'),
        'ui_message_translation': render_message_plain('navigation.item.translations') + " — " + render_message_plain('webui.select_translation_administration.input.translated_text_054048b6'),
        'user_preference': render_message_plain('preferences.heading.personal'),
        'login_session': render_message_plain('navigation.item.login_sessions'),
    }
    return labels.get(value, value.replace("_", " ").title())


def disposition_event_identity(event: dict) -> tuple[str, str]:
    """Readable job/task subject without exposing internal IDs or redacted facts."""
    entity_type = event['entity_type']
    heading = audit_entity_type_label(entity_type)
    metadata = event.get('metadata') or {}
    if metadata.get('redacted'):
        return heading, ''
    snapshot = event.get('after_state') or event.get('before_state') or metadata.get('after') or metadata.get('before') or {}
    job_id = event['entity_id'] if entity_type == 'disposition_job' else snapshot.get('job_id') or metadata.get('job_id')
    identity = snapshot.get('job_number') or (event.get('display_references') or {}).get(f'job:{job_id}') or ''
    return heading, identity
