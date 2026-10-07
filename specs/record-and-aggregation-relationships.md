# Record and Aggregation Relationships

**Status:** Approved — ready for implementation

**Prepared:** 6 October 2026  
**Project:** ERMS / Wathiq

## 1. Purpose and scope

Wathiq shall support named relationships between aggregations and between
records, with navigation in both directions. These links describe associations;
they do not replace or alter the existing aggregation hierarchy or a record's
containing aggregation. They do not confer access, inherit metadata, change
retention rules, or automatically move or copy content.

The requirements below capture the approved behavior. The existing
[security specification](security-and-authorization-subsystem.md),
[disposition specification](disposition.md), and
[WebUI performance contract](../docs/webui-performance.md) remain authoritative
unless an amendment is explicitly approved.

## 2. Supported endpoints

- An aggregation may relate to another aggregation.
- A record may relate to another record, including a record in a different
  aggregation, subject to authorization.
- Related aggregations and records remain in their existing locations.

**Agreed:** Defer aggregation-to-record links in the initial release. A
record's membership in an aggregation is already represented by containment.
Cross-type links may be useful for a record that documents or authorizes an
entire case file, but they need their own catalogue and clear disposition
semantics. If approved later, use precise labels such as **documents /
documented by** rather than duplicating **contains / contained in**.

## 3. Bidirectional links

Each relationship has two endpoints and one relationship type. Its forward and
reverse names describe the same link: if record A **supersedes** record B,
record B is **superseded by** record A. Creating or removing that link changes
both views together; users do not maintain a separate reverse link.

Symmetric types use the same name in both directions, such as **related to**.
Directional types must make the chosen direction clear before creation.

**Agreed:** Reject self-links and duplicate links, including duplicates
entered from the reverse endpoint. Permit different relationship types between
the same pair. Do not infer transitive relationships: A relating to B and B
relating to C does not create an A–C link.

## 4. Relationship catalogues

Maintain separate catalogues for aggregation relationships and record
relationships. Each type defines its forward and reverse names. Users with the
catalogue-administration privilege may add types.

### Approved initial aggregation catalogue

| Forward name | Reverse name | Intended meaning |
| --- | --- | --- |
| related to | related to | General association between files or cases |
| supersedes | superseded by | One aggregation replaces another for business purposes |
| continues | continued by | A later file continues an earlier file |
| references | referenced by | One aggregation refers to another |

### Approved initial record catalogue

| Forward name | Reverse name | Intended meaning |
| --- | --- | --- |
| related to | related to | General association |
| supersedes | superseded by | A replacement record replaces an earlier record |
| redaction of | redaction source of | A redacted record derives from its source record |
| attached to | has attachment | A separately registered record is an attachment to another record |
| responds to | has response | A reply relates to the record being answered |
| references | referenced by | A record refers to another record |
| copy of | has copy | A separately registered copy relates to its source |

Use **supersedes**, rather than “supercedes.” **Has attachment** is the approved
reverse of **attached to**. This relationship does not create a digital
component or merge two records. Likewise, **redaction of** describes provenance;
it does not perform redaction or change the source's access controls.

**Agreed catalogue maintenance:** Give types stable identifiers and localized
labels. Allow administrators to deactivate a type so existing links remain readable
but new links cannot use it. Do not delete a type in use or change its meaning
retroactively; create a new type for a different meaning.

### Approved catalogue and privilege setup

Use the initial aggregation and record catalogues above as the starting
sets. Place **Relationship Types** under Records Management administration,
with separate Aggregation and Record tabs, available to users with
`relationships.administer`.

Grant `relationships.link` to `INFO_GOV_OFFICER` and `INFO_GOV_MGR`, and to
ordinary business-user profiles whose users maintain records and aggregations.
Grant `relationships.administer` to `INFO_GOV_OFFICER` and `INFO_GOV_MGR` for
business catalogue maintenance. Do not grant either privilege to `SYS_ADMIN`
merely for technical administration. Explicitly add both to `ALL_PRIVS` under
its existing compatibility policy. Existing custom profiles receive grants
through normal profile administration. This catalogue and privilege setup is approved.

### English and Arabic localization

Localize the display names and descriptions of `relationships.link` and
`relationships.administer` in English and Arabic. Keep their privilege codes
unchanged across languages. Provide English and Arabic forward and reverse
labels for every seeded type in both relationship catalogues. Catalogue
administration must support maintaining labels in both languages for
user-created types, using the existing multilingual catalogue conventions.
Stable type identifiers and link direction do not change with the UI language.

Localize the catalogue administration screens, relationship actions, table
headings, redacted and empty states, validation messages, and disposition
blocker explanations in English and Arabic. Follow sections 7.5 and
7.8.1–7.8.4 of the internationalization specification: preserve curated Arabic
wording and provenance, merge by message key, maintain canonical ordering, and
verify active-key coverage and translation-artifact checks. Verify relationship
and privilege displays in both English/LTR and Arabic/RTL.

## 5. Authorization and redacted targets

Viewing a relationship from an authorized aggregation or record shall show the
applicable relationship name and its related endpoint. An authorized target
is navigable. An unauthorized target shall appear as a redacted representation
under the existing redaction rules, without revealing protected identifiers,
titles, metadata, or content. Redaction does not authorize navigation or action
on that target. Authorization must be checked again when navigating.

### Global privileges and resource access

| Global privilege | Capability |
| --- | --- |
| `relationships.link` | Create and remove individual links |
| `relationships.administer` | Maintain the two relationship catalogues |

These names follow the existing `.manage` and `.administer` conventions.
Catalogue administration does not imply permission to manage individual links.
Viewing links needs the existing resource-view authorization rather than a new
relationship-view privilege.

Creating or removing a link requires `relationships.link` and current view
authorization on **both endpoints**, including the existing resource-view ACL,
clearance, and organizational gates. No dedicated relationship ACL permission,
metadata-edit ACL permission, or global `aggregation.modify` or `record.modify`
privilege is required.

Users granted `relationships.link` may therefore maintain links between
resources they can view, including after initial creation when they cannot
edit metadata. Administrators grant this capability through privilege profiles;
they do not need to configure relationship permissions on individual resources
or default-child ACL templates. View access alone does not authorize link
changes without `relationships.link`.

**Agreed:** A redacted target cannot be selected for link creation or used to
authorize removal. Removing its link during disposition review requires an
officer authorized for both endpoints. Any exception allowing removal through
a redacted target must be explicitly approved; neither new global privilege
bypasses resource access.

## 6. Display and navigation

Aggregation details shall list related aggregations, and record details shall
list related records. Each list shows the relationship name as read from the
current resource. Following a visible target exposes the reverse relationship
back to the original resource, subject to current authorization.

**Agreed:** Provide add and remove actions only to authorized users. Select
targets through bounded remote search; use server pagination for relationship
lists. Follow Wathiq's standard table presentation, loading, empty, and error
states, translation rules, and LTR/RTL behavior. Refresh both endpoint views
after mutation, including when revisiting a previously opened page.

## 7. Disposition

Read this section alongside the common
[Disposition specification](disposition.md) and, for destruction jobs, the
[Destruction Process extension specification](destruction-process.md).

Relationships shall not prevent adding an otherwise admissible disposition
unit to a disposition job. Links within one disposition unit or between units
in the same job do not block and need not be removed. A link to a unit outside
the current job, including a unit in a different job, blocks final disposition
until the Records Officer removes the link during review from either endpoint. This applies to both aggregation links and record links,
regardless of whether the related disposition unit is otherwise eligible.
Existing admission and execution blockers still apply.

Show each blocking relationship, its name, and its related aggregation or
record during review. If the target is inaccessible, show a redacted blocker
and its generic reason without disclosing protected details. Recheck links
immediately before the final action; an earlier review is not sufficient
authorization to execute disposition.

Disposition review shall clearly show the Records Officer and Records Manager
when aggregations or records within the job are linked to one another. Show
the relationship name, both endpoints, and their containing aggregations and
disposition units, subject to existing authorization and redaction rules.
Explain whether each link is within one disposition unit, between units in
the same job, or to a unit outside the current job. The first two cases do not
block; the third requires removal. Do not hide these links merely because
both endpoints are included in the job. An internal link shall not be presented
as a blocker requiring removal.

### Disposition review UI

The Records Officer and Records Manager review screens shall include a visible
**Relationships within this job** section. Its summary shall appear without
requiring either user to open individual aggregations or records. Show counts
of non-blocking links within a disposition unit, non-blocking links between
units in the same job, and blocking links to units outside the job. Include
both internal-job links and links leaving the job in this section. Count each bidirectional link once.

Provide a server-paginated relationship table showing the relationship type,
both endpoint resources and their kinds, containing aggregations for record
endpoints, their disposition units and
current jobs (or no active job), subject to authorization, and an
explicit blocking status with its explanation. Display **Within one
disposition unit — does not block**, **Within this job — does not block**, or
**Outside this job — remove link before disposition**, as applicable; color alone is insufficient.
Allow filtering by blocking status and navigating to authorized endpoints.
Apply the existing redaction rules to inaccessible endpoint details.

Offer the removal action on blocking rows only when the user's privileges and
authorization permit it, and collect the required review reason. Refresh the
table, summary counts, and disposition-blocker state after removal. When no
aggregation or record links involve the job, show an explicit empty state. Follow
Wathiq's standard table, loading, error, translation, and LTR/RTL requirements.

### A link added after review

For example, the Records Officer reviews a job containing aggregation A.
Someone then links a record in A to a record in aggregation B, which is outside
the job. The new link blocks final disposition. An authorized Records Officer
must remove it before disposition can proceed. This relationship change does
not itself require repeating the approval process. Always check the current
links before execution; do not rely on the list shown during an earlier review.
Other changes remain subject to the destruction specification's approval rules.

### Agreed disposition rules

- Apply the blocker to every aggregation and record relationship type, in
  both directions.
- Assess links from all aggregations and records within the disposition unit,
  including descendants, so a child aggregation or record link cannot evade
  the check.
- Links within one disposition unit or between disposition units in the same
  job do not block disposition and do not require removal.
- Links between units in different jobs block disposition of both units;
  removing the single bidirectional link from either endpoint clears that
  relationship blocker for both. Links to units with no active job also block.
- Eligibility alone does not clear a blocker. Joining the same job clears it
  without removing the link. Recheck current job membership before execution;
  removing a related unit from the job makes the retained link blocking again.
- Require both `disposition.jobs.manage` and `relationships.link` for an
  officer to remove a link during review, with a recorded reason and current
  view authorization on both endpoints. Redacted targets do not authorize
  removal.
- Removal clears that relationship blocker at both endpoints. It does not
  clear other relationships or retention, hold, vital-status, security, or
  other disposition blockers.

No recursive eligibility calculation is needed: current job membership
identifies whether a link blocks. Final-action checks must coordinate with link
changes and job-membership changes so that neither can evade enforcement.
Preserve link-removal evidence under existing audit access rules. Retain same-job and internal-unit links after disposition, including their
endpoint identifiers, relationship type, and direction. Their retained evidence
remains subject to the common disposition specification's metadata and access
restrictions; destroyed endpoints are not ordinary navigable resources.

If destruction is interrupted, retained links between units in that same job
remain non-blocking while unfinished work is retried or resumed. For example,
if A finishes but B fails, their link does not prevent retrying B in that job.
Completed work remains recorded; the job is incomplete until all required work
succeeds.

If a partially completed destruction job is terminated and an unfinished unit
enters a new job, retain its links to units already destroyed in the former job
as historical evidence. Such links do not block its later destruction and do
not permit ordinary navigation to destroyed endpoints. Links to resources that
remain live still follow the normal same-job or outside-job blocking rule.

## 8. Audit and verification

Audit link creation and removal, including actor, endpoints, type, direction,
time, and removal reason during disposition review. Audit catalogue changes.
Apply existing event-history access and redaction rules to this evidence.

| Requirement | Required verification evidence |
| --- | --- |
| REL-01 Separate aggregation and record links | Both endpoint kinds supported; unsupported cross-type links rejected |
| REL-02 Named reverse relationship | Forward, reverse, symmetric, duplicate, and atomic-removal checks |
| REL-03 Separate extensible catalogues | Correct type scope, administration authorization, and deactivation checks |
| REL-04 Preserve containment | Creating and removing links leaves parentage, filing, and inherited policy unchanged |
| REL-05 Navigate both ways | Live-browser navigation and post-mutation freshness in LTR and RTL |
| REL-06 Redact inaccessible targets | UI and API disclosure checks before and after access revocation |
| REL-07 Enforce link privileges and resource access | Management succeeds with the global privilege and view authorization on both endpoints despite absent metadata-edit permissions; fails without the privilege or either endpoint's view authorization; clearance and catalogue/link privilege separation checks |
| REL-08 Admit but block final disposition | Admission succeeds despite this blocker; links within a unit or the same job do not block or require removal; links outside the job block until removal from either endpoint; no-active-job, membership-change, descendant, and concurrency checks |
| REL-09 Audit changes | Attributable link/catalogue events and protected review reasons |
| REL-10 Bounded relationship UI | Server pagination, bounded search, selected-value retention, and repeated-navigation checks |
| REL-11 Explain aggregation and record links within the job | Live-browser Officer and Manager review verifies visible summary, unique-link counts, paginated table, explicit blocking explanations, authorized navigation/removal, redaction, post-removal refresh, empty/loading/error states, and LTR/RTL presentation against existing Wathiq tables |

| REL-12 English and Arabic localization | Both privileges and both catalogues have localized labels; forward/reverse names remain correct in English/LTR and Arabic/RTL; UI key coverage, provenance, ordering, placeholders, terminology, and artifact checks pass |
| REL-13 Historical links after terminated partial destruction | Retained links to already-destroyed units do not block later destruction of the unfinished unit; links to live units retain normal blocking behavior; historical access restrictions remain enforced |

Implementation and test evidence must be attached to these requirements before
the feature is declared complete. Database-backed verification must use a new
disposable database for each run and clean it up afterward.
