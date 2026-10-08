from __future__ import annotations

from typing import Any

from .i18n_catalogue import render_message


OPERATIONS = {
    "aggregation": (
        "aggregation.view", "aggregation.modify_metadata", "aggregation.delete",
        "aggregation.close", "aggregation.reopen", "aggregation.move",
        "aggregation.reclassify", "aggregation.security_level.change",
        "aggregation.vital_status.change",
        "aggregation.location.change",
        "aggregation.review_date.change",
        "aggregation.acl.manage", "aggregation.add_child", "aggregation.add_record",
    ),
    "record": (
        "record.view", "record.modify_metadata", "record.delete", "record.move",
        "record.security_level.change", "record.acl.manage", "record.component.list",
        "record.vital_status.change",
        "record.review_date.change",
        "record.component.view", "record.component.download", "record.component.add",
        "record.component.replace", "record.component.remove", "record.component.reorder",
    ),
}


PERMISSION_DISPLAY_ORDER = {
    "aggregation": (
        "aggregation.view", "aggregation.modify_metadata", "aggregation.delete",
        "aggregation.add_child", "aggregation.add_record", "aggregation.close",
        "aggregation.reopen", "aggregation.move", "aggregation.receive_child",
        "aggregation.receive_record", "aggregation.reclassify",
        "aggregation.security_level.change", "aggregation.history.view",
        "aggregation.acl.manage", "aggregation.vital_status.change",
        "aggregation.location.change",
        "aggregation.review_date.change",
    ),
    "record": (
        "record.view", "record.modify_metadata", "record.delete", "record.move",
        "record.component.list", "record.component.view", "record.component.download",
        "record.component.add", "record.component.replace", "record.component.remove",
        "record.component.reorder", "record.component.share", "record.component.print",
        "record.history.view", "record.security_level.change", "record.vital_status.change", "record.review_date.change", "record.acl.manage",
    ),
}


GATE_LABELS = {
    "authentication": "Authentication and account state",
    "effective_roles": "Effective role assignment",
    "operation_integrity": "Resource state rules",
    "global_privilege": "Global privilege",
    "security_clearance": "Security clearance",
    "resource_acl": "Resource ACL",
}


AUTHORIZATION_CODE_LABELS = {
    "aggregation.view": "View Aggregation",
    "aggregation.modify": "Modify Aggregations",
    "aggregation.modify_metadata": "Modify Metadata",
    "aggregation.delete": "Delete Aggregation",
    "aggregation.close": "Close Aggregation",
    "aggregation.reopen": "Reopen Aggregation",
    "aggregation.move": "Move Aggregation",
    "aggregation.reclassify": "Reclassify Aggregation",
    "aggregation.security_level.change": "Change Security Level",
    "aggregation.vital_status.change": "Change Vital Status",
    "aggregation.location.change": "Change Location",
    "aggregation.review_date.change": "Change Next Review",
    "aggregation.acl.manage": "Manage ACL",
    "aggregation.create_child": "Create Child Aggregations",
    "aggregation.add_child": "Add Child Aggregation",
    "aggregation.add_record": "Add Record",
    "aggregation.receive_child": "Receive Child Aggregation",
    "aggregation.receive_record": "Receive Record",
    "aggregation.history.view": "View Event History",
    "record.view": "View Record",
    "record.modify": "Modify Records",
    "record.modify_metadata": "Modify Metadata",
    "record.delete": "Delete Record",
    "record.create": "Create Records",
    "record.move": "Move Record",
    "record.security_level.change": "Change Security Level",
    "record.vital_status.change": "Change Vital Status",
    "record.review_date.change": "Change Next Review",
    "record.acl.manage": "Manage ACL",
    "record.history.view": "View Event History",
    "record.component.list": "List Digital Components",
    "record.component.view": "View Digital Component",
    "record.component.download": "Download Digital Component",
    "record.component.add": "Add Digital Component",
    "record.component.replace": "Replace Digital Component",
    "record.component.remove": "Remove Digital Component",
    "record.component.reorder": "Reorder Digital Components",
    "record.component.share": "Share Digital Component",
    "record.component.print": "Print Digital Component",
    "record.component.reindex": "Reindex Digital Component",
}


PRIVILEGE_HELP = {
    'relationships.administer': 'Maintain aggregation and record relationship catalogues.',
    'relationships.link': 'Create and remove named links between resources you can view.',
    "authorization.administer": "Create and maintain authorization profiles and their privilege assignments. Shows the Profiles and Governance custody pages in navigation.",
    "authorization.explain": "Inspect why a person is allowed or denied an operation on protected information.",
    "security_levels.administer": "Create and maintain the security levels used for roles, aggregations, and records. Shows the Security levels page in navigation.",
    "identity.users.administer": "Create and manage person and service accounts, including their lifecycle state. Shows the Users page in navigation.",
    "identity.sessions.administer": "Review and revoke active login sessions. Shows the Login sessions page in navigation.",
    "organization.browse": "Browse the organization hierarchy and view concise organization-unit, role, and user summaries. Shows Browse under Organization Structure.",
    "organization.administer": "Create and manage organization units, roles, and role assignments. Shows the Organization units and Roles pages in navigation.",
    "classifications.administer": "Create, publish, update, deactivate, and otherwise manage classification schemes and classifications. Shows the Classification schemes page in navigation.",
    "audit.view": "View the system audit trail and its recorded security and business events. Shows the Audit trail and Security operations pages in navigation.",
    "aggregation.view": "Open aggregations and view their metadata, subject to clearance and the resource ACL. Shows the Aggregations page in navigation.",
    "aggregation.create_root": "Create a new top-level aggregation.",
    "aggregation.create_child": "Create an aggregation beneath an existing aggregation when its ACL also permits it.",
    "aggregation.modify": "Change aggregation metadata when its ACL also permits modification.",
    "aggregation.move": "Move an aggregation to another permitted parent aggregation.",
    "aggregation.reclassify": "Assign an aggregation to a different classification where policy permits it.",
    "aggregation.close": "Close an aggregation so its normal contents and metadata can no longer be changed.",
    "aggregation.reopen": "Reopen a closed aggregation when an authorized correction requires it.",
    "aggregation.delete": "Permanently delete an aggregation when all deletion conditions are satisfied.",
    "aggregation.security_level.change": "Change an aggregation's security level within the caller's clearance and hierarchy rules.",
    "aggregation.vital_status.change": "Mark an aggregation as vital or no longer vital, with a recorded reason.",
    "aggregation.location.change": "Change an aggregation's assigned or current physical location, with a recorded reason.",
    "aggregation.acl.manage": "Change which roles receive permissions through an aggregation's ACL and child defaults.",
    "record.view": "Open records and view their metadata, subject to clearance and the resource ACL. Shows the Records page in navigation.",
    "record.create": "Create a record in an aggregation whose ACL accepts it.",
    "record.modify": "Change record metadata when its ACL also permits modification.",
    "record.move": "Move a record to another permitted aggregation.",
    "record.delete": "Permanently delete a record when all deletion conditions are satisfied.",
    "record.security_level.change": "Change a record's security level within the caller's clearance and hierarchy rules.",
    "record.vital_status.change": "Mark a record as vital or no longer vital, with a recorded reason.",
    "record.acl.manage": "Change which roles receive permissions through a record's ACL.",
    "record.component.view": "Open and preview digital components attached to a record.",
    "record.component.download": "Download digital components attached to a record.",
    "record.component.add": "Upload a new digital component to a record.",
    "record.component.replace": "Atomically replace a digital component while preserving the replacement audit trail.",
    "record.component.remove": "Remove a digital component from a record.",
    "record.component.reorder": "Change the display order of a record's digital components.",
    "record.component.share": "Share a digital component through a supported sharing workflow.",
    "record.component.print": "Print a digital component through a supported printing workflow.",
    "record.component.reindex": "Request asynchronous extraction and search indexing for authorized component content.",
    "security.resource.downgrade": "Lower a resource's security level after the required checks and audit reason.",
    "closure.correct_record_placement": "Correct record placement inside a closed aggregation without resetting its retention clock.",
    "authorization.recovery": "Perform explicitly controlled recovery when ordinary authorization administration cannot restore access.",
}


DECISION_CODE_LABELS = {
    "allowed": "Allowed",
    "authentication_required": "Authentication is required",
    "session_revoked": "Login session was revoked",
    "session_expired": "Login session expired",
    "user_inactive": "Account is inactive",
    "user_suspended": "Account is suspended",
    "user_locked": "Account is locked",
    "no_effective_role": "No effective role assignment",
    "insufficient_privilege": "Required system privilege is missing",
    "insufficient_clearance": "Security clearance is too low",
    "insufficient_resource_permission": "Resource ACL permission is missing",
    "operation_not_allowed": "Operation is not allowed in the current state",
    "resource_not_found": "Resource is unavailable",
    "unspecified": "Reason was not recorded",
}


def privilege_help_text(code: str, fallback: str | None = None) -> str:
    """Explain a global privilege in business language suitable for UI guidance."""
    return PRIVILEGE_HELP.get(code, fallback or f"Controls the {code} capability.")


def privilege_matches_search(privilege: dict[str, Any], query: str) -> bool:
    """Match privilege code, name, stored description, and accessible UI help."""
    needle = query.strip().casefold()
    if not needle:
        return True
    searchable = " ".join((
        str(privilege.get("code") or ""),
        str(privilege.get("name") or ""),
        str(privilege.get("description") or ""),
        privilege_help_text(privilege.get("code") or "", privilege.get("description")),
    )).casefold()
    return needle in searchable


def decision_code_label(code: str | None) -> str:
    if not code:
        return "—"
    return localized_decision_label(code)


PERMISSION_MESSAGE_KEYS = {
    "aggregation.acl.manage": "authorization.permission.aggregation.acl.manage",
    "aggregation.add_child": "authorization.permission.aggregation.add_child",
    "aggregation.add_record": "authorization.permission.aggregation.add_record",
    "aggregation.close": "authorization.permission.aggregation.close",
    "aggregation.delete": "authorization.permission.aggregation.delete",
    "aggregation.history.view": "authorization.permission.aggregation.history.view",
    "aggregation.location.change": "authorization.permission.aggregation.location.change",
    "aggregation.modify_metadata": "authorization.permission.aggregation.modify_metadata",
    "aggregation.move": "authorization.permission.aggregation.move",
    "aggregation.receive_child": "authorization.permission.aggregation.receive_child",
    "aggregation.receive_record": "authorization.permission.aggregation.receive_record",
    "aggregation.reclassify": "authorization.permission.aggregation.reclassify",
    "aggregation.reopen": "authorization.permission.aggregation.reopen",
    "aggregation.review_date.change": "authorization.permission.aggregation.review_date.change",
    "aggregation.security_level.change": "authorization.permission.aggregation.security_level.change",
    "aggregation.view": "authorization.permission.aggregation.view",
    "aggregation.vital_status.change": "authorization.permission.aggregation.vital_status.change",
    "record.acl.manage": "authorization.permission.record.acl.manage",
    "record.component.add": "authorization.permission.record.component.add",
    "record.component.download": "authorization.permission.record.component.download",
    "record.component.list": "authorization.permission.record.component.list",
    "record.component.print": "authorization.permission.record.component.print",
    "record.component.remove": "authorization.permission.record.component.remove",
    "record.component.reorder": "authorization.permission.record.component.reorder",
    "record.component.replace": "authorization.permission.record.component.replace",
    "record.component.share": "authorization.permission.record.component.share",
    "record.component.view": "authorization.permission.record.component.view",
    "record.delete": "authorization.permission.record.delete",
    "record.history.view": "authorization.permission.record.history.view",
    "record.modify_metadata": "authorization.permission.record.modify_metadata",
    "record.move": "authorization.permission.record.move",
    "record.review_date.change": "authorization.permission.record.review_date.change",
    "record.security_level.change": "authorization.permission.record.security_level.change",
    "record.view": "authorization.permission.record.view",
    "record.vital_status.change": "authorization.permission.record.vital_status.change",
}

ACL_SOURCE_MESSAGE_KEYS = {
    "resource_override": "authorization.acl_source.resource_override",
    "parent_custom_default": "authorization.acl_source.parent_custom_default",
    "parent_default": "authorization.acl_source.parent_default",
    "mirror_resource_acl": "authorization.acl_source.mirror_resource_acl",
    "custom": "authorization.acl_source.custom",
    "local": "authorization.acl_source.local",
    "parent_mirror": "authorization.acl_source.parent_mirror",
}

def operation_label(code: str) -> str:
    if code in PERMISSION_MESSAGE_KEYS:
        return render_message(PERMISSION_MESSAGE_KEYS[code])
    return code.split(".", 1)[-1].replace("_", " ").replace(".", " · ").title()


def authorization_code_label(code: str) -> str:
    """Return a concise business label while retaining the code for diagnostics."""
    return AUTHORIZATION_CODE_LABELS.get(
        code,
        code.replace("_", " ").replace(".", " · ").title(),
    )


def security_level_label(level: dict[str, Any] | None) -> str:
    if not level:
        return render_message("authorization.explanation.no_clearance")
    return render_message(
        "authorization.explanation.security_level",
        code=level.get("code") or "—",
        name=(level.get("localized") or {}).get("name") or level.get("name") or "—",
        level=level.get("level_number", "—"),
    )


def ordered_permission_catalogue(
    catalogue: list[dict[str, Any]], resource_type: str,
) -> list[dict[str, Any]]:
    rank = {code: index for index, code in enumerate(PERMISSION_DISPLAY_ORDER[resource_type])}
    return sorted(catalogue, key=lambda item: (rank.get(item["code"], len(rank)), item["code"]))


def acl_source_label(acl: dict[str, Any]) -> str:
    source = str(acl.get("source") or acl.get("effective_acl_source") or "local")
    if source.startswith("parent_mirror:"):
        source = "parent_mirror"
    if source in ACL_SOURCE_MESSAGE_KEYS:
        return render_message(ACL_SOURCE_MESSAGE_KEYS[source])
    return source.replace("_", " ").title()


def aggregation_reference_label(aggregation: dict[str, Any]) -> str:
    number = aggregation.get("aggregation_number") or "Aggregation"
    title = aggregation.get("title") or aggregation.get("name") or "Untitled"
    return f"{number} — {title}"


def gate_detail(gate: dict[str, Any]) -> str:
    if gate.get("gate") == "operation_integrity":
        if gate.get("passed"):
            return render_message('authorization.explanation.state_allowed')
        if gate.get("detail") == "resource_is_effectively_closed":
            return render_message('authorization.explanation.state_closed')
        return render_message('authorization.explanation.state_denied')
    if gate.get("detail") == "information_governance_bypass":
        return render_message('authorization.explanation.bypass')
    if gate.get("gate") == "resource_acl" and gate.get("detail"):
        return "، ".join(operation_label(code.strip()) for code in gate["detail"].split(","))
    return decision_code_label(gate.get("code"))


def denied_gate(explanation: dict[str, Any]) -> dict[str, Any] | None:
    return next((gate for gate in explanation.get("gates", []) if not gate.get("passed")), None)


def gate_label(code: str) -> str:
    return {
        'authentication': render_message('authorization.explanation.gate.authentication'),
        'effective_roles': render_message('authorization.explanation.gate.effective_roles'),
        'operation_integrity': render_message('authorization.explanation.gate.operation_integrity'),
        'global_privilege': render_message('authorization.explanation.gate.global_privilege'),
        'security_clearance': render_message('authorization.explanation.gate.security_clearance'),
        'resource_acl': render_message('authorization.explanation.gate.resource_acl'),
    }.get(code, code)


def localized_decision_label(code: str) -> str:
    return {
        'allowed': render_message('authorization.explanation.decision.allowed'),
        'authentication_required': render_message('authorization.explanation.decision.authentication_required'),
        'session_revoked': render_message('authorization.explanation.decision.session_revoked'),
        'session_expired': render_message('authorization.explanation.decision.session_expired'),
        'user_inactive': render_message('authorization.explanation.decision.user_inactive'),
        'user_suspended': render_message('authorization.explanation.decision.user_suspended'),
        'user_locked': render_message('authorization.explanation.decision.user_locked'),
        'no_effective_role': render_message('authorization.explanation.decision.no_effective_role'),
        'insufficient_privilege': render_message('authorization.explanation.decision.insufficient_privilege'),
        'insufficient_clearance': render_message('authorization.explanation.decision.insufficient_clearance'),
        'insufficient_resource_permission': render_message('authorization.explanation.decision.insufficient_resource_permission'),
        'operation_not_allowed': render_message('authorization.explanation.decision.operation_not_allowed'),
        'resource_not_found': render_message('authorization.explanation.decision.resource_not_found'),
        'unspecified': render_message('authorization.explanation.decision.unspecified'),
    }.get(code, code)
