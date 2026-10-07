# Hierarchical Oversight Default ACLs — Security and Authorization Extension

**Status:** Approved
**Approved:** 7 October 2026
**Project:** ERMS / Wathiq
**Prepared:** 7 October 2026
**Revision:** 1.5 — separated File Administrator grants from creator defaults

## 1. Purpose and authority

This specification extends the approved
[Security and Authorization Subsystem](security-and-authorization-subsystem.md)
and
[Organizational Ownership and Default ACLs](organizational-ownership-and-default-acls.md)
specifications. It gives appropriate management and file-administration roles
access to newly created aggregations and records through two contextual ACL
principals:

- **Owning and Higher-Level Unit Managers**; and
- **Effective File Administrator**.

This is an authorization feature. It is not part of disposition or destruction
workflow, and those specifications do not define its behavior.

Where this extension differs from the earlier ACL principal list or creation
defaults, this extension governs the two new principals and their grants. All
other approved authorization rules remain unchanged.

## 2. Approved outcomes

1. New aggregation and record ACLs include the two contextual principals.
2. **Owning and Higher-Level Unit Managers** follows the current
   organizational-unit chain from the resource's owning unit through every
   ancestor and matches each unit's designated managing role.
3. **Effective File Administrator** follows the current organizational-unit
   hierarchy from the resource's owning unit.
4. **Owning and Higher-Level Unit Managers** receives the same permissions as
   the existing **All org unit members** default for that resource type, but is
   an independent grant that remains effective if **All org unit members** is
   removed.
5. **Effective File Administrator** receives the explicit operational permission
   sets in Section 4, including ACL management. These are independent of the
   creator-role defaults, which no longer include ACL management.
6. The principals supply ACL scope only. They do not supply a global privilege,
   security clearance, role assignment, or any other required authorization
   gate.
7. Changes to organizational hierarchy, designated managing roles, designated
   File Administrator roles, role assignments, role activity, or ownership
   take effect without rewriting every affected resource ACL.
8. An authorized ACL manager may remove either default grant. A later hierarchy
   or role change must not recreate a grant that was deliberately removed.

## 3. Terms

### 3.1 Managing role

Each organizational unit may designate one role through nullable
`org_units.managing_role_id`. The referenced role must belong to that same
organizational unit and must not be a system or service role. This is the
authoritative designation of the role responsible for managing that unit.

The database rejects a role belonging to another organizational unit. Wathiq
allows only an authorized organizational-unit administrator to set, replace,
or clear the field and records every change in event history. Deactivating a
designated role does not erase the designation or its history, but an inactive
role cannot match an ACL principal or receive a task.

### 3.2 Owning and Higher-Level Unit Managers

A contextual synthetic ACL principal. It starts with the resource's current
owning organizational unit, includes that unit, and then follows the current
parent-unit chain through every ancestor. It matches users who have a currently
effective assignment to an active `managing_role_id` designated by any unit in
that chain.

This principal is independent of **All org unit members**. Removing the general
unit-member grant does not remove the owning unit manager's access. A unit with
no designated managing role contributes no match, but evaluation continues to
higher units. An inactive or otherwise invalid designated role contributes no
match and likewise does not stop evaluation of higher units.

The user-facing label is **Owning and Higher-Level Unit Managers**. The stored
principal code is `owning_and_higher_level_unit_managers`.

### 3.3 Effective File Administrator

A contextual synthetic ACL principal. It checks the resource's current owning
organizational unit first. If that unit has no configured
`file_administrator_role_id`, it checks each ancestor unit in order. The first
unit with a configured role supplies the effective File Administrator role.

It matches users who have a currently effective assignment to that role while
the role is active. A configured but inactive or otherwise invalid role does
not cause resolution to continue to a more distant ancestor. If no role is
configured anywhere in the chain, the principal matches nobody.

The user-facing label is **Effective File Administrator**. The recommended
stored principal code is `effective_file_administrator`.

Only the effective File Administrator is matched. File Administrator roles
higher than the effective role do not receive access through this principal.

## 4. Default permissions

**Owning and Higher-Level Unit Managers** mirrors the existing **All org unit
members** defaults.
**Effective File Administrator** receives the explicit permission sets below,
including ACL management. These sets are defined independently of creator-role
defaults and do not change automatically when those defaults change.
This gives the File Administrator the operational and ACL-management authority
needed to administer records for the organizational units for which that role
is effective.

Information governors retain ultimate responsibility for access
administration through their existing authorized capabilities. When an
effective File Administrator is configured, access administration for the
applicable units is delegated to that role. If none is configured, information
governors continue to administer access; creation does not grant that authority
to the creator role. Both global privileges and applicable resource-access
checks continue to apply.

### 4.1 Aggregations

Grant **Owning and Higher-Level Unit Managers**:

```text
aggregation.view
aggregation.history.view
```

Grant **Effective File Administrator**:

```text
aggregation.view
aggregation.modify_metadata
aggregation.add_child
aggregation.add_record
aggregation.close
aggregation.acl.manage
aggregation.history.view
```

Do not grant either principal aggregation deletion, reopening, movement,
receiving, reclassification, or security-level changes by default.

### 4.2 Records

Grant **Owning and Higher-Level Unit Managers**:

```text
record.view
record.component.list
record.component.view
record.component.download
```

Grant **Effective File Administrator**:

```text
record.view
record.acl.manage
record.history.view
record.component.list
record.component.view
record.component.download
record.component.share
record.component.print
```

Do not grant either principal record metadata changes, deletion, movement,
security-level changes, or component addition, replacement, removal, or
reordering by default.

The Effective File Administrator's ACL-management grants are intentional. They
allow the role to administer access to resources owned by the unit for which it
is effective. Every ACL change still requires the matching global privilege,
uses optimistic concurrency, and produces immutable event history.

## 5. Authorization behavior

### 5.1 All existing gates still apply

A match supplies only the required ACL permission. Access is allowed only when
the user also has:

- a currently effective real-role assignment;
- the required global privilege through an effective profile;
- sufficient security clearance; and
- permission under every applicable lifecycle, redaction, structural, and
  information-disclosure rule.

Neither principal grants access merely because a user has a related job title
or because a resource belongs to a related organizational unit.

### 5.2 Current-state resolution

Wathiq resolves both principals from current authoritative data during access
evaluation:

- **Owning and Higher-Level Unit Managers** uses the resource's current
  `owning_org_unit_id`, the current organizational-unit hierarchy, and current
  `managing_role_id` values on the owning unit and all ancestor units.
- **Effective File Administrator** uses the resource's current
  `owning_org_unit_id`, the current organizational-unit hierarchy, and current
  `file_administrator_role_id` values.
- Both use current role activity and effective assignments when matching the
  user.

The ACL stores the rule to evaluate, not a copied list of users or all roles
that happened to match on the creation date.

### 5.3 Effect of later organizational changes

The following changes take effect on the next authoritative authorization
check without rewriting resource ACL rows:

- moving an organizational unit under a different parent changes the chains
  searched by both principals;
- changing the owning unit's or an ancestor unit's `managing_role_id` changes
  the roles matched by **Owning and Higher-Level Unit Managers**;
- changing `file_administrator_role_id` changes the effective role;
- activating or deactivating a role changes whether its assignees can match;
- starting or ending a role assignment changes whether that user can match;
  and
- changing a resource's owning unit changes the organizational chains used for
  both principals.

These changes affect access only while the corresponding synthetic grants
remain in the effective ACL.

### 5.4 Access-cache correctness

An authorization cache must not preserve an earlier answer after relevant
state changes. Any cached result must either be invalidated when the data in
Section 5.3 changes or use a key and freshness rule that guarantees the same
result as current authoritative data.

Cache invalidation covers, at minimum:

- managing-role configuration and role activity;
- role assignments and their effective dates;
- organizational-unit parent changes;
- File Administrator role configuration;
- resource ownership changes;
- ACL edits and ACL inheritance changes;
- profile privileges; and
- security clearance.

Failure to invalidate a cache must fail closed rather than continue granting
access from stale data.

## 6. ACL creation and inheritance

### 6.1 Root aggregations

The root aggregation's local effective ACL receives both synthetic principals
with their respective aggregation grants from Section 4.1. Neither principal
requires a creator-role anchor.

### 6.2 Child aggregations and records

Existing live ACL inheritance remains authoritative. Every new child
aggregation and record receives the two principals in its dormant local ACL.

If the child inherits its effective ACL from a parent, the parent's policy
remains effective. The dormant local ACL becomes effective only under the
existing local-override rules.

### 6.3 Default-child ACLs

When a new aggregation's default child-aggregation and child-record ACLs are
initialized, they include each principal's corresponding grants from Section
4. Neither principal stores a role anchor in these templates.

### 6.4 Manual removal and later changes

These are defaults, not permanent mandatory grants. An authorized ACL manager
may remove or reduce them through the ordinary ACL editor. Wathiq records the
change through existing immutable ACL history.

After removal, a change to the hierarchy, managing-role configuration, File
Administrator configuration, assignment, or ownership must not add the
principal again. It returns only through an explicit authorized ACL edit or
replacement that adds it.

## 7. ACL representation and integrity

The allowed ACL principal types become:

```text
role
everyone
org_unit_members
owning_and_higher_level_unit_managers
effective_file_administrator
```

Their structural rules are:

| Principal type | `role_id` | Meaning |
| --- | --- | --- |
| `role` | Required | One named role receives the grant |
| `everyone` | Null | Every otherwise-authorized authenticated user |
| `org_unit_members` | Null | Current members of the resource's owning unit |
| `owning_and_higher_level_unit_managers` | Null | Current assignees of active managing roles designated by the resource's owning unit and its ancestor units may match |
| `effective_file_administrator` | Null | The current effective File Administrator resolved from the resource's owning-unit chain may match |

Every resource ACL and both default-child ACL types must support the new
principal codes. Check constraints, foreign keys, uniqueness rules, permission
dependency checks, ACL-version handling, and event-history triggers must cover
them. Duplicate grants for the same principal and permission in one ACL are
rejected.

## 8. Ownership transfer and structural moves

An aggregation or record move continues to change ownership under the existing
approved rules. Both contextual principals then resolve through the new
owner's organizational chain without rewriting either grant. The move preview
must explain that the users who match these principals may change when
ownership changes.

Changes to a unit's parent do not constitute a resource ownership transfer.
They simply change the current organizational chains used by both principals.

## 9. API and user interface

ACL read and write contracts accept the two new principal types and enforce the
structural rules in Section 7. Clients cannot invent additional synthetic
principal codes.

The ACL editor presents the principals by their user-facing labels and explains
their current meaning:

- **Owning and Higher-Level Unit Managers** shows the owning unit, the current
  ancestor units, and the managing roles that may match.
- **Effective File Administrator** shows the owning unit, the organizational
  unit that supplied the configured role, and that effective role. If no role
  is configured, it shows that the principal currently matches nobody.

These explanations are server-paginated or bounded where a hierarchy could be
large. They must not disclose roles, units, resources, or users the viewer is
not authorized to inspect.

Authorization explanations identify the synthetic principal, the real role
through which the user matched, and the relevant organizational unit. They must
also identify any independent gate that denied the operation without revealing
protected information.

Removing either synthetic principal requires the same confirmation and
optimistic-concurrency protection used for other ACL replacement operations.

## 10. Event history and audit

Creation history records that each synthetic grant was added.

Each allowed authorization decision remains explainable from historical and
current facts. Relevant audit output includes:

- resource and effective ACL source;
- synthetic principal code;
- matched real role and effective assignment;
- owning organizational unit, matched owning or ancestor unit, and matched
  managing role, when applicable;
- owning organizational unit, the unit that supplied the File Administrator
  configuration, and the matched File Administrator role, when applicable; and
- the independent privilege and clearance gates.

Role, hierarchy, assignment, ownership, configuration, and ACL changes continue
to use their existing governed event histories. This extension does not create
a new event for every later access change caused by one of those configuration
changes.

## 11. Migration and existing resources

This extension changes defaults for resources created after implementation. It
does not silently add the principals to existing local ACLs or default-child
ACLs.

Preserve every existing grant, including creator-role ACL-management grants in
resource ACLs, dormant local ACLs, and default-child templates. The revised
creator defaults apply only to subsequent ACL initialization. Do not remove
existing permissions or add the new principals through this revision's upgrade.

If the organization wants the grants on existing resources, that requires a
separate approved, previewable, auditable migration or bulk ACL operation. Such
an operation must preserve deliberate ACL customizations and existing
inheritance choices.

Canonical executable SQL belongs in `database/schema.sql` and in a migration
for existing databases only when implementation is authorized. SQL files must
remain portable PostgreSQL and must not contain `psql` meta-commands.

## 12. Verification and traceability

| ID | Requirement | Minimum verification |
| --- | --- | --- |
| HACL-01 | New root aggregation ACLs grant Owning and Higher-Level Unit Managers the org-unit-member defaults and Effective File Administrator the explicit Section 4.1 grants, including `aggregation.acl.manage`; creator defaults omit ACL management | Creation, exact-grant, omission, dependency, separate creator/File Administrator principal, ACL-management, and database-constraint tests |
| HACL-02 | New record ACLs grant Owning and Higher-Level Unit Managers the org-unit-member defaults and Effective File Administrator the explicit Section 4.2 grants, including `record.acl.manage`; creator defaults omit ACL management | Creation, exact-grant, omission, component-access, separate creator/File Administrator principal, share/print, ACL-management, and database-constraint tests |
| HACL-03 | Child dormant local ACLs and both default-child ACL types receive the correct principals without role anchors and without overriding live inheritance | Root, child, record, template, null-role, inherited/local-toggle, and ACL-source tests |
| HACL-04 | `org_units.managing_role_id` identifies at most one non-system, non-service role belonging to that unit, and only authorized changes are accepted and recorded | Same-unit foreign-key, invalid/system/service role, set/replace/clear authorization, inactive-role, concurrency, and event-history tests |
| HACL-05 | Owning and Higher-Level Unit Managers matches current assignees of active managing roles on the owning unit and every ancestor, remains independent of All org unit members, and continues past missing, inactive, or invalid designations | Owning-unit and multi-level hierarchy, removal of All org unit members, missing/inactive/invalid role, assignment effective-date, reparenting, ownership-change, and authorization-explanation tests |
| HACL-06 | Effective File Administrator matching uses the owning unit first and then the nearest ancestor with a configured role, never falls past an unusable configured role, and matches nobody when the chain has no configuration | Direct, multi-level, no-role, inactive/invalid-role, assignment, ownership, and authorization-explanation tests |
| HACL-07 | Both principals supply ACL permissions only and never bypass global privilege, clearance, lifecycle, redaction, or information-disclosure gates | Cross-gate allow/deny, insufficient-clearance, missing-privilege, closed-resource, and redaction tests |
| HACL-08 | Hierarchy, managing-role, File Administrator, role, assignment, ownership, ACL, profile, and clearance changes affect the next authoritative decision without stale authorization | Mutation, cache-invalidation, multi-process, failure, and fail-closed tests |
| HACL-09 | Removing a synthetic grant is versioned and audited, and later contextual changes do not recreate it | ACL-editor, optimistic-concurrency, removal, hierarchy-change, and history tests |
| HACL-10 | Ownership-changing moves preview the possible change in matching users, and both principals follow the new owner's current organizational chain without grant rewriting | Move preview, ownership confirmation, rollback, destination validation, event-history, and post-move authorization tests |
| HACL-11 | APIs, ACL editors, and authorization explanations represent the new principals accurately without leaking protected role, unit, user, or resource information | Contract, invalid-payload, uniqueness, bounded-query, UI, accessibility, LTR/RTL, and disclosure tests |
| HACL-12 | This upgrade preserves all existing resource, dormant local, and default-child ACL grants, including creator ACL-management grants, and does not add new principals to existing ACLs | Upgrade, exact before/after grant comparison, inheritance, and customization-regression tests |

All database-backed tests must use a newly created disposable PostgreSQL
database initialized from the canonical schema or required migration path. The
test database must be dropped after the run whether the tests pass or fail.

## 13. Completion criteria

This extension is complete only when:

- every requirement in Section 12 has implementation and passing verification
  evidence;
- the two principals behave consistently in resource ACLs, dormant local ACLs,
  and both default-child ACL types;
- current organizational and role changes cannot leave stale access;
- existing authorization gates remain effective;
- ACL and authorization explanations remain understandable and do not disclose
  protected information; and
- the maintained English and Arabic interface catalogues pass all required
  coverage, ordering, terminology, placeholder, provenance, stale-key, and hash
  checks.
