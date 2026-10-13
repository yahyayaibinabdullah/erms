# Administration Settings Specification

**Status:** Approved
**Approved:** 12 October 2026
**Prepared:** 12 October 2026
**Revision:** 1.1
**Amendment approved:** 13 October 2026

## 1. Purpose

Wathiq provides a reusable **Administration → Settings** page for
organization-wide business settings. Settings are grouped by area, rather
than having a separate administration page for each individual setting.
Future approved settings can use this page; this specification does not
authorize additional settings by itself.

## 2. Settings page

The settings registry assigns each setting an explicit `category`. The API
supplies the category and its translated label for UI grouping. Categories are
application-defined, not inferred from setting keys or duplicated in the
`application_settings` table. Administrators edit values, not categories.

The search and indexing group includes the Audit Trail search result limit:
a positive whole number, default 1,000, limiting matching results and count
work. It is database-managed and editable, takes effect through the general
30-second cache, and requires no restart. The API supplies the effective limit
to the Audit Trail UI.

The page groups settings by their business area and shows each setting's
name, current value, allowed choices, and explanation of its effect.
Authorized administrators can save changes through this page. Business
settings stored here do not require environment-variable changes or a service
restart.

Every setting displays concise explanatory text beside its control, in the
user's interface language. It explains the purpose, data type in plain
language, units where applicable, allowed values or limits, default or unset
meaning, relevant dependencies, and when a change takes effect. Keep this text
visible without requiring a tooltip. Use familiar terms such as “whole number”
or “email address” rather than database types. Explanations must not reveal
saved credentials.

All database-managed settings are editable by an authorized administrator.
Related settings are saved together, validated as a set, and committed with
their audit history in one operation. This includes the classification scheme
and its two destination classifications, and related SMTP settings. Invalid
values or a concurrent edit prevent the whole submitted group from being saved.
Secret values remain masked and are changed through replacement inputs.

General settings use the approved 30-second cache lifetime. Job creation,
artifact saving, and email sending read current committed settings directly as
defined in Application Configuration. Migration must preserve existing
non-default values before consumers switch to database-only configuration.

Settings administration requires **`app.settings.manage`**, granted to the
**System Administrator** profile. This single privilege covers the reusable
page and its settings operations, including protected SMTP configuration.
It is not included in `disposition.jobs.manage` or inferred from unrelated
administration privileges. The System Administrator profile receives the
privilege. The [Application Configuration specification](application-configuration.md)
defines the shared registry, storage, protected-secret handling, and fresh
operation reads; no parallel settings store is introduced.

Local development upgrades follow [Application Configuration section 9](application-configuration.md#9-rollout-and-compatibility):
explicit per-database preview and migration preserve existing non-default `.env`
values before database-only operation. Startup checks migration readiness;
it does not import values automatically. Subsequent edits use this Settings page.

## 3. Disposition settings

The **Disposition** group contains **Destruction review route**, with
**Standard** as its default, with **Simplified** and **Records Manager Only**
as alternatives. Records Manager Only assigns preparation, review, approval,
and external correspondence to the Records Manager without the other three
participants. The setting's explanation makes this absence of independent
internal review clear. Existing jobs retain their saved route.
The [Destruction Process specification, Section 5.4](destruction-process.md#54-organization-wide-review-route)
defines the routes and when a changed setting takes effect.

For Destruction review route, the organization-wide saved setting is the source of truth. The Records
Officer does not choose or override the route when creating a job. Each new
job stores the route in effect at creation; later setting changes affect new
jobs only.

The Disposition group also contains three organization-wide destination
settings: **Classification scheme**, **Uploaded evidence classification**,
and **Generated reports classification**. All three are selectors with
server-side type-ahead filtering that starts after two typed characters, and
a **Browse** button. Searches return bounded results and retain selected
values; a selected ID is fetched individually when needed.

The Classification scheme selector searches and browses schemes and selects
a scheme, not a classification. Each classification selector searches within
the selected scheme and its Browse button opens a drill-down browser showing
the scheme, branch classifications, and terminal classifications. Users may
navigate branches, but may select only a terminal classification as the
destination. The browser shows the selected scheme as context and does not
allow choosing a classification from a different scheme. Scheme lists and
each hierarchy branch are independently server-paginated; Wathiq must not
download the complete scheme hierarchy for searching or browsing.

Both destination classification selectors
store validated classification IDs rather than free-text numbers. A saved
combination must place both classifications in the selected scheme; an
inconsistent combination is rejected. No classification numbers are hardcoded
or required as defaults.

Each artifact is saved as a record in the latest open root aggregation under
its corresponding selected classification. The system-generated Certificate
of Destruction (Digital) is an explicit exception to generated-report routing:
it is evidence and uses **Uploaded evidence classification**. Section 17.2 of the Destruction
Process specification defines these destinations. These settings are selected
by an authorized administrator, not by the Records Officer per job.

Each new artifact save uses the current scheme and destination settings, even
for an existing job. Earlier saved records stay in their original destinations.
If a destination differs from the one used for earlier job artifacts, the
relevant task warns the user of both facts before saving, displaying destination
details only as authorized. The warning alone does not block saving.

The Disposition group includes **External archives authority name**, defaulting
to **Sharjah Archives**, and **External archives authority email address**,
which has no fabricated default and must be a valid email address when set.
The name appears as the recipient authority on each generated Request for
Destruction Form. The email address is the destination for the task's send
actions for both the Records Officer's Request for Destruction Form and the
Records Manager's Certificate of Destruction (Digital). Both actions use the
shared Email settings, support repeat sending, and display per-attempt status
as specified in the destruction process. Earlier generated forms and send history retain the name and address
used; editing settings does not rewrite them.

## 4. Email settings

The reusable **Email** settings group provides the SMTP configuration needed
for server-side outgoing mail:

- SMTP server hostname and port;
- connection security: STARTTLS or implicit TLS;
- authentication enabled, username, and password when authentication is enabled;
- sender email address and sender display name;
- optional reply-to email address; and
- connection and send timeout.

SMTP credentials are protected secrets: passwords are masked, never returned
as readable saved values, and excluded from ordinary logs and history. Saved
credentials must be protected at rest. Certificate validation remains enabled.
Port defaults follow the selected security mode: 587 for STARTTLS and 465 for
implicit TLS. No server, credential, or sender address is invented at deployment.
The timeout defaults to 30 seconds. Sender and reply-to addresses are validated.
Settings changes apply to subsequent send attempts without a service restart.
Only administrators with the confirmed settings-management authority may
manage these settings; Records Officers and Records Managers use them without
seeing credentials.

## 5. Governance Custody warnings

If any disposition destination setting has not been configured after deployment,
the **Governance Custody** page shows a warning identifying each missing setting:

- Classification scheme;
- Uploaded evidence classification; or
- Generated reports classification.

The warnings direct authorized administrators to
**Administration → Settings → Disposition** to complete configuration. Wathiq
does not silently supply a classification or scheme. Each warning remains
until its setting is configured and is cleared when configuration is completed.
The warning does not grant permission to change settings.

Destruction review route is not a missing-configuration warning when its
defined Standard default applies.

Governance Custody also warns when either configured destination classification
has no suitable open root aggregation. The latest destination is the root
whose date opened is most recent among roots that are still open under that
classification; equal opening dates are resolved by selecting the larger
aggregation ID. The relevant evidence or report task is blocked and displays
its own warning until a suitable open root exists. Closed or child aggregations
and other classifications cannot be substituted. Warnings clear after the
destination is checked again and the missing-root condition is resolved.

## 6. Verification requirements

- The reusable Settings page groups the approved setting under Disposition
  and displays its value and effect clearly.
- Only administrators authorized through `app.settings.manage`
  can change the setting.
- Standard is the default; only Standard and Simplified are accepted.
- Saved changes take effect for new jobs without a restart and do not change
  routes already saved on existing jobs.
- Both destination classification settings store valid IDs belonging to the
  selected scheme, using bounded selectors without hardcoded numbers; earlier
  records retain their saved destination references.
- All three selectors start type-ahead search at two characters, use bounded
  server results, retain selected values, and provide Browse controls. Scheme
  browsing selects a scheme; classification browsing drills through independently
  paged branches to terminal-only selections within that scheme.
- Governance Custody identifies each unset destination setting after deployment,
  directs administrators to Disposition settings, and clears the corresponding
  warning after configuration without granting settings-management authority.
- Missing open-root destinations produce both task and Governance Custody
  warnings and prevent task continuation; selection uses the most recent
  opening date among still-open roots under the configured classification.
- Equal opening dates select the larger aggregation ID. Changed destination
  settings apply to new artifact saves for existing jobs, with task warnings
  and preservation of earlier saved records.
- Authority name defaults to Sharjah Archives, configured recipient addresses
  are validated, and generated forms preserve their original recipient name.
- SMTP validation, TLS and certificate verification, authentication, protected
  secret storage and masking, timeout handling, and new-send configuration
  freshness are verified without exposing credentials in logs or history.

## 7. Implementation alignment

The privilege name and System Administrator grant are resolved. Shared settings
persistence and protected SMTP-secret handling follow Application Configuration
Sections 5.6–5.7, 6.1, 7, and 8. The general migration proposals still marked
open in that draft are separate from the resolved disposition and email rules.
