from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str = "text"
    required: bool = False
    lookup_resource: str | None = None
    lookup_label_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntitySpec:
    key: str
    label: str
    singular: str
    columns: tuple[tuple[str, str], ...]
    fields: tuple[FieldSpec, ...]
    search_first: bool = False
    search_fields: tuple[str, ...] = ()


ENTITIES = {
    "aggregations": EntitySpec(
        "aggregations", "Aggregations", "aggregation",
        (("aggregation_number", "Number"), ("title", "Title"), ("medium_display", "Medium"), ("vital_display", "Vital"), ("review_display", "Review"), ("location_display", "Location")),
        (FieldSpec("parent_aggregation_id", "Parent aggregation", "lookup", lookup_resource="aggregations", lookup_label_fields=("aggregation_number", "title")), FieldSpec("classification_id", "Classification", "classification", lookup_resource="classifications", lookup_label_fields=("code", "title")), FieldSpec("security_level_id", "Security level", "lookup", True, "security-levels", ("code", "name")), FieldSpec("medium", "Medium", "medium", True), FieldSpec("is_vital", "Vital aggregation", "bool"), FieldSpec("aggregation_number", "Aggregation number", required=True), FieldSpec("title", "Title", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("date_opened", "Date opened", "datetime"), FieldSpec("date_closed", "Date closed", "datetime"), FieldSpec("date_of_next_review", "Date of next review", "datetime"), FieldSpec("assigned_location", "Assigned location"), FieldSpec("current_location", "Current location")),
        True, ("aggregation_number", "title", "description"),
    ),
    "records": EntitySpec(
        "records", "Records", "record",
        (("record_number", "Number"), ("title", "Title"), ("aggregation_display", "Aggregation"), ("medium_display", "Medium"), ("vital_display", "Vital"), ("review_display", "Review"), ("location_display", "Inherited location")),
        (FieldSpec("aggregation_id", "Aggregation", "lookup", True, "aggregations", ("aggregation_number", "title")), FieldSpec("security_level_id", "Security level", "lookup", True, "security-levels", ("code", "name")), FieldSpec("medium", "Medium", "medium", True), FieldSpec("is_vital", "Vital record", "bool"), FieldSpec("record_number", "Record number", required=True), FieldSpec("title", "Title", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("date_originated", "Date originated", "datetime"), FieldSpec("date_of_next_review", "Date of next review", "datetime")),
        True, ("record_number", "title", "description"),
    ),
    "classification-schemes": EntitySpec(
        "classification-schemes", "Classification schemes", "classification scheme",
        (("code", "Code"), ("title", "Title"), ("date_published", "Published"), ("date_deactivated", "Deactivated")),
        (FieldSpec("code", "Code", required=True), FieldSpec("title", "Title", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("authority", "Authority"), FieldSpec("scope_note", "Scope note", "textarea"), FieldSpec("edition", "Edition"), FieldSpec("date_published", "Date published", "datetime")),
        False, ("code", "title", "description"),
    ),
    "classifications": EntitySpec(
        "classifications", "Classifications", "classification",
        (("code", "Code"), ("title", "Title"), ("type_display", "Type"), ("scheme_display", "Scheme")),
        (
            FieldSpec("classification_scheme_id", "Classification scheme", "lookup", True, "classification-schemes", ("code", "title")),
            FieldSpec("parent_classification_id", "Parent classification", "lookup", False, "classifications", ("code", "title")),
            FieldSpec("code", "Code", required=True), FieldSpec("title", "Title", required=True),
            FieldSpec("description", "Description", "textarea"), FieldSpec("authority", "Authority"),
            FieldSpec("scope_note", "Scope note", "textarea"), FieldSpec("keywords", "Keywords"),
            FieldSpec("is_terminal", "Classification type", "classification_type", True),
            FieldSpec("current_period_years", "Current retention (years)", "int"),
            FieldSpec("intermediate_period_years", "Intermediate retention (years)", "int"),
            FieldSpec("final_disposition", "Final disposition", "disposition"),
            FieldSpec("instructions", "Retention and disposal instructions", "textarea"),
        ),
        True, ("code", "title", "description", "keywords"),
    ),
    "org-units": EntitySpec(
        "org-units", "Organization units", "organization unit",
        (("code", "Code"), ("name", "Name"), ("effective_status", "Status"), ("parent_org_unit_display", "Parent")),
        (FieldSpec("parent_org_unit_id", "Parent organization unit", "lookup", lookup_resource="org-units", lookup_label_fields=("code", "name")), FieldSpec("code", "Code", required=True), FieldSpec("name", "Name", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("managing_role_id", "Managing role", "lookup", lookup_resource="roles", lookup_label_fields=("code", "name")), FieldSpec("file_administrator_role_id", "File Administrator role", "lookup", lookup_resource="roles", lookup_label_fields=("code", "name"))),
        search_fields=("code", "name", "description"),
    ),
    "users": EntitySpec(
        "users", "Users", "user",
        (("_avatar", ""), ("name", "Name"), ("email", "Email"), ("account_type", "Account type"), ("status", "Status")),
        (FieldSpec("name", "Name", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("email", "Email"), FieldSpec("external_id", "External ID"), FieldSpec("account_type", "Account type", "account_type", True)),
        search_fields=("name", "email", "external_id"),
    ),
    "roles": EntitySpec(
        "roles", "Roles", "role",
        (("code", "Code"), ("name", "Name"), ("org_unit_display", "Organization unit"), ("profile_display", "Profile"), ("effective_status", "Status")),
        (FieldSpec("org_unit_id", "Organization unit", "lookup", True, "org-units", ("code", "name")), FieldSpec("supervisor_role_id", "Supervising role", "lookup", False, "roles", ("code", "name")), FieldSpec("security_level_id", "Security clearance", "lookup", True, "security-levels", ("code", "name")), FieldSpec("profile_id", "Profile", "lookup", True, "profiles", ("code", "name")), FieldSpec("is_information_governance", "Information-governance role", "bool"), FieldSpec("code", "Code", required=True), FieldSpec("name", "Name", required=True), FieldSpec("description", "Description", "textarea")),
        search_fields=("code", "name", "description"),
    ),
    "security-levels": EntitySpec(
        "security-levels", "Security levels", "security level",
        (("code", "Code"), ("name", "Name"), ("level_number", "Level"), ("prevents_disposition", "Prevents disposition")),
        (FieldSpec("code", "Code", required=True), FieldSpec("name", "Name", required=True), FieldSpec("description", "Description", "textarea"), FieldSpec("level_number", "Level number", "int", True), FieldSpec("prevents_disposition", "Prevents disposition", "bool")),
    ),
    "profiles": EntitySpec(
        "profiles", "Profiles", "profile",
        (("code", "Code"), ("name", "Name"), ("description", "Description"), ("is_system", "Built-in")),
        (FieldSpec("code", "Code", required=True), FieldSpec("name", "Name", required=True), FieldSpec("description", "Description", "textarea")),
    ),
    "privileges": EntitySpec(
        "privileges", "Privileges", "privilege",
        (("code", "Code"), ("name", "Name"), ("category", "Category"), ("is_reserved", "Reserved")),
        (),
    ),
    "permissions": EntitySpec(
        "permissions", "Permissions", "permission",
        (("resource_type", "Resource type"), ("code", "Code"), ("name", "Name"), ("description", "Description")),
        (),
    ),
}
