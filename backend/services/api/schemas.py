from datetime import datetime, timedelta
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
LocationCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _is_future(value: datetime) -> bool:
    now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
    return value > now


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecurityLevelCreate(ApiModel):
    code: NonBlankString
    name: NonBlankString
    level_number: int = Field(ge=0)
    prevents_disposition: bool = False
    description: str | None = None


class SecurityLevelUpdate(ApiModel):
    code: NonBlankString | None = None
    name: NonBlankString | None = None
    level_number: int | None = Field(default=None, ge=0)
    prevents_disposition: bool | None = None
    description: str | None = None


class SecurityLevelRead(SecurityLevelCreate):
    id: int
    date_created: datetime
    date_updated: datetime
    version: int
    roles_assigned_count: int = 0
    aggregation_count: int = 0
    record_count: int = 0
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class PrivilegeRead(ApiModel):
    id: int
    code: str
    name: str
    description: str
    category: str
    is_reserved: bool
    account_type_restriction: Literal["person", "service"] | None = None
    date_created: datetime
    date_updated: datetime
    version: int


class ProfileCreate(ApiModel):
    code: NonBlankString
    name: NonBlankString
    description: str | None = None


class ProfileUpdate(ApiModel):
    name: NonBlankString | None = None
    description: str | None = None


class ProfileRead(ApiModel):
    id: int
    code: str
    name: str
    description: str | None
    is_system: bool
    date_created: datetime
    date_updated: datetime
    version: int
    privilege_count: int = 0
    role_count: int = 0
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class ProfileReferenceRead(ProfileRead):
    grants_all_privileges: bool


class ProfilePrivilegeReplace(ApiModel):
    privilege_ids: list[int]


class RoleProfileAssignment(ApiModel):
    profile_id: int


class PermissionRead(ApiModel):
    id: int
    code: str
    name: str
    description: str
    resource_type: Literal["aggregation", "record"]
    date_created: datetime


class AclPrincipalGrant(ApiModel):
    principal_type: Literal["role", "everyone", "org_unit_members", "owning_and_higher_level_unit_managers", "effective_file_administrator"]
    role_id: int | None = None
    permission_codes: list[str]

    @model_validator(mode="after")
    def validate_principal(self):
        if (self.principal_type == "role") != (self.role_id is not None):
            raise ValueError("role_id is required only for role principals")
        return self


class AclReplace(ApiModel):
    version: int = Field(gt=0)
    grants: list[AclPrincipalGrant]
    inherit_acl_from_parent: bool | None = None
    initialize_override_from_inherited: bool = False
    reason: NonBlankString


class ChildAggregationAclReplace(ApiModel):
    version: int = Field(gt=0)
    mode: Literal["mirror_resource_acl", "custom"]
    grants: list[AclPrincipalGrant]
    initialize_custom_from_mirrored: bool = False
    reason: NonBlankString


class ChildRecordAclReplace(ApiModel):
    version: int = Field(gt=0)
    grants: list[AclPrincipalGrant]
    reason: NonBlankString


class AclPrincipalRead(ApiModel):
    principal_type: Literal["role", "everyone", "org_unit_members", "owning_and_higher_level_unit_managers", "effective_file_administrator"]
    role_id: int | None
    display_name: str
    role_code: str | None
    permission_codes: list[str]


class ResourceAclRead(ApiModel):
    inherit_acl_from_parent: bool
    effective_acl: list[AclPrincipalRead]
    effective_acl_source: str
    effective_acl_source_id: int
    override_acl: list[AclPrincipalRead]
    override_acl_is_dormant: bool
    resource_acl_version: int


class ChildAggregationAclRead(ApiModel):
    mode: Literal["mirror_resource_acl", "custom"]
    effective_acl: list[AclPrincipalRead]
    custom_acl: list[AclPrincipalRead]
    custom_acl_is_dormant: bool
    version: int
    affected_aggregation_ids: list[int]
    affected_aggregation_count: int
    affected_record_count: int


class ChildRecordAclRead(ApiModel):
    effective_acl: list[AclPrincipalRead]
    version: int
    affected_record_count: int


class AclChangePreviewRead(ApiModel):
    added_grants: int
    removed_grants: int
    potentially_affected_user_count: int
    affected_record_count: int
    version: int


class ChildAggregationAclChangePreviewRead(AclChangePreviewRead):
    mode: Literal["mirror_resource_acl", "custom"]
    affected_aggregation_ids: list[int]
    affected_aggregation_count: int


class ResourceCapabilitiesRead(ApiModel):
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    capabilities: dict[str, bool | int]
    capability_reasons: dict[str, str] = Field(default_factory=dict)


class AuthorizationGateRead(ApiModel):
    gate: str
    passed: bool
    code: str
    detail: str | None


class EffectiveAuthorizationRoleRead(ApiModel):
    role_id: int
    role_code: str
    role_name: str
    org_unit_id: int
    profile_id: int
    profile_code: str
    profile_name: str
    security_level_id: int
    security_level_code: str
    clearance: int
    is_information_governance: bool
    privileges: list[str]


class ExcludedAuthorizationRoleRead(ApiModel):
    role_id: int
    role_code: str
    reason: str


class AuthorizationSubjectRead(ApiModel):
    user_id: int | None
    effective_clearance: int | None
    effective_roles: list[EffectiveAuthorizationRoleRead]
    excluded_roles: list[ExcludedAuthorizationRoleRead]


class EffectiveAclGrantRowRead(ApiModel):
    id: int
    principal_type: Literal["role", "everyone", "org_unit_members", "owning_and_higher_level_unit_managers", "effective_file_administrator"]
    role_id: int | None
    role_code: str | None
    role_name: str | None
    permission_id: int
    permission_code: str


class AccessExplanationAclRead(ApiModel):
    contextual_matches: list[dict[str, Any]] = Field(default_factory=list)
    resource_type: Literal["aggregation", "record"]
    source: str
    source_resource_id: int
    inherit_acl_from_parent: bool
    effective_grants: list[EffectiveAclGrantRowRead]
    dormant_override_grants: list[EffectiveAclGrantRowRead]


class AccessContributorsRead(ApiModel):
    privilege_role_ids: list[int]
    clearance_role_ids: list[int]
    acl_role_ids_by_permission: dict[str, list[int]]
    everyone_permissions: list[str]
    org_unit_member_permissions: list[str]
    org_unit_member_role_ids_by_permission: dict[str, list[int]]
    governance_bypass_role_ids: list[int]


class AccessSecurityLevelRead(ApiModel):
    id: int
    code: str
    name: str
    level_number: int


class AccessExplanationRead(ApiModel):
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    operation: str
    selected_user_id: int
    other_user_diagnostic: bool
    allowed: bool
    decision_code: str
    gates: list[AuthorizationGateRead]
    contributors: AccessContributorsRead
    subject: AuthorizationSubjectRead
    acl: AccessExplanationAclRead
    required_privilege: str
    required_permission: str
    required_clearance: int | None
    effective_security_level: AccessSecurityLevelRead | None
    required_security_level: AccessSecurityLevelRead
    resource_state_constraints: list[dict[str, Any]] = Field(default_factory=list)


class ExplainableUserRead(ApiModel):
    id: int
    name: str
    email: str | None
    status: Literal["active", "inactive", "suspended"]


class CustodySecurityLevelRead(ApiModel):
    id: int
    code: str
    name: str
    level_number: int


class GovernanceRoleRead(ApiModel):
    id: int
    code: str
    name: str
    status: Literal["active", "inactive"]
    profile_id: int
    profile_code: str
    profile_name: str
    security_level_id: int
    security_level_code: str
    security_level_name: str
    level_number: int
    effective: bool
    current_assignee_count: int
    effective_assignee_count: int
    universal_custodian_count: int
    is_highest_clearance: bool
    has_required_custody_privileges: bool
    qualifies_for_universal_custody: bool
    missing_custody_privilege_codes: list[str]


class GovernanceAssignmentRead(ApiModel):
    id: int
    user_id: int
    user_name: str
    user_email: str | None
    user_status: Literal["active", "inactive", "suspended"]
    account_type: Literal["person", "service"]
    role_id: int
    role_code: str
    role_name: str
    valid_from: datetime
    valid_until: datetime | None
    role_effective: bool
    effective: bool
    effective_for_universal_custody: bool
    ineffective_reasons: list[str]


class GovernanceWarningRead(ApiModel):
    code: str
    severity: Literal["critical", "advisory"]


class GovernanceCustodyRead(ApiModel):
    security_levels: list[CustodySecurityLevelRead]
    highest_security_level: CustodySecurityLevelRead | None
    required_custody_privilege_codes: list[str]
    governance_roles: list[GovernanceRoleRead]
    assignments: list[GovernanceAssignmentRead]
    highest_clearance_custodian_count: int
    warnings: list[GovernanceWarningRead]


class SecurityEventCountRead(ApiModel):
    operation: str
    count: int
    last_seen_at: datetime


class SecurityDenialGroupRead(ApiModel):
    decision_code: str
    required_privilege: str
    count: int
    last_seen_at: datetime


class SecurityEventDetailRead(ApiModel):
    id: int
    occurred_at: datetime
    operation: str
    actor_user_id: int | None
    actor_name: str | None
    actor_email: str | None
    actor_type: str
    entity_type: str
    entity_id: int
    entity_label: str
    decision_code: str | None
    required_privilege: str | None
    redacted: bool


class FullPrivilegeProfileRoleRead(ApiModel):
    id: int
    code: str
    name: str
    status: str
    profile_code: str
    profile_name: str
    is_builtin_bootstrap_profile: bool


class SecurityOperationsSummaryRead(ApiModel):
    window_start: datetime
    window_end: datetime
    window_hours: int
    generated_at: datetime
    event_counts: list[SecurityEventCountRead]
    denial_groups: list[SecurityDenialGroupRead]
    recent_events: list[SecurityEventDetailRead]
    full_privilege_roles: list[FullPrivilegeProfileRoleRead]
    total_security_events: int
    total_denials: int


class ContinuityPersonRead(ApiModel):
    id: int
    name: str
    email: str | None


class GovernanceCustodianRead(ContinuityPersonRead):
    role_id: int
    role_code: str
    security_level_code: str


class SecurityFindingRead(ApiModel):
    code: str
    severity: Literal["critical", "advisory"]
    count: int | None = None


class SecurityReconciliationRead(ApiModel):
    generated_at: datetime
    active_authorization_administrators: list[ContinuityPersonRead]
    highest_clearance_governance_custodians: list[GovernanceCustodianRead]
    hierarchy_violation_count: int
    ownership_invariant_violation_count: int
    ownership_invariant_violations_by_type: dict[str, int]
    findings: list[SecurityFindingRead]


class AclMoveRequest(ApiModel):
    destination_aggregation_id: int
    resource_version: int = Field(gt=0)
    keep_current_access_as_override: bool = False
    confirm_ownership_change: bool = False
    reason: NonBlankString


class OwnershipCorrectionRequest(ApiModel):
    destination_role_id: int
    reason: NonBlankString


class OwnershipCorrectionPreviewRead(ApiModel):
    root_aggregation_id: int
    source_owning_org_unit_id: int
    destination_owning_org_unit_id: int
    destination_role_id: int
    destination_role_code: str
    destination_role_name: str
    affected_aggregation_count: int
    affected_record_count: int
    creator_role_id: int | None
    creator_role_grant_count: int


class SecurityLevelChangePreviewRequest(ApiModel):
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    target_security_level_id: int
    destination_aggregation_id: int | None = None
    remedy: Literal["none", "raise_ancestors", "downgrade_subtree"] = "none"


class SecurityLevelChangeVersions(ApiModel):
    resource: int
    aggregations: dict[str, int]
    records: dict[str, int]


class SecurityLevelChangeApplyRequest(SecurityLevelChangePreviewRequest):
    reviewed_versions: SecurityLevelChangeVersions


class SecurityLevelChangePreviewRead(ApiModel):
    conflict: bool
    remedy: str
    target_level_number: int
    affected_aggregations: list[dict[str, Any]]
    affected_records: list[dict[str, Any]]
    reviewed_versions: SecurityLevelChangeVersions


class AggregationCreate(ApiModel):
    creator_acl_role_id: int | None = None
    parent_aggregation_id: int | None = None
    classification_id: int | None = None
    aggregation_number: NonBlankString
    title: NonBlankString
    description: str | None = None
    date_opened: AwareDatetime | None = None
    date_closed: AwareDatetime | None = None
    security_level_id: int | None = None
    medium: Literal["digital", "physical", "mixed"] | None = None
    is_vital: bool = False
    date_of_next_review: AwareDatetime | None = None
    assigned_location: LocationCode | None = None
    current_location: LocationCode | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_closed is not None and _is_future(self.date_closed):
            raise ValueError("date_closed cannot be in the future")
        if (
            self.date_opened is not None
            and self.date_closed is not None
            and self.date_closed < self.date_opened
        ):
            raise ValueError("date_closed cannot be earlier than date_opened")
        if self.date_of_next_review is not None and not _is_future(self.date_of_next_review):
            raise ValueError("date_of_next_review must be in the future")
        return self


class AggregationUpdate(ApiModel):
    parent_aggregation_id: int | None = None
    classification_id: int | None = None
    aggregation_number: NonBlankString | None = None
    title: NonBlankString | None = None
    description: str | None = None
    date_opened: AwareDatetime | None = None
    date_closed: AwareDatetime | None = None
    security_level_id: int | None = None
    medium: Literal["digital", "physical", "mixed"] | None = None

    @model_validator(mode="after")
    def validate_closed_date(self):
        if self.date_closed is not None and _is_future(self.date_closed):
            raise ValueError("date_closed cannot be in the future")
        return self


class AggregationRead(ApiModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    parent_aggregation_id: int | None
    parent_aggregation_state: Literal["none", "visible", "redacted"] | None = None
    classification_id: int | None
    aggregation_number: str
    title: str
    description: str | None
    date_created: datetime
    date_opened: datetime
    date_closed: datetime | None
    medium: Literal["digital", "physical", "mixed"] = "mixed"
    is_vital: bool = False
    has_vital_descendants: bool = False
    date_of_next_review: datetime | None = None
    assigned_location: str | None = None
    current_location: str | None = None
    effective_assigned_location: str | None = None
    effective_current_location: str | None = None
    effective_assigned_location_source_aggregation_id: int | None = None
    effective_current_location_source_aggregation_id: int | None = None
    security_level_id: int
    owning_org_unit_id: int
    owning_org_unit_code: str
    owning_org_unit_name: str
    inherit_acl_from_parent: bool
    default_child_aggregation_acl_mode: Literal["mirror_resource_acl", "custom"]
    resource_acl_version: int
    child_aggregation_acl_version: int
    child_record_acl_version: int
    version: int

    @model_validator(mode="after")
    def derive_parent_aggregation_state(self):
        # CRUD redaction sets "redacted" explicitly. This fallback makes
        # non-redacted create/update responses self-describing as well.
        if self.parent_aggregation_state is None:
            self.parent_aggregation_state = (
                "none" if self.parent_aggregation_id is None else "visible"
            )
        return self


DispositionAction = Literal[
    "destruction",
    "transfer_to_external_archive",
    "selective_preservation",
    "retain_as_local_archives",
]


class ClassificationSchemeCreate(ApiModel):
    code: NonBlankString
    title: NonBlankString
    description: str | None = None
    authority: str | None = None
    scope_note: str | None = None
    edition: str | None = None
    date_published: AwareDatetime | None = None


class ClassificationSchemeUpdate(ApiModel):
    code: NonBlankString | None = None
    title: NonBlankString | None = None
    description: str | None = None
    authority: str | None = None
    scope_note: str | None = None
    edition: str | None = None
    date_published: AwareDatetime | None = None
    date_deactivated: datetime | None = None


class ClassificationSchemeRead(ClassificationSchemeCreate):
    id: int
    date_created: datetime
    date_updated: datetime
    date_deactivated: datetime | None
    date_first_used: datetime | None
    version: int
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class ClassificationSchemeClassificationCounts(ApiModel):
    classification_scheme_id: int
    branch_count: int
    terminal_count: int
    eligible_terminal_count: int


class BrowseClassificationNode(ApiModel):
    id: int
    classification_scheme_id: int
    parent_classification_id: int | None
    code: str
    title: str
    description: str | None
    is_terminal: bool
    date_deactivated: datetime | None
    child_classification_count: int
    root_aggregation_count: int


class BrowseAggregationNode(ApiModel):
    id: int
    parent_aggregation_id: int | None
    classification_id: int | None
    classification_code: str | None
    classification_title: str | None
    aggregation_number: str
    title: str
    description: str | None
    date_created: datetime
    date_opened: datetime
    date_closed: datetime | None
    medium: Literal["digital", "physical", "mixed"] = "mixed"
    is_vital: bool = False
    has_vital_descendants: bool = False
    date_of_next_review: datetime | None = None
    assigned_location: str | None = None
    current_location: str | None = None
    effective_assigned_location: str | None = None
    effective_current_location: str | None = None
    effective_assigned_location_source_aggregation_id: int | None = None
    effective_current_location_source_aggregation_id: int | None = None
    owning_org_unit_id: int
    owning_org_unit_code: str
    owning_org_unit_name: str
    child_aggregation_count: int
    record_count: int
    effective_hold_count: int = 0
    resource_state_changes_blocked: bool = False


class BrowseRecordNode(ApiModel):
    id: int
    aggregation_id: int | None
    aggregation_number: str | None
    aggregation_title: str | None
    record_number: str
    title: str
    description: str | None
    date_created: datetime
    date_originated: datetime
    medium: Literal["digital", "physical", "mixed"] = "mixed"
    is_vital: bool = False
    date_of_next_review: datetime | None = None
    effective_assigned_location: str | None = None
    effective_current_location: str | None = None
    effective_assigned_location_source_aggregation_id: int | None = None
    effective_current_location_source_aggregation_id: int | None = None
    owning_org_unit_id: int
    owning_org_unit_code: str
    owning_org_unit_name: str
    digital_component_count: int
    effective_hold_count: int = 0
    resource_state_changes_blocked: bool = False


class FavouriteAggregationRead(ApiModel):
    id: int
    aggregation_number: str
    title: str
    parent_aggregation_id: int | None
    date_favourited: datetime


class FavouriteRecordRead(ApiModel):
    id: int
    record_number: str
    title: str
    aggregation_id: int | None
    aggregation_number: str | None
    aggregation_title: str | None
    date_favourited: datetime


class FavouritesRead(ApiModel):
    aggregations: list[FavouriteAggregationRead]
    records: list[FavouriteRecordRead]


BrowseNode = TypeVar("BrowseNode")


class BrowsePage(ApiModel, Generic[BrowseNode]):
    items: list[BrowseNode]
    next_cursor: str | None
    total: int


class RetentionRuleInput(ApiModel):
    current_period_years: int = Field(ge=0)
    intermediate_period_years: int = Field(ge=0)
    final_disposition: DispositionAction
    instructions: str | None = None


class ClassificationRetentionRuleRead(RetentionRuleInput):
    id: int
    classification_id: int
    date_created: datetime
    date_updated: datetime
    version: int


class ClassificationCreate(ApiModel):
    classification_scheme_id: int
    parent_classification_id: int | None = None
    code: NonBlankString
    title: NonBlankString
    description: str | None = None
    authority: str | None = None
    scope_note: str | None = None
    keywords: str | None = None
    is_terminal: bool = False
    retention_rule: RetentionRuleInput | None = None


class ClassificationUpdate(ApiModel):
    parent_classification_id: int | None = None
    code: NonBlankString | None = None
    title: NonBlankString | None = None
    description: str | None = None
    authority: str | None = None
    scope_note: str | None = None
    keywords: str | None = None
    is_terminal: bool | None = None


class ClassificationRead(ApiModel):
    id: int
    classification_scheme_id: int
    parent_classification_id: int | None
    code: str
    title: str
    description: str | None
    authority: str | None
    scope_note: str | None
    keywords: str | None
    is_terminal: bool
    date_created: datetime
    date_updated: datetime
    date_deactivated: datetime | None
    date_first_used: datetime | None
    version: int
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class AggregationRetentionRuleCreate(RetentionRuleInput):
    justification: NonBlankString


class AggregationRetentionRuleRead(AggregationRetentionRuleCreate):
    id: int
    aggregation_id: int
    date_created: datetime
    date_updated: datetime
    version: int


class EffectiveRetentionRuleRead(ApiModel):
    governing_root_aggregation_id: int | None = None
    classification_id: int | None = None
    rule_source: Literal["aggregation", "classification"] | None = None
    rule_id: int
    defined_by_classification_id: int | None = None
    inheritance_depth: int
    current_period_years: int
    intermediate_period_years: int
    final_disposition: DispositionAction
    instructions: str | None = None
    justification: str | None = None


class RecordCreate(ApiModel):
    creator_acl_role_id: int | None = None
    aggregation_id: int
    record_number: NonBlankString
    title: NonBlankString
    description: str | None = None
    date_originated: AwareDatetime | None = None
    security_level_id: int | None = None
    medium: Literal["digital", "physical", "mixed"] | None = None
    is_vital: bool = False
    date_of_next_review: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_review_date(self):
        if self.date_of_next_review is not None and not _is_future(self.date_of_next_review):
            raise ValueError("date_of_next_review must be in the future")
        return self


class CreationRoleOption(ApiModel):
    role_id: int
    role_code: str
    role_name: str
    org_unit_id: int
    org_unit_code: str
    org_unit_name: str
    label: str


class RecordUpdate(ApiModel):
    aggregation_id: int | None = None
    record_number: NonBlankString | None = None
    title: NonBlankString | None = None
    description: str | None = None
    date_originated: AwareDatetime | None = None
    security_level_id: int | None = None
    medium: Literal["digital", "physical", "mixed"] | None = None


class RecordPlacementCorrection(ApiModel):
    destination_aggregation_id: int


class VitalStatusChange(ApiModel):
    is_vital: bool
    reason: NonBlankString


class ReviewDateChange(ApiModel):
    date_of_next_review: AwareDatetime | None = None
    reason: NonBlankString

    @model_validator(mode="after")
    def validate_review_date(self):
        if self.date_of_next_review is not None and not _is_future(self.date_of_next_review):
            raise ValueError("date_of_next_review must be in the future")
        return self


class AggregationLocationChange(ApiModel):
    assigned_location: LocationCode | None = None
    current_location: LocationCode | None = None
    reason: NonBlankString

    @model_validator(mode="after")
    def require_location_change(self):
        if not self.model_fields_set & {"assigned_location", "current_location"}:
            raise ValueError("provide assigned_location, current_location, or both")
        return self


class AggregationLocationPreview(ApiModel):
    assigned_location: LocationCode | None = None
    current_location: LocationCode | None = None

    @model_validator(mode="after")
    def require_location_change(self):
        if not self.model_fields_set & {"assigned_location", "current_location"}:
            raise ValueError("provide assigned_location, current_location, or both")
        return self


class AggregationLocationImpactItem(ApiModel):
    entity_type: Literal["aggregation", "record"]
    entity_id: int
    number: str
    title: str


class AggregationLocationPreviewRead(ApiModel):
    affected_descendant_count: int
    affected_descendants: list[AggregationLocationImpactItem]
    preview_truncated: bool


class RecordRead(ApiModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    aggregation_id: int | None
    aggregation_state: Literal["visible", "redacted"] | None = None
    record_number: str
    title: str
    description: str | None
    date_created: datetime
    date_originated: datetime
    medium: Literal["digital", "physical", "mixed"] = "mixed"
    is_vital: bool = False
    date_of_next_review: datetime | None = None
    effective_assigned_location: str | None = None
    effective_current_location: str | None = None
    effective_assigned_location_source_aggregation_id: int | None = None
    effective_current_location_source_aggregation_id: int | None = None
    security_level_id: int
    owning_org_unit_id: int
    owning_org_unit_code: str
    owning_org_unit_name: str
    inherit_acl_from_parent: bool
    resource_acl_version: int
    version: int

    @model_validator(mode="after")
    def derive_aggregation_state(self):
        # Records always belong to an aggregation; NULL in an API response
        # therefore means that the existing container relationship is redacted.
        if self.aggregation_state is None:
            self.aggregation_state = (
                "visible" if self.aggregation_id is not None else "redacted"
            )
        return self


class RecordDraftCreate(ApiModel):
    aggregation_id: int | None = None
    security_level_id: int | None = None
    record_number: NonBlankString | None = None
    title: NonBlankString | None = None
    description: str | None = None
    date_originated: AwareDatetime | None = None
    medium: Literal["digital", "physical", "mixed"] | None = None
    is_vital: bool = False
    date_of_next_review: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_review_date(self):
        if self.date_of_next_review is not None and not _is_future(self.date_of_next_review):
            raise ValueError("date_of_next_review must be in the future")
        return self


class RecordDraftUpdate(RecordDraftCreate):
    pass


class RecordDraftRead(ApiModel):
    id: int
    owner_user_id: int | None
    aggregation_id: int | None
    security_level_id: int | None
    record_number: str | None
    title: str | None
    description: str | None
    date_originated: datetime | None
    medium: Literal["digital", "physical", "mixed"] | None = None
    is_vital: bool = False
    date_of_next_review: datetime | None = None
    date_created: datetime
    date_updated: datetime
    expires_at: datetime
    version: int


class RecordDraftComponentRead(ApiModel):
    id: int
    draft_id: int
    component_order: int
    file_name: str
    date_created: datetime
    date_originated: datetime
    mime_type: str
    size_in_bytes: int
    checksum_algo: str
    checksum_value: str
    content_status: Literal["staged"] = "staged"
    storage_backend: Literal["temporary"] = "temporary"


class ComponentOrderItem(ApiModel):
    id: int
    component_order: int = Field(gt=0)


class ComponentReorderRequest(ApiModel):
    components: list[ComponentOrderItem]


class ComponentMoveRequest(ApiModel):
    direction: Literal[-1, 1]


class DigitalComponentCreate(ApiModel):
    record_id: int
    component_order: int = Field(gt=0)
    file_name: NonBlankString
    date_originated: AwareDatetime | None = None
    mime_type: NonBlankString
    size_in_bytes: int = Field(ge=0)
    checksum_algo: NonBlankString
    checksum_value: NonBlankString


class DigitalComponentUpdate(ApiModel):
    record_id: int | None = None
    component_order: int | None = Field(default=None, gt=0)
    file_name: NonBlankString | None = None
    date_originated: AwareDatetime | None = None
    mime_type: NonBlankString | None = None
    size_in_bytes: int | None = Field(default=None, ge=0)
    checksum_algo: NonBlankString | None = None
    checksum_value: NonBlankString | None = None


class DigitalComponentRead(ApiModel):
    id: int
    record_id: int
    component_order: int
    file_name: str
    date_created: datetime
    date_originated: datetime
    mime_type: str
    size_in_bytes: int
    checksum_algo: str
    checksum_value: str
    storage_backend: Literal["postgresql", "s3"]
    storage_key: str | None
    content_status: Literal["pending", "uploading", "available", "failed", "quarantined", "deleted"]
    active_content_set_id: int | None = None
    upload_completed_at: datetime | None = None
    version: int


class EventHistoryRead(ApiModel):
    id: int
    occurred_at: datetime
    transaction_id: int
    entity_type: str
    entity_id: int
    operation: str
    actor_user_id: int | None
    actor_name: str | None
    actor_email: str | None
    actor_type: str
    source: str
    request_id: UUID | None
    correlation_id: UUID | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    changed_fields: list[str]
    reason: str | None
    metadata: dict[str, Any]


class SelfRecentActivityRead(ApiModel):
    """A deliberately small, self-only view of a person's own recent work."""

    entity_type: Literal["aggregation", "record"]
    entity_id: int
    operation: Literal["CREATE", "UPDATE", "CONTENT_VIEWED"]
    occurred_at: datetime


class OwnershipDashboardCount(ApiModel):
    org_unit_id: int
    org_unit_code: str
    org_unit_name: str
    aggregation_count: int
    record_count: int


class DashboardOwnershipCount(OwnershipDashboardCount):
    open_aggregation_count: int
    closed_aggregation_count: int
    physical_record_count: int
    digital_record_count: int
    mixed_record_count: int
    vital_record_count: int
    storage_size_in_bytes: int


class DashboardClassificationMetrics(ApiModel):
    published_scheme_count: int
    draft_scheme_count: int
    inactive_scheme_count: int
    branch_count: int
    terminal_count: int
    assignable_terminal_count: int
    draft_terminal_count: int
    inactive_classification_count: int


class DashboardRecentItem(ApiModel):
    entity_type: Literal["aggregation", "record"]
    entity_id: int
    operation: Literal["CREATE", "UPDATE", "CONTENT_VIEWED"]
    occurred_at: datetime
    title: str
    aggregation_number: str | None
    record_number: str | None


class DashboardReviewItem(ApiModel):
    entity_type: Literal["aggregation", "record"]
    entity_id: int
    date_of_next_review: datetime
    title: str
    aggregation_number: str | None = None
    record_number: str | None = None


class DashboardSummaryRead(ApiModel):
    overview_counts: dict[str, int]
    overview_medium_counts: dict[str, dict[Literal["physical", "digital", "mixed"], int]]
    overview_resource_attention_counts: dict[str, dict[Literal["vital", "held"], int]]
    overview_aggregation_status_counts: dict[Literal["open", "closed"], int]
    overview_digital_component_metrics: dict[
        Literal["component_count", "storage_size_in_bytes"], int
    ]
    classification_metrics: DashboardClassificationMetrics
    unclassified_root_count: int
    ownership_counts: list[DashboardOwnershipCount]
    favourites: FavouritesRead
    recent_activity: list[DashboardRecentItem]
    review_warning_window_days: int
    overdue_review_count: int
    upcoming_review_count: int
    overdue_reviews: list[DashboardReviewItem]
    upcoming_reviews: list[DashboardReviewItem]


class DeletionBlocker(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DeletionPreflightRead(ApiModel):
    entity_type: Literal["user", "role", "org_unit"]
    entity_id: int
    entity_version: int
    allowed: bool
    blockers: list[DeletionBlocker]
    dependencies: dict[str, Any]
    cascades: dict[str, int]


class OrgUnitCreate(ApiModel):
    parent_org_unit_id: int | None = None
    code: NonBlankString
    name: NonBlankString
    description: str | None = None


class OrgUnitUpdate(ApiModel):
    managing_role_id: int | None = None
    file_administrator_role_id: int | None = None
    parent_org_unit_id: int | None = None
    code: NonBlankString | None = None
    name: NonBlankString | None = None
    description: str | None = None


class OrgUnitRead(ApiModel):
    managing_role_id: int | None = None
    file_administrator_role_id: int | None = None
    id: int
    parent_org_unit_id: int | None
    code: str
    name: str
    description: str | None
    status: Literal["active", "inactive"]
    date_created: datetime
    date_deactivated: datetime | None
    version: int
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class UserCreate(ApiModel):
    name: NonBlankString
    email: NonBlankString | None = None
    external_id: NonBlankString | None = None
    account_type: Literal["person", "service"] = "person"
    description: str | None = None


class UserUpdate(ApiModel):
    name: NonBlankString | None = None
    email: NonBlankString | None = None
    external_id: NonBlankString | None = None
    account_type: Literal["person", "service"] | None = None
    description: str | None = None


class UserRead(ApiModel):
    id: int
    name: str
    email: str | None
    external_id: str | None
    account_type: Literal["person", "service"]
    status: Literal["active", "inactive", "suspended"]
    date_created: datetime
    date_deactivated: datetime | None
    date_suspended: datetime | None
    version: int
    description: str | None = None
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class ServiceCredentialCreate(ApiModel):
    name: NonBlankString
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def expiry_is_future(self):
        if not _is_future(self.expires_at):
            raise ValueError("expires_at must be in the future")
        return self


class ServiceCredentialRotate(ServiceCredentialCreate):
    overlap_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def overlap_is_bounded(self):
        if self.overlap_until is not None:
            if not _is_future(self.overlap_until):
                raise ValueError("overlap_until must be in the future")
            now = datetime.now(self.overlap_until.tzinfo) if self.overlap_until.tzinfo else datetime.now()
            if self.overlap_until > now + timedelta(days=7):
                raise ValueError("credential overlap cannot exceed 7 days")
        return self


class ServiceCredentialRead(ApiModel):
    id: int
    service_user_id: int
    name: str
    credential_identifier: str
    status: Literal["active", "expiring", "expired", "revoked"]
    date_created: datetime
    expires_at: datetime
    last_used_at: datetime | None
    last_worker_id: str | None
    date_revoked: datetime | None
    created_by_user_id: int | None
    created_by_name: str | None


class ServiceCredentialCreated(ServiceCredentialRead):
    api_key: str


class TextIndexerCreate(ServiceCredentialCreate):
    name: NonBlankString
    external_id: NonBlankString
    credential_name: NonBlankString


class TextIndexerRead(UserRead):
    credential_count: int
    active_credential_count: int
    last_used_at: datetime | None


class TextIndexerDetail(TextIndexerRead):
    pass


class ServiceCredentialPage(ApiModel):
    items: list[ServiceCredentialRead]
    total: int
    limit: int
    offset: int
    retention_days: int


class TextIndexerCreated(ApiModel):
    text_indexer: TextIndexerRead
    credential: ServiceCredentialCreated


class TextIndexerBackfillRequest(ApiModel):
    batch_size: int = Field(default=500, ge=1, le=500)


class LoginRequest(ApiModel):
    email: NonBlankString
    password: str


class ChangePasswordRequest(ApiModel):
    current_password: str
    new_password: str


class PrincipalUserRead(ApiModel):
    localized: dict[str, Any] | None = None
    id: int
    name: str
    email: str
    account_type: Literal["person", "service"]


class PrincipalRoleRead(ApiModel):
    localized: dict[str, Any] | None = None
    id: int
    code: str
    name: str
    org_unit: dict[str, Any]


class PrincipalSessionRead(ApiModel):
    id: int


class PrincipalRead(ApiModel):
    user: PrincipalUserRead
    roles: list[PrincipalRoleRead]
    session: PrincipalSessionRead
    must_change_password: bool
    previous_login_at: datetime | None
    global_privileges: list[str]


class LoginSessionRead(ApiModel):
    id: int
    user_id: int
    user_name: str
    user_email: str | None
    account_type: Literal["person", "service"]
    date_created: datetime
    last_seen_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None
    client_ip: str | None
    user_agent: str | None
    is_current: bool
    status: Literal["active", "expired", "revoked"]


class RoleCreate(ApiModel):
    org_unit_id: int
    supervisor_role_id: int | None = None
    code: NonBlankString
    name: NonBlankString
    description: str | None = None
    security_level_id: int | None = None
    profile_id: int | None = None
    is_information_governance: bool = False


class RoleUpdate(ApiModel):
    org_unit_id: int | None = None
    supervisor_role_id: int | None = None
    code: NonBlankString | None = None
    name: NonBlankString | None = None
    description: str | None = None
    security_level_id: int | None = None
    profile_id: int | None = None
    is_information_governance: bool | None = None


class RoleRead(ApiModel):
    id: int
    org_unit_id: int | None
    supervisor_role_id: int | None
    code: str
    name: str
    description: str | None
    status: Literal["active", "inactive"]
    date_created: datetime
    date_deactivated: datetime | None
    security_level_id: int
    profile_id: int
    is_information_governance: bool
    is_system: bool = False
    account_type_restriction: Literal["person", "service"] | None = None
    version: int
    localized: dict[str, Any] | None = None
    translations: dict[str, dict[str, str]] | None = None


class UserRoleAssignmentCreate(ApiModel):
    user_id: int
    role_id: int
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot be earlier than valid_from")
        return self


class UserRoleAssignmentUpdate(ApiModel):
    user_id: int | None = None
    role_id: int | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class UserRoleAssignmentRead(ApiModel):
    id: int
    user_id: int
    role_id: int
    date_assigned: datetime
    valid_from: datetime
    valid_until: datetime | None
    version: int


SearchOperator = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "between",
    "is_null",
    "is_not_null",
    "contains_ci",
    "starts_with_ci",
    "ends_with_ci",
    "matches_ci",
]


class FullTextClause(ApiModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    sources: list[str] | None = Field(default=None, min_length=1, max_length=2)


class SearchExpression(ApiModel):
    field: str | None = None
    operator: SearchOperator | None = None
    value: Any = None
    and_: list["SearchExpression"] | None = Field(default=None, alias="and", min_length=1)
    or_: list["SearchExpression"] | None = Field(default=None, alias="or", min_length=1)
    not_: "SearchExpression | None" = Field(default=None, alias="not")
    full_text: FullTextClause | None = None

    @model_validator(mode="after")
    def validate_expression_shape(self):
        comparison_keys = self.model_fields_set & {"field", "operator", "value"}
        logical_nodes = sum(node is not None for node in (self.and_, self.or_, self.not_))
        full_text_nodes = int(self.full_text is not None)
        is_comparison = self.field is not None or self.operator is not None

        if logical_nodes + full_text_nodes + int(is_comparison) != 1:
            raise ValueError("use exactly one comparison, full_text, and, or, or not expression")
        if (logical_nodes or full_text_nodes) and comparison_keys:
            raise ValueError("logical expressions cannot contain field, operator, or value")
        if is_comparison and (self.field is None or self.operator is None):
            raise ValueError("comparison expressions require field and operator")

        has_value = "value" in self.model_fields_set
        if is_comparison and self.operator in {"is_null", "is_not_null"} and has_value:
            raise ValueError(f"{self.operator} does not accept a value")
        if is_comparison and self.operator not in {"is_null", "is_not_null"}:
            if not has_value or self.value is None:
                raise ValueError(f"{self.operator} requires a non-null value")
        return self


class SearchSort(ApiModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"


class SearchRequest(ApiModel):
    where: SearchExpression | None = None
    sort: list[SearchSort] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    include: list[Literal["full_text_matches"]] = Field(default_factory=list, max_length=1)
    debug: bool = False


class GlobalSearchRequest(ApiModel):
    record_where: SearchExpression | None = None
    aggregation_where: SearchExpression | None = None
    result_types: list[Literal["records", "aggregations"]] = Field(min_length=1, max_length=2)
    limit: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2000)
    debug: bool = False

    @model_validator(mode="after")
    def branches_match_result_types(self):
        if len(set(self.result_types)) != len(self.result_types):
            raise ValueError("result_types cannot contain duplicates")
        supplied = ({"records"} if self.record_where is not None else set()) | (
            {"aggregations"} if self.aggregation_where is not None else set()
        )
        if supplied != set(self.result_types):
            raise ValueError("result_types must exactly match supplied resource branches")
        return self


SearchItem = TypeVar("SearchItem")


class SearchResponse(ApiModel, Generic[SearchItem]):
    items: list[SearchItem]
    total: int
    limit: int
    offset: int
    returned: int
