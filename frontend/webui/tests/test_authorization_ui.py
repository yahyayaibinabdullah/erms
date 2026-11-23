from frontend.webui.authorization_ui import (
    OPERATIONS, acl_source_label, aggregation_reference_label, authorization_code_label,
    decision_code_label, denied_gate, operation_label, gate_detail, ordered_permission_catalogue,
    privilege_help_text, privilege_matches_search, security_level_label,
)


def test_operation_catalogue_covers_resource_and_component_actions():
    assert "aggregation.security_level.change" in OPERATIONS["aggregation"]
    assert "record.component.replace" in OPERATIONS["record"]
    assert operation_label("record.component.download") == "Download Digital Component"
    assert authorization_code_label("aggregation.add_record") == "Add Record"
    assert authorization_code_label("record.create") == "Create Records"
    assert authorization_code_label("record.component.replace") == "Replace Digital Component"
    assert security_level_label({
        "code": "S", "name": "Secret", "level_number": 50,
    }).replace("\u2068", "").replace("\u2069", "") == "S — Secret (level 50)"
    assert security_level_label(None) == "None"


def test_acl_source_and_first_denial_are_explained():
    assert acl_source_label({"source": "parent_default", "source_resource_id": 42}) == "Parent Default"
    assert acl_source_label({"effective_acl_source": "parent_default"}) == "Parent Default"
    assert acl_source_label({"effective_acl_source": "parent_mirror:resource_override"}) == (
        "Parent Mirrored ACL"
    )
    assert aggregation_reference_label({"aggregation_number": "GCS-001", "title": "Board papers"}) == (
        "GCS-001 — Board papers"
    )
    explanation = {
        "gates": [
            {"gate": "global_privilege", "passed": True},
            {"gate": "security_clearance", "passed": False},
        ]
    }
    assert denied_gate(explanation)["gate"] == "security_clearance"


def test_integrity_gate_uses_business_language():
    assert gate_detail({"gate": "operation_integrity", "passed": True}) == (
        "The resource's current state permits this operation."
    )
    assert "ancestor" in gate_detail({
        "gate": "operation_integrity", "passed": False,
        "detail": "resource_is_effectively_closed",
    })


def test_permissions_use_task_order_instead_of_alphabetical_order():
    catalogue = [
        {"code": "aggregation.reopen"}, {"code": "aggregation.add_record"},
        {"code": "aggregation.delete"}, {"code": "aggregation.view"},
        {"code": "aggregation.modify_metadata"}, {"code": "aggregation.add_child"},
    ]
    assert [item["code"] for item in ordered_permission_catalogue(catalogue, "aggregation")] == [
        "aggregation.view", "aggregation.modify_metadata", "aggregation.delete",
        "aggregation.add_child", "aggregation.add_record", "aggregation.reopen",
    ]


def test_profile_privilege_help_uses_accessible_business_language():
    assert "classification schemes" in privilege_help_text("classifications.administer")
    assert "login sessions" in privilege_help_text("identity.sessions.administer")
    assert "Security operations" in privilege_help_text("audit.view")
    assert "Aggregations page" in privilege_help_text("aggregation.view")
    assert "closed aggregation" in privilege_help_text("closure.correct_record_placement")


def test_security_decisions_use_business_labels():
    assert decision_code_label("insufficient_privilege") == (
        "Required system privilege is missing"
    )
    assert decision_code_label("insufficient_resource_permission") == (
        "Resource ACL permission is missing"
    )
    assert decision_code_label(None) == "—"


def test_profile_privilege_search_covers_code_name_and_guidance():
    privilege = {
        "code": "audit.view",
        "name": "View audit trail",
        "description": "Review recorded events",
    }
    assert privilege_matches_search(privilege, "audit.view")
    assert privilege_matches_search(privilege, "recorded events")
    assert privilege_matches_search(privilege, "Security operations")
    assert not privilege_matches_search(privilege, "create records")


def test_acl_permission_and_source_labels_use_arabic_catalogue():
    import json
    from pathlib import Path
    from frontend.webui.i18n_catalogue import set_active_messages
    from frontend.webui.authorization_ui import PERMISSION_DISPLAY_ORDER
    artifact = json.loads((Path(__file__).parents[1] / "i18n/messages.ar.generated.json").read_text())
    messages = {item["message_key"]: item["translated_text"] for item in artifact["items"]}
    set_active_messages(messages)
    try:
        for codes in PERMISSION_DISPLAY_ORDER.values():
            for code in codes:
                assert operation_label(code) == messages["authorization.permission." + code]
        assert acl_source_label({"source": "resource_override"}) == "تجاوز محلي"
        assert acl_source_label({"source": "parent_mirror:resource_override"}) == messages["authorization.acl_source.parent_mirror"]
    finally:
        set_active_messages({})


def test_access_explanation_uses_arabic_catalogue_for_gates_and_decisions():
    import json
    from pathlib import Path
    from frontend.webui.i18n_catalogue import set_active_messages
    from frontend.webui.authorization_ui import GATE_LABELS, DECISION_CODE_LABELS, gate_label
    artifact = json.loads((Path(__file__).parents[1] / 'i18n/messages.ar.generated.json').read_text())
    messages = {item['message_key']: item['translated_text'] for item in artifact['items']}
    set_active_messages(messages)
    try:
        for code in GATE_LABELS:
            assert gate_label(code) == messages['authorization.explanation.gate.' + code]
        for code in DECISION_CODE_LABELS:
            assert decision_code_label(code) == messages['authorization.explanation.decision.' + code]
        assert gate_detail({'gate': 'resource_type', 'passed': True, 'detail': 'everyone'}) == messages['webui.render_principals.label.everyone_8d69f084']
        assert gate_detail({'gate': 'authentication', 'code': 'allowed', 'passed': True}) == 'مسموح'
        assert gate_detail({'gate': 'operation_integrity', 'passed': True}) == messages['authorization.explanation.state_allowed']
        assert 'سري' in security_level_label({'code': 'S', 'name': 'Secret', 'localized': {'name': 'سري'}, 'level_number': 75})
    finally:
        set_active_messages({})
