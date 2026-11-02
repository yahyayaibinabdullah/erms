# Internationalization and User Preferences — Technical Specification

**Status:** Approved — implementation baseline  
**Project:** ERMS / Wathiq  
**Prepared:** 26 September 2026  
**Revision:** 0.25 — English source text filter in Translation Administration (28 October 2026)

## 1. Purpose

This specification defines Wathiq's internationalization, localization,
bidirectional-layout, user-language, and working-timezone behavior. It also
defines multilingual values for selected domain entities and an administrative
workflow for maintaining UI translations without deploying application code.

English and Arabic are the initial supported languages. The design must permit
additional languages without changing API shapes or adding one database column
per language. English is the system default and the authoritative fallback.

> **Mandatory canonical-artifact rule for every WebUI developer and agent:**
> administrator corrections made in a database are not visible to source-code
> development by themselves. After administrative review, the complete
> exported language artifact must deliberately replace the corresponding
> checked-in canonical artifact. Future development must merge new catalogue
> keys into that checked-in file by `message_key`, preserve administrator
> wording, and generate only genuinely new or explicitly invalidated entries.
> Regenerating the entire language artifact over reviewed administrator text is
> prohibited. Section 7.8 defines the required procedure and verification.

## 2. Goals and scope

This subsystem includes:

- English (`en`) and Arabic (`ar`) UI languages;
- a registry through which additional languages can be enabled later;
- per-user language and IANA working-timezone preferences;
- complete translation of user-visible application chrome and messages;
- an administrative UI for database-backed UI translations;
- full right-to-left presentation for Arabic and other RTL languages;
- multilingual names, titles, and descriptions for the domain entities listed
  in section 11;
- locale-aware selector labels, searching, sorting, formatting, and validation;
- end-to-end date, time, and timezone rules;
- caching and invalidation of translation resources;
- optimistic concurrency, audit history, security, migration, and tests; and
- compatibility with existing rows and API consumers.

This specification does not include:

- runtime automatic translation or automatic publication of machine-generated
  text; the one-time best-effort Arabic draft-generation phase in section 21
  is included and always requires administrator review;
- translating user-authored record content or uploaded files;
- translated variants of Aggregation or Record titles/descriptions; those
  authoritative values remain exactly as entered under section 11.1;
- translating immutable identifiers, codes, record numbers, aggregation
  numbers, email addresses, filenames, or audit evidence;
- changing stored instants when a user changes timezone;
- locale-specific calendars other than the Gregorian calendar;
- localized URLs; or
- enabling a language before its release-readiness checks have passed.

## 3. Terminology

- **Language tag:** a normalized BCP 47 tag, initially `en` or `ar`.
- **Locale:** language-dependent formatting behavior. The initial effective
  locales are `en` and `ar`; deployment-specific regional tags may be enabled
  later.
- **Working timezone:** the user's preferred IANA timezone, such as
  `Asia/Dubai`. It is not a fixed UTC offset.
- **UI message:** application-owned text such as a label, button, tooltip,
  validation message, heading, status, empty state, or notification.
- **Entity translation:** a translated value belonging to one controlled or
  administrative domain row, such as a classification's Arabic title.
- **Canonical value:** the existing ordinary text column. For the initial
  rollout this is the required English/default value.
- **Effective value:** the value selected by the fallback rules in section 5.
- **RTL language:** a language whose configured direction is right-to-left.

## 4. Language registry and defaults

### 4.1 Initial languages

The language registry initially contains:

| Tag | Display name | Native name | Direction | Enabled | Default |
| --- | --- | --- | --- | --- | --- |
| `en` | English | English | `ltr` | yes | yes |
| `ar` | Arabic | العربية | `rtl` | yes | no |

Language tags must be normalized and compared case-insensitively according to
BCP 47 conventions. API responses return the registry's canonical spelling.

Exactly one enabled language is the system default. The initial default is
English. Changing that default later is an explicit system-administration
operation and must not rewrite any user's saved preference.

### 4.2 Extensibility

Adding another language requires a language-registry row, UI catalogue
coverage, direction, formatting configuration, fonts, search configuration,
and the release-readiness checks in section 19. It must not require adding a
column to every translatable entity.

Disabling a language prevents new preference selection and ordinary editing in
that language. Existing translations remain stored. A user whose saved
language has been disabled receives the system default until choosing another
enabled language; their stored preference is retained so it can become
effective again if the language is re-enabled.

### 4.3 Initial translation set for a new language

Creating a supported language must also create a complete editable draft
translation set for every current UI message definition. When no approved
machine-translation seed is selected, each draft copies `default_text` exactly
from English, including every named placeholder and escaped brace. These rows
use `origin = source_copy` and `status = draft`.

A source copy is a working aid and is visibly labelled **English source copy**
in administration. For every non-source language, `source_copy` means that no
translation decision has been made and is therefore a publication restriction.
It cannot be published individually, through the bulk workflow, through a
direct API request, or by bypassing the application and writing to the database.
The runtime uses the ordinary fallback rules until the value is replaced by an
actual translation. Saving wording deliberately, including intentionally
unchanged proper names or acronyms, changes its origin to `manual` and makes the
valid draft eligible for review and publication.

If an approved machine-translation seed is chosen instead, generated drafts
use `origin = generated` and retain their generation metadata for audit and
quality review.
Machine generation may replace untouched `source_copy` rows but must not
overwrite manual, imported, reviewed, or published values.

When a new UI message definition is added later, an English source-copy draft
must be created for every supported non-English language that has no generated
or manual value. This keeps every language's administration queue complete
without treating untranslated English copies as translation coverage.

## 5. Language resolution and fallback

For an authenticated request, the effective language is resolved in this
order:

1. the authenticated user's saved, enabled language;
2. the enabled system default language; and
3. `en` as the final application safety fallback.

The `Accept-Language` header must not override an authenticated user's saved
preference. It may select an enabled language on anonymous surfaces such as the
login page. The login page otherwise uses English. After authentication the
saved preference becomes authoritative immediately.

For a translatable value, fallback is deterministic:

1. an exact nonblank translation for the effective language tag;
2. for a regional tag, a nonblank translation for its base language;
3. the canonical English/default column;
4. a stable identifier or localized **Unnamed** placeholder only where the
   canonical field is historically nullable.

Blank or whitespace-only strings are not valid translations and behave as
absent values. Validation uses the normalized value after trimming Unicode
whitespace. A blank value must never be persisted as a translation, published,
included in a compiled catalogue, cached, or served to users. Missing
translations must never produce a blank navigation item, selector option, or
table cell. Wathiq does not combine text from two languages within one value.

## 6. User preferences

### 6.1 Behavior

Each person user may choose:

- **Language:** one enabled language, initially English or Arabic.
- **Working timezone:** one valid IANA timezone identifier.

Until a preference row exists, language is English and working timezone is the
application's configured default working timezone. The approved
[Application Configuration](application-configuration.md) section 5.1 supersedes
this section's earlier environment ownership: `DEFAULT_WORKING_TIMEZONE` is a
shared PostgreSQL setting, initialized canonically to `Asia/Dubai`. The registry
and canonical schema own that initial default; other application/browser code
and preference rows must consume the API's effective value rather than hard-code
it. Authorized Settings edits propagate within 30 seconds without restart.
Existing non-default legacy values require the explicit reviewed migration in
Application Configuration section 9. Shell or `.env` values no longer override
the database after this consumer cutover.

The API is the authority for this setting, validates it against pinned IANA
tzdata at startup, and returns it through the authenticated bootstrap/preferences
contract. The WebUI consumes that returned value and must not maintain a
separate potentially divergent default. A missing, blank, or invalid
`DEFAULT_WORKING_TIMEZONE` is a configuration error that prevents the affected
API from becoming ready; the WebUI cannot use an environment substitute. It must
not silently infer or fall back to the
browser, API server, frontend server, container, database, host operating-system
timezone, UTC, or a timezone literal embedded in code. A user's valid saved
working-timezone preference always takes precedence.

Service accounts do not require an interactive preferences UI. If a
human-readable presentation timezone is required for a service-account
operation and no explicit timezone is supplied, it uses the validated
`DEFAULT_WORKING_TIMEZONE`. API instant fields remain canonically serialized in
UTC and persisted instants are unaffected.

The Preferences page is available to every authenticated person user. Saving a
language preference changes the current UI without requiring logout. Saving a
timezone preference immediately changes subsequent display and input
interpretation without modifying stored timestamps.

### 6.2 Data model

A one-to-one table avoids widening the security-sensitive `users` row and
allows preferences to evolve independently:

#### `user_preferences`

| Column | Type | Rules |
| --- | --- | --- |
| `user_id` | `bigint` | Primary key; references `users(id)` with `ON DELETE CASCADE` |
| `language_tag` | `text` | Required; references an enabled or historically registered language |
| `working_timezone` | `text` | Required IANA zone identifier |
| `date_created` | `timestamptz` | Required; defaults to `CURRENT_TIMESTAMP` |
| `date_updated` | `timestamptz` | Required; automatically maintained |
| `version` | `bigint` | Required positive optimistic-concurrency value |

Rows are created lazily on first save. Read operations synthesize the defaults
when no row exists. The API must validate timezone names against the runtime's
pinned IANA tzdata version and must reject abbreviations such as `GST`, `EST`,
and raw offsets such as `+04:00`.

Preference changes are personal presentation settings. They do not change the
user entity's version or create a governed user-update event. They should
produce a bounded security-safe preference audit event containing old and new
language/timezone values, actor, time, and request correlation ID.

## 7. UI message catalogue

The signed-in account menu displays the user's, assigned roles', and organization
units' localized names using the effective user language and the existing entity
fallback rules. Avatar initials use the displayed user name. Email addresses,
codes, identity IDs, and authorization behavior remain unchanged. Login and
`/auth/me` supply localized projections alongside canonical names so the menu
does not fetch each assigned entity separately.

### 7.1 Key contract

Every application-owned user-visible message must be addressed by a stable,
semantic and contextual key, for example:

```text
navigation.records
records.actions.close_aggregation
records.fields.date_originated
records.validation.title_required
records.selector.no_results
authentication.errors.session_expired
```

Keys must describe meaning and context rather than English wording. A key uses
the hierarchy `<context>.<component-or-purpose>.<meaning>`. The context is the
feature or user task in which the text occurs, such as `records`,
`classification`, `authentication`, `preferences`, or `shared`. A word such as
**Open**, **Close**, **Record**, or **User** must have separate keys when it has
different grammatical or semantic meanings. A `shared` key may be reused only
when its meaning, grammatical role, audience, and interpolation contract are
identical in every location.

Each definition must supply translator guidance that states:

- the semantic meaning and intended user outcome;
- the grammatical role, such as action verb, noun, heading, or status;
- the screens/components and common locations where it appears;
- relevant domain distinctions or wording that must not be confused;
- all placeholders, their types, and an example rendered message; and
- any length, accessibility, or tone constraint.

Source code must not concatenate translated fragments to construct a sentence.
Contextual variants are preferred to forcing one translation into unrelated
uses.

The catalogue covers, at minimum:

- navigation, breadcrumbs, tabs, page titles, section headings, cards, and
  dashboard text;
- labels, field names, placeholders, hints, tooltips, buttons, menu items,
  links, action labels, confirmations, and dialog text;
- table/list headers, filters, pagination, sort labels, result counts, loading,
  empty, partial, and error states;
- every user-space error, including frontend validation, API problem
  presentation, authentication, authorization, concurrency, upload/download,
  timeout, connectivity, and unexpected-failure messages;
- status names, enum labels, badges, date/time labels, units, and accessible
  names;
- notifications, toasts, upload progress, download actions, and print views;
- administrator-facing screens; and
- client-rendered strings in JavaScript components.

Developer logs, database diagnostics, stable API error codes, and audit event
codes remain language-neutral. Every error code that may reach a user-facing
surface must map to a contextual catalogue key and translated message. The UI
must not expose raw exception text, stack traces, database messages, or an
untranslated server message. An unknown code is presented through a translated
generic error key and retains only a safe correlation/reference ID for support.

### 7.2 Message template syntax

Messages that require dynamic values use a deliberately small named-placeholder
syntax:

```text
Record {record_number} was moved to {aggregation_title}.
Your session expires at {expires_at}.
{field_name} is required.
```

The rules are:

- a placeholder is `{name}`, where `name` contains lowercase ASCII letters,
  numbers, and underscores and begins with a letter;
- literal braces are written as `{{` and `}}`;
- positional placeholders, expression evaluation, conditionals, property
  access, functions, and embedded markup are prohibited;
- the definition's `parameter_schema` declares every placeholder and its type,
  chosen from `text`, `integer`, `decimal`, `date`, `datetime`, `duration`,
  `identifier`, and `url`;
- the renderer rejects missing, additional, or differently named parameters;
- typed values are formatted using the effective language and working timezone
  before safe interpolation; and
- each value is escaped and bidirectionally isolated independently.

Each placeholder represents one complete semantic value, such as a count,
record number, person name, or formatted date. A placeholder contract must
never expose source-language grammar or presentation mechanics such as a
plural suffix (`s`), capitalization/lowercasing instruction, verb ending,
punctuation fragment, or partial word. Administrators must preserve every
declared placeholder name and its braces exactly, but may move the placeholder
to the position required by the target language. They cannot add, remove, or
rename placeholders while editing a translation; a genuinely different
contract requires changing the authoritative definition and reviewing every
affected language.

Plural or gender variants use separate explicit contextual keys selected by
application logic, for example `records.results.count_one` and
`records.results.count_other`. This keeps the stored syntax understandable to
administrators and avoids embedding a programming language in translations.
All variants must declare the same parameter schema unless their guidance
explicitly documents why they differ.

### 7.3 Catalogue data model

#### `supported_languages`

Stores the registry described in section 4, including `language_tag`, English
and native names, `direction`, enabled/default flags, formatting configuration,
`version`, and timestamps. Database constraints enforce one default and valid
directions (`ltr` or `rtl`).

#### `ui_message_definitions`

| Column | Purpose |
| --- | --- |
| `message_key` | Stable primary key |
| `context_group` | Required administration grouping, normally the first key segment |
| `default_text` | Required English source text |
| `semantic_meaning` | Required explanation of meaning and intended outcome |
| `common_locations` | Required JSON list of screens/components where commonly shown |
| `translator_guidance` | Required grammatical, domain, tone, length, and accessibility guidance |
| `parameter_schema` | JSON description of allowed named parameters |
| `rendered_example` | Required representative message with sample values |
| `is_html` | False by default; true only for reviewed rich text |
| `date_created`, `date_updated` | Audit timestamps |
| `version` | Optimistic-concurrency value |

#### `ui_message_translations`

| Column | Purpose |
| --- | --- |
| `message_key` | Definition foreign key with `ON DELETE RESTRICT` |
| `language_tag` | Language foreign key with `ON DELETE RESTRICT` |
| `translated_text` | Required nonblank message using the syntax in section 7.2 |
| `status` | `draft` or `published` |
| `origin` | `source_copy`, `manual`, `generated`, or `imported` |
| `generation_metadata` | Nullable bounded JSON recording generator/model/version and generation time |
| `date_created`, `date_updated` | Audit timestamps |
| `updated_by_user_id` | Nullable actor foreign key using the project's audit-safe deletion convention |
| `reviewed_by_user_id`, `date_reviewed` | Records the administrator review associated with publication |
| `version` | Optimistic-concurrency value |

The primary key is `(message_key, language_tag)`. English source text remains
available in the definition even if a translation row is absent. Only
published translations are served to ordinary users.

### 7.4 Administrative translation screen

General translation administration requires the reserved global privilege
`localization.administer` (**Administer localization**). This privilege is
seeded into the System Administrator profile (and the protected compatibility
profile that contains every privilege) and is not seeded into information-
governance or ordinary-user profiles. Possessing an unrelated entity-metadata
right does not grant catalogue administration.

`localization.administer` permits access to the translation-administration
screen and the creation, editing, review, publication, import, generation, and
cache invalidation of supported languages and UI message translations. It does
not grant permission to edit translated values belonging to domain entities;
those use the owning entity's metadata authorization described in section
10.4. A later separation of catalogue read, edit, or publish duties requires a
separately approved authorization amendment; this specification deliberately
uses one clear privilege for the initial subsystem.

The screen groups keys first by `context_group`, then by component/purpose, so
administrators can distinguish identical English words used in different
contexts. Groups are collapsible and display source-copy, translated, draft,
generated, reviewed, published, and missing counts. The screen provides language
selection; coverage counts; pagination; and a side-by-side English source and
selected-language editor.

Selecting any supported-language card displays that language's workflow
statistics: active keys, drafts, unreviewed drafts, reviewed translations,
published translations, unpublished translations, and translations flagged
for quality attention. These statistics are not limited to Arabic. Guidance
that is genuinely language-specific, such as the approved Arabic terminology
reference, applies only to that language.

The listing provides these explicit filters:

| Filter | Behavior |
| --- | --- |
| **Key** | Case-insensitive partial match against the complete `message_key` |
| **English source text** | Case-insensitive partial match against the authoritative English `default_text`, independently of the selected translation language |
| **Translated text** | Case-insensitive partial match against `translated_text` for the selected language |
| **Semantic meaning** | Case-insensitive partial match against the definition's `semantic_meaning` guidance |
| **Status** | Controlled selection of all, `draft`, or `published` |
| **Origin** | Controlled selection of all, `source_copy`, `manual`, `generated`, or `imported` |

Context, review state, and **Needs attention** remain available as additional
filters. The six primary filters are individually labelled and must not be
hidden inside one ambiguous general-search field. Active filters combine with
logical AND, while an empty text filter or **All** selection does not constrain
results. Text filters are debounced, changing any filter resets pagination to
the first page, and the result summary reflects the filtered total.

Filter state is preserved while an administrator opens, edits, reviews, or
returns from a key so the located item is not lost. A clear-all action restores
the unfiltered listing. Filtering must be performed by a bounded server query
when the complete catalogue is not already loaded; the WebUI must not fetch the
entire catalogue merely to filter it locally.

The editor always shows semantic meaning, grammatical role, common locations,
translator guidance, parameter definitions, and the rendered example next to
the source and translation. Source-copy and generated drafts are visibly
marked and cannot be mistaken for reviewed text. The screen uses the standard
Wathiq table/list presentation and has deliberate loading, empty, validation,
conflict, and error states.

Every translation field and catalogue result must expose whether it currently
has a valid translation. For administration purposes, a translation is valid
when it is nonblank after normalization, uses exactly the defined named
placeholders, has valid template syntax, and contains no disallowed markup.
Its origin does not make it valid or invalid.

Missing or invalid values use a restrained but unmistakable treatment: a small
warning/status icon, a concise status such as **Needs translation** or **Fix
placeholders**, and a subtle pale-amber background or inline-start border on
the affected field/card. The treatment must not dominate valid entries or turn
the whole screen into a warning panel. Red is reserved for a validation error
being actively corrected or a failed publication attempt. Color is never the
only signal.

The status indicator has a localized tooltip and accessible name containing
the exact reason. Opening or focusing the field reveals concise inline guidance
and, for placeholder problems, identifies missing and unexpected placeholder
names. Context-group and page summaries include invalid and missing counts, and
the screen provides **Needs attention** filtering and sorting so administrators
can work through affected keys efficiently. Collapsed groups containing an
invalid value retain a small count indicator; invalid fields must not disappear
solely because their group is collapsed.

If the translation editor is empty or contains only whitespace, it must show a
clear inline error such as **Enter a translation before publishing** and mark
the affected key as incomplete. Save and Publish controls for that value are
disabled or rejected with the same accessible explanation. A bulk review or
publication action lists every affected contextual key, moves focus to the
error summary, and publishes nothing until all selected values are valid. The
administrator's entered text remains available for correction. An empty input
may be discarded or used to delete an unpublished draft through an explicit
action, but it must not create a blank translation row.

Editing is row/key scoped. Each translation update requires that translation
row's `version` through `If-Match`; updating one key must not submit or replace
the full catalogue. Two administrators can edit different keys concurrently
without locking each other out. If they edit the same key and language, the
first commit succeeds and the stale update receives `409 Conflict` with the
current value and version. The UI preserves the administrator's draft and
offers review-and-reapply; it must never silently overwrite either change.

Definition and translation writes are transactional. Publication validates
that the normalized translation is nonblank, placeholders exactly match the
definition, the template compiles, and disallowed markup is absent. The API and
database enforce the same nonblank rule even if a client bypasses the WebUI. A
failed publication leaves the previously published catalogue and revision
unchanged; invalid text cannot enter caches or become visible through a partial
publish. Origin records provenance and determines one narrow eligibility rule:
a non-source-language `source_copy` is not a translation and cannot be
published. Publishing an eligible draft is itself an explicit system-administrator review
action and records the reviewer and review time. Every successful change produces
immutable event history with before/after values and a mandatory nonblank
change reason.

#### 7.4.1 Draft review, publication, and export workflow

The workflow uses the same rules for every supported language:

1. Every translation value begins as a draft. A draft may contain the original
   English wording, a machine-generated translation, an imported translation,
   or wording entered by an administrator.
2. `source_copy`, `generated`, `imported`, and `manual` describe where the text
   came from. For a non-source language, `source_copy` is an untranslated
   fallback and cannot be published. Generated, imported, and manual drafts are
   eligible when otherwise valid. English source baselines remain publishable
   as English, and a deliberately unchanged non-English value becomes eligible
   after an administrator saves it as `manual` with a reason.
3. Publishing is an explicit review action performed by a user with the
   `localization.administer` privilege. The system records that user and time
   as both reviewer and publisher. Publication is rejected when the text is a
   non-source-language `source_copy`, is blank, or fails template, placeholder,
   or markup validation.
4. The supported-language cards at the top of Translation Administration are
   the explicit language selector for administration work. The selected card
   controls the keys being listed and every language-specific action. There is
   no separate language filter among the key filters and no second language
   selector inside Export or **Review and Publish All**. After confirmation,
   all eligible valid drafts for the selected language and scope are reviewed
   and published together. Non-source-language source copies are excluded and
   reported as awaiting translation. If any selected eligible draft is invalid,
   nothing is published.
   The routine generated-draft flag `needs_human_review` is a review reminder,
   not a translation defect. It must not block this explicit review-and-publish
   action or its preview. Successful publication removes that marker, preserves
   the remaining generation provenance, and records the reviewer and publisher.
   Other quality flags (including unknown flags), invalid placeholders, blank
   text and malformed markup still block the complete selected batch. Failed
   or stale submissions must leave flags, publication and revision unchanged.
5. Context-level bulk actions apply to the language and context visibly being
   viewed. They use the same validation and all-or-nothing behavior.
6. English definitions are the original application wording and may be
   exported without first creating published translation rows. A published
   English revision takes precedence over the original wording. When the
   administrator explicitly chooses to include reviewed but unpublished
   changes, a newer reviewed English draft takes precedence for that export.
7. For every other language, export uses published text by default. The same
   explicit option may include newer reviewed but unpublished drafts.
8. Exporting downloads a file for the selected administration-language card
   and changes nothing in Wathiq. An import file declares its own language;
   Wathiq displays and validates that declared language rather than using or
   overriding it with the selected card. Importing stores validated values as
   drafts and publishes nothing automatically.

English definitions are the source language, so the non-source publication ban
does not apply to their baseline. English-to-English editorial revisions remain
supported as manual drafts. For other languages, an administrator who
deliberately retains identical wording must save that value as `manual` before
review and publication.

### 7.5 Translation keys during active WebUI development

Translation-key maintenance is part of implementing a screen or component, not
a later localization cleanup task. Any developer or Agentic AI agent that adds,
changes, or removes user-visible WebUI text must automatically add, update, or
delete the corresponding catalogue definitions in the same change while the
screen is being actively developed.

For each added key, the implementation change includes:

- the contextual `message_key` and `context_group`;
- required English `default_text`;
- semantic meaning, common locations, translator guidance, grammatical role,
  parameter schema, and rendered example;
- creation/synchronization logic for the database-backed definition; and
- English `source_copy` drafts for supported non-English languages unless a
  protected manual, imported, generated, reviewed, or published value already
  exists.

When English wording, semantics, context, or placeholders change, the same
change updates the definition and marks affected non-English translations as
**Needs review**. Automated synchronization must never overwrite an
administrator-authored, reviewed, imported, or published translation. A
placeholder-contract change must prevent reuse/publication of an incompatible
translation until it has been corrected and reviewed.

When a screen or message is removed, the agent removes the key only after the
checked-in extractor/manifest proves that no application reference remains.
Deletion must follow the catalogue's audited, referentially safe removal path
and preserve immutable event history. If another screen still references the
key, or historical/deployment compatibility requires it, the key remains and
is updated or explicitly deprecated rather than silently deleted.

The agent must run the catalogue completeness and stale-key checks before
declaring the screen complete. A pull request or implementation handoff for UI
work is incomplete if visible strings, error messages, tooltips, accessible
names, empty states, or guidance were added or changed without their catalogue
lifecycle changes. Generated source files or database contents must not be
edited as an undocumented substitute for changing the checked-in authoritative
definition/manifest and its synchronization path.

Completeness checks must detect user-visible text produced indirectly as well
as direct string literals. This includes interpolated/f-string messages,
conditional expressions, selector option mappings, post-construction
component text assignments, intermediate variables flowing into visible
components, chart labels, notifications, tooltips, and accessible names in
component properties. Passing a literal-only extraction check is not evidence
of catalogue completeness.

The same implementation change must also maintain the checked-in generated
Arabic draft catalogue file used by the explicit Phase 6 seed utility. The
implementing Agentic AI agent must:

- generate an idiomatic contextual Arabic draft for every new English key;
- regenerate the checked-in Arabic draft when English wording, semantics,
  guidance, context, or placeholders materially change;
- remove a draft entry when its definition is safely removed, or retain it
  consistently while the definition is explicitly deprecated;
- preserve named placeholders exactly and apply section 21.1 terminology;
- refresh generator/model/prompt provenance, generation time, batch identity,
  and specification, catalogue, and terminology hashes; and
- run Arabic completeness, exact-key, placeholder-parity, blank-value,
  unexplained-English, terminology, and stale-entry checks.

This is an Agentic-AI implementation responsibility, not deferred work for a
human developer or system administrator. The generated Arabic draft catalogue
is source-controlled input to seeding; it is not a published catalogue and must
not be edited directly in the database as a substitute for maintaining its
authoritative English definitions and generation inputs.

The generic seed utility must not be modified for individual message keys. It
reads the complete current generated Arabic draft catalogue and applies it only
to absent or untouched `source_copy` rows. It may run explicitly against a
selected database. The local `run-local-stack.sh` launcher also invokes it with
`--missing-only` against its resolved `DATABASE_URL`, after readiness/preflight
checks and before starting or reusing application services. A failed sync stops
that launch with its error; it never publishes translations. The launcher uses
the existing utility rather than a second catalogue-merging implementation.
It must not run during API startup, schema creation, or a migration. Existing manual, imported, generated, reviewed, or published rows
remain protected. If an English source changes after a generated row has been
seeded, synchronization marks the row **Needs review**; replacing that existing
database draft requires the governed review/reconciliation workflow and must
never occur as a silent seed overwrite.

When the maintained artifact corrects a known defective generated value, it may
declare that exact former value as superseded. The generic seed utility may
replace only an exact match for that declared value; any differing administrator
edit remains protected. A corrected reviewed or published value is returned to
an unreviewed generated draft, its defective publication is withdrawn, and the
administrator can review and publish all such corrections through the existing
bulk workflow. This is the governed reconciliation path and must be audited with
source `seeding`; it is not authority to overwrite arbitrary translations.

### 7.8 Governed translation-artifact export and import

Translation Administration provides compact export and import actions to move
an administrator-reviewed language catalogue between Wathiq databases without
manual database work.

Export defaults to the latest published text for every active contextual key.
An explicit option may substitute a newer reviewed draft. Before download, the
system validates completeness, nonblank values, markup rules, and exact named-
placeholder contracts, and reports how many values differ from the checked-in
artifact. An incomplete or invalid catalogue cannot be downloaded as a valid
artifact. The resulting JSON is compatible with the repository seed pipeline,
records the language tag, English and native language names, text direction,
formatting configuration, and catalogue revision, and retains per-item
provenance.
Manual administrator wording is identified as `manual_admin_export` and must
never be misrepresented as machine-generated. Export creates a download copy;
it never overwrites the checked-in canonical artifact automatically because a
browser download is not authorized to mutate a source checkout.

Import is preview-first and accepts one complete JSON artifact. The artifact,
not a UI selector, declares its language. The preview displays that language,
validates its metadata, every active key, and every placeholder contract, and
shows importable, protected, unchanged, missing, and invalid counts. If the
language does not yet exist, a successful import creates the supported language
from the artifact metadata and the new language card appears immediately.
Applying an import requires the `localization.administer` privilege and one
audit reason.
Imported values are stored as `imported` drafts and are never published
automatically. Existing manual, imported, reviewed, or published values are
protected from overwrite. Any valid, nonblank draft may use the same atomic
bulk review-and-publication workflow, regardless of provenance. Administrators must review
the exported differences before replacing the repository's canonical artifact.

#### 7.8.1 Canonical file and synchronization boundary

For Arabic, the source-controlled canonical artifact is exactly:

`frontend/webui/i18n/messages.ar.generated.json`

The database is the runtime and administrative working copy. The checked-in
artifact is the development, deployment, seeding, and cross-database copy. An
administrator edit exists only in that database until a complete export is
deliberately promoted by replacing the checked-in file and committing it. An
uncommitted browser download is not canonical. A developer or agent cannot
infer or recover database-only administrator edits from the prior checked-in
file and must never claim otherwise.

Promotion of an administrator export is a governed source-maintenance action:

1. export a complete, valid artifact from Translation Administration;
2. replace the corresponding checked-in language artifact with that export;
3. preserve its per-item administrator provenance;
4. run exact-key coverage, nonblank, placeholder-contract, terminology,
   malformed-markup, stale-entry, and artifact-hash validation; and
5. commit the artifact with the catalogue change it represents.

The export/import feature does not silently synchronize a workstation download
with Git. The user or implementing agent must perform this explicit promotion.

#### 7.8.2 Mandatory merge algorithm for later development

Whenever later WebUI work adds, changes, or deletes catalogue definitions, the
developer or Agentic AI agent must load the current checked-in canonical
language artifact before generating anything and merge strictly by
`message_key`:

- preserve every existing administrator-authored, imported, reviewed, or
  published translation and its provenance unchanged;
- add entries for new active keys and generate best-effort text only for those
  missing entries;
- update definition metadata for an existing key when its English source,
  semantic meaning, locations, guidance, context, or placeholder schema changes;
- preserve administrator wording but mark it for review when a changed source
  may affect meaning; a placeholder-incompatible value is invalid until
  corrected and must not be published or seeded as valid;
- regenerate an existing value only when it remains machine-generated and the
  source meaning or contract materially changed, or when the user explicitly
  authorizes replacement;
- remove entries only when the English definition is safely removed, otherwise
  keep definition and artifact deprecation aligned; and
- record exact known replaced machine values in `superseded_translations` when
  the guarded correction mechanism is required.

A whole-file machine regeneration that overwrites curated values is forbidden.
The generic seed script remains key-agnostic; new feature keys and their text
belong in the artifact, never in per-key seed logic.

#### 7.8.3 Required handoff and failure rule

UI work is incomplete until the English manifest and every maintained language
artifact have identical active-key coverage and all required validations pass.
The implementation handoff must state which artifact changed, whether an
administrator export was promoted, which keys were added/changed/removed, and
whether any values require human review.

If the latest administrator-edited export is unavailable, the agent must say
that database-only corrections cannot be preserved in source control and must
request or produce a fresh export before replacing the canonical artifact. It
must not regenerate over the last checked-in file and present that as a safe
merge.

#### 7.8.4 Normative catalogue ordering

`frontend/webui/i18n/messages.en.json` must always be stored in ascending
lexicographic order by the complete contextual `message_key`. This is the sole
canonical ordering for the UI catalogue. Every maintained language artifact,
administrator export, seed input, and generated draft artifact must contain its
items in exactly that same key order.

Every human developer and Agentic AI agent that adds, changes, removes, merges,
generates, promotes, or exports catalogue entries must re-sort the complete
English manifest by `message_key`, then align every maintained language artifact
to it without changing translation wording or provenance. Source-file order,
discovery order, database row order, insertion time, context-group presentation,
and merge history must never determine artifact order. Repository validation
must reject an unsorted English manifest or any maintained language artifact
whose key sequence differs from it.

## 8. Administration-screen design language

The new supported-language, translation-catalogue, translation-review, and
related localization-administration screens must use the established Wathiq
visual language with the following feature-specific rules.

### 8.1 Compact information design

Administration screens use compact, dense, card-based information design by
default. Cards group closely related facts and controls, minimize decorative
empty space, and expose the information needed to understand status and take
the next action without unnecessary navigation. Density must not reduce
legibility, keyboard usability, touch-target safety, or accessible zoom.

A matrix is allowed where it communicates a genuine two-dimensional
relationship more clearly than cards—for example, translation coverage by
context and language. A matrix must remain compact and dense, use Wathiq's
standard light-blue headers, borders, spacing, typography, filtering, sortable
columns where useful, pagination where required, and deliberate loading,
empty, partial, and error states. A raw or default-styled NiceGUI `ui.table` is
not permitted.

### 8.2 Listings

Listings must follow the presentation and interaction pattern of search-result
listings already implemented in Wathiq. Each result is a compact card or row
with a clear information hierarchy, useful status indicators, concise context,
matched/searchable text where relevant, and a consistent action area. Filters,
sorting, paging or progressive loading, selection state, and empty/error states
must behave consistently with comparable search screens.

The translation-catalogue listing is paged by complete `context_group`, not by
an arbitrary number of individual keys. A context group must appear only once
on a main results page and must never be split across adjacent main pages.
Expanding it displays every matching key in that group; an exceptionally large
group may use its own nested key pager or progressive loading. The screen must
report the total matching key count separately from the displayed context-group
range so administrators can understand both scopes.

Before implementation, the team must inspect a comparable live Wathiq search
result listing and reuse its component structure, spacing, typography, colors,
and interaction treatment. Completion requires live-browser visual comparison
in both English LTR and Arabic RTL modes.

### 8.3 Indicators and actions

Status, completeness, review state, publication state, origin, direction, and
similar compact facts should use familiar indicators, badges, and icons rather
than repeated explanatory labels. Row/card actions use recognizable icon-only
controls without visible text labels by default.

Every icon-only action must have:

- a localized tooltip in plain language;
- a localized accessible name (`aria-label` or framework equivalent);
- a visible keyboard focus state and full keyboard activation;
- a sufficiently large interaction target; and
- an icon whose meaning remains correct or is mirrored in RTL as appropriate.

Color or icon shape alone must not carry essential meaning. Unfamiliar,
ambiguous, high-impact, or destructive actions require enough adjacent context
or confirmation to prevent mistakes. The same action must use the same icon and
placement throughout these screens.

### 8.4 Explanatory and guidance text

Screens must provide concise explanatory text when an administrator needs
context to make a safe or correct choice. Guidance uses simple, accessible
language, explains the consequence or next step, and avoids unexplained
technical terminology. It should appear near the relevant control, empty
state, warning, conflict, generated/source-copy translation, or publication
decision rather than in a distant help page.

Guidance must remain visually subordinate to the primary task and should be
progressively disclosed when it is lengthy. It must be translated, readable by
assistive technology, and available in RTL without layout loss. Tooltips are
appropriate for short action explanations but must not be the sole location of
critical instructions, validation errors, or consequences.

## 9. Complete RTL and bidirectional behavior

When the effective language has direction `rtl`, the root HTML element must set
both `lang="ar"` and `dir="rtl"`. Direction must be applied before first
meaningful paint to avoid a visible left-to-right layout flash.

RTL is a complete layout mode, not right-aligned text. It includes:

- primary navigation and drawers anchored on the right;
- navigation order, breadcrumbs, tabs, steppers, toolbars, and action groups
  flowing from the right;
- lists, table columns, pagination, filters, cards, forms, dropdown menus,
  selector values, dialogs, toasts, and contextual menus beginning from the
  right;
- directional icons, chevrons, next/previous controls, indentation, margins,
  padding, borders, and transitions mirrored where their meaning is spatial;
- text, placeholders, selected values, and dropdown options aligned according
  to the active direction; and
- keyboard traversal and focus order matching visual order.

CSS must use logical properties (`inline-start`, `inline-end`, logical margin,
padding, border, and inset) rather than hard-coded left/right wherever the
property is directional. Components that portal content outside their parent
must receive language and direction explicitly.

Codes, numbers, email addresses, URLs, hashes, file paths, record identifiers,
and other intrinsically LTR tokens must render in isolated bidirectional spans
with `dir="ltr"` or equivalent Unicode isolation. User-supplied text must not
be allowed to alter surrounding direction or inject markup. Mixed Arabic/LTR
content must remain legible and copy correctly.

Arabic fonts must cover required glyphs and preserve Wathiq's typography and
accessible contrast. RTL acceptance requires live-browser comparison at
desktop and supported mobile widths; screenshots alone do not replace keyboard
and assistive-technology checks.

## 10. Date, time, and timezone contract

### 10.1 Semantic types

The implementation must distinguish:

- **Instant:** a globally unique moment, stored and transferred with timezone
  semantics, for example event time or `date_created`.
- **Local date:** a calendar date without time or timezone, for example a date
  whose business meaning is the whole named day.
- **Local date-time input:** wall-clock values entered by a user and interpreted
  in the user's working timezone before becoming an instant.
- **Duration:** elapsed time, never formatted or converted as a wall-clock
  timestamp.

An API field's schema and documentation must identify which semantic type it
uses. A date must never be parsed as midnight UTC merely to reuse datetime
code.

### 10.2 Database tier

- Instants use PostgreSQL `timestamptz` and are compared as instants.
- Database connections run with session timezone `UTC`.
- `CURRENT_TIMESTAMP` is acceptable because `timestamptz` preserves the
  instant; serialization is normalized to UTC.
- Calendar-only values use PostgreSQL `date`.
- Wall-clock recurring values, if introduced by a separately approved feature,
  require an explicit local time plus IANA timezone and must not be stored as
  an unqualified timestamp alone.
- Existing `timestamptz` rows are not rewritten by this feature.

### 10.3 API tier

- Instants are accepted and returned as RFC 3339 strings with an explicit
  offset; canonical responses use UTC with `Z`.
- The API rejects offset-free datetime strings for instant fields.
- Date fields use `YYYY-MM-DD` and undergo no timezone conversion.
- For wall-clock form input, the frontend converts to an offset-bearing instant
  before submission. Where server interpretation is unavoidable, the request
  carries both the local value and IANA timezone, and the server returns the
  resolved instant.
- Ambiguous daylight-saving times require an explicit earlier/later choice;
  nonexistent local times are rejected with a localized corrective message.
- Business rules, authorization, retention calculations, expiry, ordering, and
  audit logic compare instants in UTC and never depend on the API host's local
  timezone.

The effective language/timezone may be returned as response metadata or from a
bootstrap endpoint, but API resource fields remain stable and language-neutral
unless the endpoint explicitly provides localized projections.

### 10.4 Frontend Python/UI tier

- Frontend code parses API instants as timezone-aware values.
- It converts an instant to the user's IANA timezone only for presentation or
  to initialize a local date-time control.
- A `datetime-local` value is never interpreted using the browser, frontend
  server, or container's implicit timezone. It is paired with the user's saved
  IANA timezone and converted deliberately.
- Form submission sends the resolved offset-bearing instant. Validation near
  DST transitions occurs before the request is committed.
- Locale-aware formatters render dates, times, numbers, and relative values;
  scattered `strftime` patterns and process-local `astimezone()` calls are not
  permitted for user-facing values.

### 10.5 Browser tier

- Bootstrap data contains effective language, direction, working timezone,
  catalogue revision, and formatting metadata before normal page rendering.
- Browser components use explicit locale and `timeZone` options; they must not
  silently use the device timezone for Wathiq business values.
- The device timezone may be offered as a convenience when choosing a
  preference, but it does not override a saved working timezone.
- Changing language/timezone refreshes current formatting and component
  direction while preserving safe unsaved form state. A component that cannot
  switch safely must prompt before controlled reload.

### 10.6 Examples

An instant stored as `2026-09-26T08:00:00Z` displays as 12:00 in
`Asia/Dubai`. If another user views the same row in `Europe/London`, that user
sees the London local time for the same instant. Changing either user's working
timezone changes only display and future wall-clock interpretation.

A stored date `2026-09-26` remains 26 September for every timezone. It is
localized in wording/order but never shifted to the previous or next day.

## 11. Multilingual domain entity values

### 11.1 Covered entities and fields

The initial multilingual entities are:

| Entity | Canonical fields | Translatable fields |
| --- | --- | --- |
| Classification scheme | `title`, `description` | `title`, `description` |
| Classification | `title`, `description` | `title`, `description` |
| User | `name`, new nullable `description` | `name`, `description` |
| Role | `name`, `description` | `name`, `description` |
| Organizational unit | `name`, `description` | `name`, `description` |
| Security level | `name`, new nullable `description` | `name`, `description` |
| Authorization profile | `name`, `description` | `name`, `description` |

Codes and identifiers remain untranslated and are shown with the effective
name where disambiguation is useful.

Aggregations and Records are explicitly not multilingual entities under this
subsystem. Their titles and descriptions are user-authored business and
records-management metadata that may be English, Arabic, another language, or
mixed-language text. The value entered and governed on the entity is the
authoritative value and is displayed verbatim to every user, independent of UI
language.

This exclusion is deliberate because presenting a translated aggregation or
record title as though it were interchangeable with the authoritative value
could alter or obscure scope, provenance, filing context, or legal/evidentiary
meaning. It could also cause two users to see different apparent official
titles in selectors, exports, audit review, references, and operational
communication. Descriptions carry even greater risk because they may contain
nuanced contextual or governance information. Avoiding automatic display
substitution also reduces schema, indexing, fallback, audit, export, and
regression complexity without preventing users from entering Arabic or mixed
text directly.

Wathiq still translates all UI labels surrounding Aggregation and Record
metadata, and search continues to support English, Arabic, and mixed-language
values as entered. Selectors, breadcrumbs, cards, tables, favourites, search
results, history references, and exports show the authoritative stored title
and description rather than a language-dependent substitute.

If a later approved business requirement needs bilingual or alternate titles,
it must be specified as a separate governed metadata feature—not added back as
generic localization. Such a feature should distinguish an official supplied
title from an administrative translation or alternate title and record its
language, type, source/translator, actor, time, authorization, and audit
history. It must label the alternate value explicitly and must not silently
replace the authoritative title.

### 11.2 Minimal-change storage design

Each covered table receives one nullable `translations jsonb` column with this
shape:

```json
{
  "ar": {
    "title": "عنوان عربي",
    "description": "وصف عربي"
  }
}
```

Entities using `name` store `name` rather than `title`. A locale object may
contain only fields valid for that entity. Language keys are normalized BCP 47
tags. Values must be strings, trimmed, bounded to the corresponding canonical
field limits, and nonblank when present. Empty locale objects are removed.

The existing columns and their established constraints remain intact. They
continue to carry the required English/default value, preserving joins,
triggers, event snapshots, imports, integrations, existing queries, and API
consumers. The JSONB column adds translations without normalizing every entity
through new join tables or adding one column per language. The only additional
canonical fields are nullable `description` on `users` and `security_levels`,
required to meet the approved description-translation scope.

JSON shape and enabled-language validation must occur in shared API validation
and PostgreSQL constraints/triggers so direct SQL cannot persist malformed
structures. The database must not require every enabled language to be present.

#### 11.2.1 Rationale for retaining translations on the owning row

This storage choice is deliberate, including for protected built-in entities.
A shared polymorphic translation table shaped around `entity_type` and
`entity_id` would isolate translation writes, but PostgreSQL cannot enforce one
ordinary foreign key whose target table changes according to `entity_type`.
Referential integrity would therefore require custom triggers, or one separate
translation table and repeated API/query plumbing for every covered entity.
Seven entity-specific translation tables would restore real foreign keys but
would substantially expand schema, migration, join, fallback, search, audit,
versioning, and regression surface for two small translated fields per entity.

Keeping a bounded `translations jsonb` map on each owning row best satisfies
the approved minimal-change requirement. It preserves existing entity identity,
foreign keys, authorization paths, optimistic concurrency, event history, and
read APIs while avoiding language-specific columns and cross-entity
polymorphism. The design remains appropriate while translations are limited to
the approved name/title and description fields and supported-language counts
remain administratively bounded. A separate normalized design may be
reconsidered only through an approved specification change if translation
volume, independently managed translation lifecycles, or query requirements
materially outgrow these assumptions.

Protected built-ins do not weaken this rationale. Their database guards must
permit an update only when every canonical, authorization, lifecycle,
ownership, and stable-identity field remains unchanged and the only business
payload change is `translations`; automatic version fields may advance through
the normal concurrency mechanism. Ordinary entity APIs must continue to reject
canonical changes. Locale-scoped translation APIs remain separately
authorized, validated, versioned, and audited. This narrow exception provides
localized names and descriptions without making platform-owned configuration
mutable.

### 11.3 Concurrency and auditing

Translation changes are part of the owning entity and use its existing
optimistic-concurrency `version`, `If-Match`, authorization, transaction, and
event-history path. The API accepts a locale-scoped patch and performs a
server-side JSON merge; clients must not replace the complete `translations`
object when editing one language.

Concurrent changes to different entities proceed independently. Concurrent
changes to the same entity are protected by its version: a stale request gets
the established conflict response and cannot overwrite a winning edit. The UI
preserves unsaved translations and supports review/reapply after reload.

Event history contains the changed translation paths and before/after values.
Existing canonical event snapshots remain readable. Translation editing obeys
the same change-reason requirements as editing the corresponding entity.

### 11.4 Editing experience

The ordinary form shows only the current canonical/effective primary fields.
An unobtrusive **Translations** disclosure or secondary dialog exposes enabled
languages. It must not make routine creation or editing feel multilingual or
require duplicate entry.

The advanced editor shows language, completion status, title/name, description,
and the canonical English value for context. Users who already have permission
to modify that entity's metadata may add, update, or remove its translations;
this feature does not grant broader entity access. They do not need
`localization.administer` or System Administrator status.

The required right is listed below. User translations use the same right as
ordinary user administration; other entity types retain their metadata right:

| Entity | Required metadata right |
| --- | --- |
| Classification scheme | `classification_scheme.modify_metadata` |
| Classification | `classification.modify_metadata` |
| User | `identity.users.administer` |
| Role | `role.modify_metadata` |
| Organizational unit | `org_unit.modify_metadata` |
| Security level | `security_level.modify_metadata` |
| Authorization profile | `profile.modify_metadata` |

`profile.modify_metadata` is granted by default to the protected `ALL_PRIVS`
and `SYS_ADMIN` profiles. This lets a System Administrator maintain localized
Profile names and descriptions without first modifying their own authorization
profile. The right remains independently assignable to other profiles.

`identity.users.administer` authorizes both reading and changing users' localized
names/descriptions, including from the ordinary Edit User form. No separate
user-translation privilege or `localization.administer` grant is required.
The former `user.modify_metadata` privilege is retired; remove its profile
memberships and dependency links without granting user administration to its
former holders. Preserve historical audit events and deprecate its message keys.

The authorization check uses the same scope, resource access, state, and other
integrity gates as an ordinary metadata edit for that entity. Translating
metadata cannot be used to edit canonical fields or other protected attributes
that the actor could not otherwise modify.

Protected built-in entities remain an explicit translation-only exception to
canonical immutability. When a covered built-in entity, such as the Text
Indexing Service role, cannot be changed through its ordinary metadata API,
the WebUI still exposes the standard metadata editor with every canonical
control disabled and the **Translations** disclosure enabled. Saving that form
must call only the locale-scoped entity-translation endpoint. The ordinary
entity update endpoint continues to reject every canonical-field mutation,
including requests that attempt to combine canonical and translated changes.
The corresponding right in the table above is still required.

If an existing implementation currently represents one of these administrative
metadata operations under a broader legacy administration privilege, the
internationalization implementation must add or map the listed right (except
users, which deliberately reuse `identity.users.administer`) through the normal privilege migration and
dependency process. It must not require `localization.administer` as a shortcut.
Read-only users may see effective values but cannot edit translations.

Creating an entity still requires its existing canonical English/default
name/title. Other translations are optional and may be supplied atomically in
the create request. Translation validation errors identify the language and
field without discarding other entered form values.

### 11.5 Reads, selectors, lists, and references

API resource responses retain canonical fields for compatibility and add
localized projections or an explicitly requested `translations` block where
authorized. A recommended response shape is:

```json
{
  "title": "Financial administration",
  "localized": {
    "language": "ar",
    "title": "الإدارة المالية",
    "description": "...",
    "used_fallback": false
  }
}
```

For the seven covered entities, selectors, breadcrumbs, cards, tree nodes,
tables, search results, reference summaries, and relationship labels display
the effective value in the signed-in user's preferred language. They include
the stable code or identifier where needed to distinguish duplicate translated
names. Aggregation and Record references instead display their authoritative
stored title/description verbatim as required by section 11.1.

List endpoints must resolve effective values in the query or bounded response
mapping and must not execute one query per row. Sorting by displayed name/title
uses the effective value and an approved locale collation, followed by stable
code and ID tie-breakers. Pagination must use the same ordering expression as
display. Absence of a deployment-approved collation must fall back to a
documented deterministic Unicode ordering, not host-dependent behavior.

References captured in immutable history remain snapshots of what was recorded
at the event time. Later translation edits must not rewrite history. History UI
may show a current localized live-entity label separately, clearly identified
as current rather than historical.

#### 11.5.1 Database default and language-specific ordering

For Arabic-primary deployments supporting English, the recommended default
database collation is **ICU `ar` with UTF-8 encoding**. It applies Arabic
tailoring while retaining English and other Unicode text support. ICU `und`
is a deliberate language-neutral alternative; libc relies on host-OS locale
rules and is not the preferred default for a new Arabic-primary deployment.
ICU results also depend on its library/data version, which deployment evidence
must record. Creation, controlled conversion and upgrade procedures are defined
in [application configuration section 4.1.1](application-configuration.md#411-database-encoding-and-collation-provisioning).

This default does not change the English system/UI default, per-user language
resolution, stored text, RTL rendering, or the preceding localized-ordering
contract. Explicit column/query collations take precedence; English-facing
lists can use an approved English collation with the same stable pagination
tie-breakers. Existing numeric code collations and portable export ordering
remain separate contracts.

Sorting related forms close together does not make them equal. The database
default remains deterministic; `علم` and `عِلْم`, or `Apple` and `apple`, remain
distinct values. Nondeterministic equality, search normalization and numeric
ordering are not enabled by this recommendation. ICU `ar` alone still orders
`File 1`, `File 10`, `File 2`; natural numeric order requires explicit options.

The [database collation guide](../docs/database-collation.md#measured-examples)
records measured libc versus ICU `ar` examples for names, vowel marks and digit
scripts, along with read-only reproduction queries and their platform/version
scope. These examples illustrate the recommendation rather than freezing every
library version's full sort order.

## 12. Search and discovery

Metadata search for the seven covered multilingual entities must consider the
canonical value and translations for enabled languages without weakening
existing authorization filters. A user may find one of those entities using
either English or Arabic text regardless of current UI language; results
display using the user's effective language.

Aggregation and Record search indexes only their authoritative title and
description as entered; this subsystem does not create or index translated
variants for them. Their existing English, Arabic, and mixed-language analyzer
behavior follows the approved full-text search language policy. Reindex
configuration identifies language-analysis changes where required, but no
entity-translation version applies to Aggregation or Record metadata.

Administrative entity search may begin with bounded JSONB extraction where
volumes permit. Production query plans and indexes must be verified; a generic
unbounded JSONB scan is not an acceptable large-dataset design.

## 13. API contract

The subsystem provides authenticated endpoints equivalent to:

```text
GET  /api/v1/preferences
PUT  /api/v1/preferences
GET  /api/v1/i18n/bootstrap
GET  /api/v1/i18n/catalogues/{language_tag}

GET  /api/v1/admin/i18n/languages
POST /api/v1/admin/i18n/languages
PUT  /api/v1/admin/i18n/languages/{language_tag}
GET  /api/v1/admin/i18n/messages?language_tag={tag}&key={text}&source_text={text}&translated_text={text}&semantic_meaning={text}&status={status}&origin={origin}&limit={n}&offset={n}
PUT  /api/v1/admin/i18n/messages/{message_key}/translations/{language_tag}
POST /api/v1/admin/i18n/messages/{message_key}/translations/{language_tag}/publish
```

The message-list endpoint validates controlled `status` and `origin` values,
applies all supplied filters with logical AND, returns the filtered total with
the bounded page, and uses a deterministic `message_key` tie-breaker. Additional
context, review, and needs-attention filters follow the same contract. Empty
text values are treated as omitted rather than as a request to match blank
translations.

Exact route integration may follow the existing API module layout, but these
capabilities and semantics are required. Administrative mutations require
`localization.administer`, `If-Match`, and a nonblank `X-Change-Reason` where
established governance conventions require one. Locale-scoped translation
patches on the seven covered entities do not use `localization.administer`; they require
the entity-specific authorization from section 11.4.

The bootstrap response contains effective language, direction, working
timezone, default/fallback language, enabled-language summaries, catalogue
revision, and catalogue URL or embedded initial messages. It must not disclose
draft translations or unauthorized administrative metadata.

Localized API behavior must vary caches on authenticated user context or an
explicit normalized locale key. Shared caches must never return one user's
preferences or unreleased draft translations to another user.

## 14. Caching and invalidation

### 14.1 UI catalogue

Published catalogue data is compiled per language into one versioned resource,
not fetched key by key. The resource has a content hash/revision, `ETag`, and
supports conditional requests. Immutable revisioned URLs may be cached for a
long duration; the small bootstrap document is short-lived or revalidated.

Cache layers are:

1. API-process memory keyed by `(language_tag, catalogue_revision)`;
2. optional shared cache with the same key;
3. browser memory plus persistent HTTP cache; and
4. a per-session resolved-message map in frontend code.

Publishing a translation increments the affected language catalogue revision
in the same transaction. After commit, an invalidation notification evicts that
language from API/shared caches. Polling the revision is an acceptable safety
net; time-to-live alone is not the primary invalidation mechanism. Invalidation
failure must be logged and recover through revision mismatch/revalidation.

Draft changes do not invalidate ordinary-user caches. Administrators preview
drafts through an authenticated, non-cacheable preview path.

### 14.2 Entity translations and preferences

Translations for the seven covered entities travel with normal bounded
entity/list responses; the frontend must not make an additional API request per
entity or per selector option. Their cache keys include entity version and
requested effective language. Mutating one of those entities invalidates its
ordinary and localized representations after transaction commit. Aggregation
and Record cache representations are not varied by UI language merely for
title or description because those fields remain verbatim.

Preferences are loaded once during authenticated bootstrap and may be cached
for the session. A successful preference update replaces that session value
and invalidates any server-side per-user entry. Preference responses are
private and must not enter a shared public cache.

## 15. Security, validation, and privacy

- All translation output is escaped by default. Rich UI messages are exceptional,
  explicitly flagged, sanitized against a strict allowlist, and covered by
  tests.
- Interpolation values are escaped independently and cannot introduce message
  syntax or markup.
- Translation-catalogue and supported-language administration requires
  `localization.administer`; entity translation editing requires only the
  corresponding entity-specific authorization. Both are protected
  from cross-site request forgery under the established session model.
- Locale, direction, timezone, catalogue key, sort/collation, and field name
  are selected from server allowlists; none may become raw SQL or template
  input.
- Error responses retain stable machine-readable codes. Localized text is a
  presentation concern and must not be used for program logic.
- User language and timezone are account preferences and are visible only where
  required for the user, authorized administration, auditing, or support.
- Unicode input is normalized consistently, while original meaningful script
  and diacritics are preserved. Confusable identifiers are mitigated by always
  retaining stable codes/IDs and existing uniqueness rules.

## 16. Accessibility and usability

Language changes must update the document language so screen readers use the
correct pronunciation. Direction, accessible names, error associations, live
regions, focus management, and keyboard order must remain correct in both LTR
and RTL modes.

Translated text may expand substantially. Layouts must tolerate at least 200%
text zoom and long labels without clipping controls or obscuring actions.
Icon-only controls require localized accessible names and visible tooltips.
Color or direction alone must not convey meaning.

Arabic and English number/date presentation must be consistent with approved
locale rules. Stable identifiers remain copyable in their canonical form.

## 17. Migration and compatibility

Implementation requires one transactional migration for existing databases and
matching DDL in `database/schema.sql`. The canonical schema remains standalone
and must not invoke the migration.

Migration steps are:

1. create language, message-definition, message-translation, and preference
   tables and their constraints/indexes;
2. seed `localization.administer` into the System Administrator and protected
   all-privileges profiles, and add or map the seven
   entity-specific rights from section 11.4 through the established privilege and
   dependency catalogues;
3. seed enabled English and Arabic language metadata with English as default;
4. import the application-owned English message definitions, contextual
   grouping, translator guidance, common locations, parameter schemas, and
   examples idempotently;
5. add nullable `translations jsonb` to the seven covered entity tables;
6. add nullable `description` to `users` and `security_levels`;
7. add validation, versioning, history, and applicable covered-entity search
   integration without changing existing canonical values or adding translated
   Aggregation/Record search fields; and
8. verify existing rows resolve identically in English before enabling the new
   UI.

The migration itself does not synthesize translations. Best-effort Arabic
draft generation occurs only in the final implementation phase described in
section 21, after extraction and catalogue infrastructure are complete.
Existing API clients continue receiving the current canonical fields. New
localized fields are additive until a separately approved API version changes
that contract.

Rollback must not discard administrator-authored translations. A code rollback
may stop consuming new fields, but destructive schema rollback requires an
explicit export and operational approval.

## 18. Observability and operations

Metrics and structured logs include catalogue compile time, cache hit/miss,
invalidation lag/failure, missing-key count, fallback count by language,
invalid translation syntax, preference validation failures, and timezone/DST
resolution failures. They must not include session secrets or unnecessary
user-authored descriptions.

Missing UI keys produce a conspicuous safe English fallback in non-production
testing and a bounded warning in production. Repeated missing keys are
aggregated to prevent log flooding. Health/readiness checks verify that the
default catalogue compiles and `DEFAULT_WORKING_TIMEZONE` names a valid IANA
timezone.

The application and workers use the same pinned tzdata release. Updating
tzdata is an operational release because governments can change future offset
rules. Historical instants remain unchanged; future local schedules, if any,
must be re-evaluated under their owning feature's rules.

## 19. Verification and acceptance criteria

### 19.1 Automated tests

Tests must cover:

- default resolution with and without a preference row, including
  `DEFAULT_WORKING_TIMEZONE=Asia/Dubai` from test environment configuration and
  startup/readiness rejection when that variable is absent, blank, or invalid;
- preference authorization, validation, version conflict, deletion cascade,
  immediate session refresh, disabled-language fallback, and IANA timezone
  validation;
- catalogue key completeness, contextual uniqueness, required guidance and
  location metadata, placeholder parity/template compilation, plural-variant
  selection, HTML safety, draft isolation, blank/whitespace rejection at WebUI,
  API, database, compilation, and publication boundaries, source-copy creation,
  origin-independent review and publication, ETag
  behavior, and invalidation;
- invalid/missing field highlighting, exact accessible reason text,
  needs-attention filtering/sorting, collapsed-group indicators, and restrained
  English/Arabic visual treatment;
- independent key, translated-text, semantic-meaning, status, and origin
  filters, including logical-AND combination, debounce, pagination reset,
  filtered totals, clear-all, state preservation, and bounded server-query
  behavior;
- add/update/delete development reconciliation, stale-reference protection,
  source-change review marking, placeholder-contract invalidation, protection
  of administrator translations, and Agentic AI definition-of-done behavior;
- new-language creation with one source-copy row per definition, exact
  preservation of named placeholders and escaped braces, subsequent-definition
  backfill, and protection of manual/reviewed/published translations from
  seeding;
- translated presentation for every user-space error category, including the
  safe localized generic message for unknown error codes;
- concurrent administrators editing different keys and same-key conflict
  preservation;
- authorization tests proving `localization.administer` is required for every
  catalogue/language mutation and that each entity translation accepts its
  matching authorized actor from section 11.4 while denying read-only actors;
- negative tests proving a catalogue administrator cannot edit an entity
  translation without its metadata right and an entity metadata editor cannot
  administer the general catalogue;
- JSONB shape validation, locale-scoped merging, fallback, event history, and
  stale entity updates for all seven covered entity types;
- Aggregation and Record tests proving no `translations` column or localized
  projection is introduced, titles/descriptions render verbatim for users with
  different UI languages, and English/Arabic/mixed metadata remains searchable;
- selector, breadcrumb, table/list, tree, and reference labels for the six
  covered entities in preferred language without N+1 queries, plus verbatim
  Aggregation/Record labels in those same presentation surfaces and favourites;
- localized sorting with deterministic pagination;
- explicit database provider/locale/version verification for new deployments
  and deliberate rebuilds, default ICU `ar` versus explicit Arabic-collation
  sample ordering, English sorting, retained equality distinctions, and
  separate numeric-order behavior; mutable regressions run in disposable
  databases while retained targets receive read-only verification;
- English, Arabic, mixed-language, missing-translation, and translated-metadata
  search cases under authorization filters;
- instant round trips, date non-shifting, non-whole-hour zones, positive and
  negative UTC offsets, DST gaps/overlaps, leap day, and change-of-timezone
  behavior at database, API, frontend, and browser boundaries;
- RTL component direction, portal/dropdown direction, mirrored navigation,
  keyboard order, focus, bidirectional isolation, and responsive layouts;
- administration-screen density, search-result listing consistency, compact
  matrix styling, icon-only action tooltips/accessibility, and contextual
  guidance in English and Arabic;
- Translation Inspector authorization, default-off/session-only state,
  hover/focus highlighting, pinning, fixed-panel behavior, portal/dynamic-
  content coverage, ordinary-tooltip preservation, and absence for unauthorized
  users; and
- accessibility names, document language changes, zoom, and screen-reader
  smoke tests.

Any database-backed test must use a new uniquely named disposable PostgreSQL
database initialized from the canonical schema or required migration path and
must drop it after the run, whether the run passes or fails.

### 19.2 Catalogue completeness gate

A build-time extractor or explicit checked-in key manifest compares application
message usage with definitions. CI fails for:

- a referenced key with no English definition;
- an unknown interpolation parameter;
- an invalid message pattern;
- a definition without context grouping, semantic meaning, common locations,
  translator guidance, parameter types, or a rendered example;
- hard-coded user-visible application text outside an approved exception list;
  or
- removal of a still-referenced key.

Arabic rollout requires administrator-reviewed and published translations for
all release-blocking UI keys, including all user-space errors. Explicitly
approved lower-priority omissions may fall back to English and must appear in
an administrator coverage report; silent omissions are not acceptable.

### 19.3 Release acceptance

The feature is accepted only when:

1. with `DEFAULT_WORKING_TIMEZONE=Asia/Dubai`, a new user sees English and the
   Asia/Dubai working timezone; changing the environment value changes the
   default without a code or schema change;
2. a user can select Arabic and a working timezone and immediately receives a
   fully RTL, Arabic UI with correct date/time presentation;
3. all covered UI messages use the catalogue or an approved exception;
4. contextual groups and per-key guidance make identical English wording in
   different semantic contexts distinguishable to translators;
5. every newly supported language receives a complete English source-copy
   draft set when machine seeding is not selected; those drafts are not
   published automatically, but an administrator may deliberately review and
   publish them;
6. every user-space error has a translated presentation and unknown errors use
   a translated safe generic message;
7. blank or whitespace-only translation input produces accessible inline and
   summary guidance, cannot be persisted or published, and cannot replace or
   invalidate the currently published catalogue;
8. every missing or invalid translation is clearly but unobtrusively marked,
   exposes its exact accessible reason, remains discoverable through
   needs-attention filters and collapsed-group counts, and is not communicated
   by color alone;
9. an administrator can independently filter by message key, English source text, translated text,
   semantic meaning, status, and origin; combined filters, pagination, result
   totals, clear-all, and return-from-edit behavior remain correct;
10. two administrators can safely maintain translations concurrently without
   catalogue-wide locks or lost updates;
11. every covered entity supports optional locale values while its existing
   English behavior and integrations remain intact;
12. selectors and reference presentations use the current user's effective
   language and deterministic fallback for the seven covered entities, while
   Aggregation and Record titles/descriptions remain authoritative and verbatim
   for every UI language;
13. one stored instant displays correctly for users in different timezones and
   one stored date never changes day;
14. translation resources do not cause per-key or per-row database/API
   round-trips;
15. English LTR and Arabic RTL pass live-browser visual, keyboard, responsive,
   and accessibility verification;
16. new administration screens pass live-browser comparison against Wathiq's
    existing search-result listings and meet the compact-card, dense-matrix,
    icon-action, tooltip, and plain-language guidance rules in section 8;
17. best-effort generated Arabic drafts are visibly identified, reviewed by
    administrators, corrected where necessary, and never auto-published;
18. every new or changed WebUI screen includes its translation-definition
    additions, updates, and safe removals in the same implementation change,
    together with corresponding generated Arabic-draft additions, updates, or
    removals, current provenance/hashes, protected translations preserved, and
    catalogue checks passing;
19. an authorized administrator can enable the Translation Inspector for the
    current session, inspect and pin keys by hover, keyboard focus, or click,
    copy a key, and open the filtered translation-administration entry without
    changing ordinary tooltips or page layout, while unauthorized users cannot
    see or activate the mode; and
20. migration, rollback-safety, performance, security, concurrency, and audit
    evidence is recorded.

## 20. Requirement traceability

| Requirement | Design sections | Required evidence |
| --- | --- | --- |
| English, Arabic, extensible languages | 4, 7, 17 | registry/catalogue tests and additional-language fixture |
| English source-copy drafts for new languages | 4.3, 7.3–7.4, 19 | completeness, placeholder-preservation, coverage, and publication-gate tests |
| English default | 4–6 | preference/default integration tests |
| User language and working timezone | 6, 10, 13 | API, frontend, browser, and persistence tests |
| Correct dates/datetimes at every tier | 10 | DB/API/UI/browser boundary and DST suite |
| Contextual keys and translator guidance | 7.1, 7.3–7.4 | metadata completeness and grouped-admin-UI tests |
| Simple interpolated messages | 7.2 | parser, type formatting, escaping, and placeholder-parity tests |
| Blank translations cannot be used | 5, 7.3–7.4, 19 | WebUI/API/database rejection, atomic publication, cache, and accessibility tests |
| Invalid translations are visibly identifiable | 7.4, 8, 19 | status-reason, filtering, collapsed-group, visual-regression, RTL, and accessibility tests |
| Translation catalogue filters | 7.4, 13, 19 | key/English source/translated text/meaning/status/origin, combination, paging, state-restoration, and bounded-query tests |
| Translation keys and Arabic drafts follow screen development | 7.5, 19, 21 | definition and generated-draft add/update/delete reconciliation, provenance/hash, stale-key, placeholder, Arabic-quality, protected-translation, source-change, explicit-seed, and CI tests |
| Complete UI and user-error translation | 7, 19.2 | key manifest, error-code mapping, CI completeness, browser coverage |
| Administration-screen design language | 8, 9, 16, 19 | live-browser comparison, density, icon accessibility, guidance, and RTL evidence |
| General translation administration | 7.4, 13, 15 | `localization.administer` allow/deny matrix |
| Entity translation authorization | 11.4, 13, 15 | seven-entity authorization allow/deny matrix |
| Concurrent administrative translation | 7.4, 13 | different-key concurrency and same-key conflict tests |
| Full Arabic RTL | 9, 16, 19 | desktop/mobile browser, keyboard, accessibility evidence |
| Multilingual entity data | 11, 17 | schema/API/UI tests for all seven covered entities |
| Aggregation and Record metadata remains authoritative | 11.1, 11.5, 12, 19 | schema-exclusion, verbatim-display, audit/export, and multilingual-search tests |
| Low-regression schema strategy | 11.2, 17 | English compatibility and migration comparison tests |
| Advanced but unobtrusive entity editing | 11.4 | usability and browser workflow evidence |
| Localized selectors | 11.5 | selector/query-count/fallback tests |
| Arabic-primary database collation recommendation | 11.5.1; Application Configuration 4.1.1 | recorded provider/locale/version, read-only Arabic/English examples, backup-snapshot parity and disposable ICU `ar` regression evidence |
| Translation caching | 14 | ETag, hit/miss, invalidation, and stale-cache recovery tests |
| Best-effort Arabic bootstrap with human review | 7.4, 19, 21 | generation report, origin/review state, and publication-gate tests |
| Approved, idiomatic, accessible Arabic | 21.1 | glossary-conformance, singular/plural context, idiomatic-quality sampling, accessibility review, and administrator-review report tests |
| Privileged Translation Inspector | 21 phase 7 | privilege, default-off, session-state, hover/focus/click, pin/copy/open, dynamic-content, fixed-panel, RTL, tooltip-preservation, and noninterference tests |
| Additional security/quality concerns | 12, 15–19 | search, security, accessibility, operations, and performance evidence |

## 21. Implementation phases

1. **Foundation:** language registry, preference storage/API, shared locale and
   timezone services, validated `DEFAULT_WORKING_TIMEZONE` configuration and
   environment examples, bootstrap contract, authorization catalogue
   additions, and contextual English key extraction.
2. **Catalogue and error conversion:** database-backed messages, required
   translator guidance, simple template renderer, all user-space error-code
   mappings, administrator grouping/editor, publication, concurrency, audit,
   compiled-resource cache, and complete English catalogue.
3. **RTL infrastructure:** root direction, component remediation, Arabic fonts,
   bidirectional isolation, and browser/accessibility verification using
   controlled test translations.
4. **Entity translations:** JSONB columns and validation, locale-scoped API
   patches, advanced form disclosure, localized selectors/lists/references.
5. **Search and hardening:** translated search documents, collation and query
   plans, cache/load tests, DST suite, telemetry, and release evidence.
6. **Best-effort Arabic bootstrap and review:** generate an Arabic draft for
   every extracted existing English UI message, including user-space errors;
   store each result with `origin = generated` and `status = draft`; produce a
   coverage and generation-failure report; and present the drafts, grouped by
   context with their guidance, for system administrators to review, correct,
   explicitly approve, and publish. Generation must never overwrite a manual
   or previously reviewed translation, and no generated value is published
   automatically. The approved generator receives only application-owned
   source text, contextual guidance, and placeholder metadata—never user data,
   credentials, audit content, or records—and its model/version and generation
   time are retained for provenance.
7. **Privileged Translation Inspector:** after all preceding infrastructure and
   bootstrap work is complete, add a hidden diagnostics mode for users whose
   effective privileges include `localization.administer`.
   (`location.administer` is not introduced; the established localization
   privilege is authoritative.)

   The signed-in user menu contains an administrator-only **Diagnostics**
   section with a compact **Translation Inspector** switch. The section and
   switch are absent for other users. The inspector is off by default; its state
   belongs to the current authenticated browser session, is cleared at sign-out
   or session expiry, and is not stored as an ordinary user preference. An
   optional keyboard shortcut may supplement the switch but must not be the only
   discoverable or accessible activation method.

   Enabling the inspector shows one compact fixed overlay panel that does not
   resize or shift the application layout. Hovering over catalogue-backed text,
   or moving keyboard focus to the translated element or its owning interactive
   control, gives that element a subtle diagnostic outline and updates the panel
   with the most specific applicable `message_key`. Moving away updates or
   clears the unpinned inspection. Clicking the highlighted element pins the
   selection so it remains available for inspection. While inspector mode is
   enabled, that diagnostic click is consumed and must not invoke the element's
   ordinary action; the panel clearly explains this mode. `Escape` clears the
   pinned selection, and disabling the inspector restores ordinary click
   behavior immediately.

   The panel shows, at minimum, the translation key, effective language,
   rendered translation, and whether fallback was used. The key uses a compact
   monospaced treatment. The panel provides icon actions with localized
   accessible names and tooltips for **Copy key** and **Open in Translation
   Administration**. Opening administration preserves the current application
   navigation history and applies the exact key filter defined in section 7.4.
   It remains subject to `localization.administer` authorization.

   The central translation renderer attaches diagnostic metadata, such as a
   controlled `data-i18n-key` attribute, while the inspector uses one document-
   level delegated hover/focus/click mechanism. Individual screens must not add
   their own inspector handlers. Coverage includes labels, headings, buttons,
   icon accessible names, validation and error messages, empty/loading states,
   dialogs, menus, dropdown/portal content, notifications, and dynamically
   refreshed components. Nested translated fragments resolve to the most
   specific target without flicker or competing overlays.

   Ordinary business tooltips remain unchanged and continue to open normally;
   the inspector panel does not replace, append to, obscure, or delay them. Its
   outline and panel are additional diagnostics only. The panel and highlight
   work in English LTR and Arabic RTL, with logical placement and no loss of
   keyboard focus or screen-reader meaning.

   The mode covers catalogue-backed application messages only. User-authored
   values, Aggregation/Record titles and descriptions, identifiers, and entity
   translation JSON values are not assigned synthetic UI message keys. The
   inspector cannot edit or publish translations. Draft status, origin, review
   history, or unpublished text is not added to ordinary catalogue responses;
   if later shown after pinning, it must be retrieved through the existing
   authorized filtered administration endpoint.

   No new database table or preference endpoint is required. The existing
   authenticated bootstrap supplies effective privileges, and the published
   catalogue/renderer already knows the key, effective language, rendered text,
   and fallback result. The existing message-list endpoint supports the
   filtered administration destination. This phase must not add per-element API
   requests.

   The switch, panel, outline, and diagnostic behavior are unavailable unless
   the current authenticated principal has `localization.administer`; the
   server-provided effective privilege is rechecked after identity refresh.
   Revocation disables and clears the inspector immediately. Direct client
   manipulation must not unlock translation administration APIs or reveal
   drafts. Ordinary users must experience no visible, performance, layout, or
   interaction difference.

### 21.1 Approved Arabic terminology reference

Best-effort generation must use the following approved English-to-Arabic domain
terminology as reference and translator guidance:

| English term | Approved Arabic reference |
| --- | --- |
| Record | وثيقة |
| Records | وثائق |
| Aggregation | ملف |
| Aggregations | ملفات |
| Parent aggregation | الملف الحاوي |
| Containing aggregation | الملف الحاوي |
| Scheme | نظام التصنيف |
| Schemes | نظم التصنيف |
| Classification | تصنيف |
| Classifications | تصنيفات |
| Digital component | المكوّن الرقمي |
| Digital components | المكوّنات الرقمية |
| Sharjah Archives | دار الوثائق في إمارة الشارقة |
| Audit Trail | مسار التتبع |
| Current period | الفترة الجارية |
| Intermediate period | الفترة الوسيطة |
| Destruction | الإتلاف |
| Disposition Job | عملية تصرف |
| Disposition Jobs | عمليات التصرف |
| Destruction Job | عملية إتلاف |
| Task | مهمة |
| Tasks | مهام |
| My Tasks | مهامي |
| Role | الدور |
| Legal Hold | تعليق القنوني |
| Mixed (record medium) | هجين |
| Physical (record medium) | مادي |
| Records Unit (organizational unit) | وحدة الوثائق |
| Retention Rule | قاعدة الحفظ |
| Security Level | درجة السرية |
| Selective Preservation | الإنتقاء |
| Permanent Preservation | حفظ الدائم |
| Vital record | الوثائق الهيوية |
| Close (aggregation lifecycle action) | إغلاق |
| Checksum | مجموع التحقق |
| Inherit | يستمد |
| System Administrator | مسؤول النظام |
| Delete | حذف |
| Filter | التصفية |
| Dashboard | لوحة المعلومات |
| Title | العنوان |

These mappings establish the preferred Wathiq domain vocabulary and proper-name
translations for generated UI-message drafts. The generator must use the
singular or plural term that
matches the English message's meaning and parameter/count context. **Scheme**
and **Schemes** in this glossary mean classification schemes, not an unrelated
general use of the English word. **Parent aggregation** and **Containing
aggregation** use **الملف الحاوي** to express direct containment; the term must
not be replaced with wording that incorrectly implies the root, main, or
original file. **Digital component** remains distinct from **Aggregation** and
must not be translated as **ملف رقمي**, because **ملف** is the approved Wathiq
term for an aggregation. **Mixed** and **Physical** apply specifically to record
medium values. **Records Unit** applies specifically to the named organizational
unit. **Close** applies specifically to the aggregation lifecycle action, not to
proximity, dismissing a dialog, or closing another kind of object. Translators
must not treat these contextual mappings—including action labels and field
labels such as **Inherit**, **Delete**, **Filter**, and **Title**—as universal
translations of the same English words in unrelated messages.

The glossary is guidance for contextual translation, not a blind substring-
replacement table. Arabic grammar, definiteness, agreement, sentence position,
and surrounding meaning may require the term to be inflected or phrased
naturally. Generated results remain `draft`, retain `origin = generated`, and
require administrator review and explicit publication. Administrators may
correct a generated phrase where context requires it without changing the
approved underlying domain meaning.

Best-effort output must use clear, idiomatic, accessible Modern Standard Arabic
appropriate for an enterprise records-management application. It must translate
the intended meaning and user action in context rather than reproduce English
word order or substitute words one by one. A draft is unacceptable when its
individual terms are technically recognizable but the resulting Arabic is
unnatural, ambiguous, overly technical, needlessly complex, or difficult for an
ordinary Arabic-speaking administrator or user to understand.

The generator should prefer concise familiar wording, natural Arabic sentence
structure, direct action language, and terminology consistent with the rest of
Wathiq. It must preserve named placeholders exactly while placing them where
Arabic grammar requires. Translator guidance and semantic meaning take
precedence over literal similarity to the English source. Administrator review
must explicitly consider idiomatic quality, clarity, accessibility, domain
accuracy, and consistency—not only whether every English word appears to have
an Arabic equivalent.

Generation tests and the administrator review report must identify messages
containing these English domain terms and verify or flag whether the generated
Arabic draft follows the approved terminology in context. Quality sampling
must also flag literal English-shaped constructions, unnatural word order,
ambiguous actions, unnecessary jargon, and inaccessible phrasing for human
correction before publication.

No phase is complete while a requirement mapped to it lacks implementation and
verification evidence.
