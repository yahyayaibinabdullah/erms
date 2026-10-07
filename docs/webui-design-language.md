# Wathiq WebUI Design Language

**Status:** Normative — sole WebUI design-language authority  
**Applies to:** `frontend/webui` only  
**Audience:** Wathiq developers, reviewers, and agentic implementation tools  
**Prepared:** 26 September 2026  
**Revision:** 1.4 — NiceGUI-first layout and RTL troubleshooting

## 1. Purpose and authority

This document is the normative design language for Wathiq's browser-based
NiceGUI WebUI. Its purpose is to keep new screens and components visually and
behaviorally consistent, reduce one-off presentation code, and maximize reuse
of established application components.

It applies to new and changed code under `frontend/webui`. It does not define a
mobile, native, public portal, or third-party client design system.

Approved feature specifications remain authoritative for product behavior,
authorization, workflow, and domain rules. This document governs how those
requirements are presented in the WebUI. When a feature specification includes
more specific approved UI requirements, satisfy both where possible; if they
conflict, stop and resolve the conflict before implementation.

This document incorporates and supersedes the former
[Web UI visual design](ui-visual-design.md) document in full. The former
document is deprecated, retained only as historical context, and has no
remaining normative authority—not even for feature-specific decisions. New
work, reviews, specifications, and agent instructions must cite and follow this
document instead. If wording in the deprecated document differs from this one,
this document governs.

The incorporated decisions include the light visual foundation, application
shell, detail-field hierarchy, page-table treatment, compact page-header action
groups, Dashboard chart rules, aggregation retention-lifecycle presentation,
responsive behavior, and accessibility expectations. They are restated and
expanded in the applicable sections below so readers do not need the deprecated
document to implement or review WebUI work.

## 2. Design character

Wathiq is a calm, compact, information-dense enterprise application. It should
feel dependable and precise rather than decorative.

The governing principles are:

1. **Reuse before invention.** Use an existing renderer, CSS class, helper, or
   interaction pattern before creating another implementation.
2. **Information before decoration.** Use hierarchy, spacing, borders, labels,
   and typography to make information clear. Avoid ornamental surfaces.
3. **Compact by default.** Present useful context without oversized cards,
   excessive whitespace, or repeated facts.
4. **Cards before generic tables.** Use compact card/list treatments for
   heterogeneous or action-rich information. Use a matrix/table only when rows
   and columns materially improve comparison.
5. **Progressive disclosure.** Keep routine work simple; reveal advanced
   controls, diagnostics, long guidance, and secondary data when requested.
6. **Business language.** Explain the task and consequence in plain language.
   Do not expose implementation terminology where a business term exists.
7. **Consistent actions.** The same action uses the same icon, color, location,
   confirmation behavior, and wording throughout the WebUI.
8. **Authorization is presentation state, not decoration.** Do not render an
   action a user cannot invoke unless the approved workflow explicitly requires
   a disabled action with an explanation.
9. **Accessibility and bidirectionality are structural.** Keyboard behavior,
   accessible names, focus, zoom, responsive flow, and RTL must be designed at
   component creation time.
10. **No false affordances.** Interactive styling means the element works;
    read-only values must not look clickable.

## 3. Current implementation architecture

The WebUI is a NiceGUI service that calls FastAPI through
`frontend/webui/api_client.py`. It must not access PostgreSQL directly.

The primary application is currently composed in `frontend/webui/app.py`.
Reusable nonvisual policy and formatting surfaces already include:

- `frontend/webui/entities.py` for common entity and field definitions;
- `frontend/webui/capabilities.py` for navigation and action visibility;
- `frontend/webui/authorization_ui.py` for authorization labels and guidance;
- `frontend/webui/acl_editor.py` for ACL selection rules; and
- reusable functions in `app.py`, including field construction, relationship
  selectors, avatars, formatting, favourites, compact resource results,
  component cards, navigation history, event timelines, and entity editors.

The size of `app.py` is not permission to copy another block into it. Before
adding UI code, search by visible text, CSS class, icon name, entity type, and
interaction. Extend the existing implementation where its semantics match.

All new and changed WebUI work must also follow the normative
[WebUI performance contract](webui-performance.md), including its critical-path,
request orchestration, cache-invalidation, stale-while-revalidate, and
verification rules.

### 3.1 Reuse decision

For every new component, apply this order:

1. Use an existing shared renderer or helper unchanged.
2. Add an option to an existing renderer when the information hierarchy and
   interaction remain the same.
3. Extract repeated presentation into a named helper/component when a second
   real use exists or the feature specification establishes a reusable pattern.
4. Create a feature-local component only when no established component has the
   same semantics.
5. Create a new visual pattern only with an explicit reason recorded in the
   feature specification or implementation notes.

Do not make an existing renderer accept unrelated modes merely to avoid a new
component. Reuse means shared semantics, not a single function with many
unrelated flags.

### 3.2 Location of new shared code

Small extensions may remain beside the current shared helper in `app.py`.
Substantial new reusable presentation should be placed in a focused module
under `frontend/webui/components/` and imported by `app.py`. The module should
expose a small typed surface and keep API access, authorization decisions, and
navigation callbacks with the page/controller unless those behaviors are
genuinely shared.

New cross-screen strings, icons, status mappings, and field definitions must
not be duplicated across page functions. Put them in the relevant catalogue or
shared module. Internationalized work follows the approved
[Internationalization and User Preferences specification](../specs/internationalization-and-user-preferences.md).

For all new or changed screens—including work performed by Agentic AI—the
implementing developer/agent must maintain translation keys as part of the same
active development change. It automatically adds definitions for new visible
text, updates definitions when wording/semantics/placeholders change, and
removes definitions for deleted UI only after proving that no references
remain. This includes labels, actions, tooltips, accessible names, guidance,
validation, errors, statuses, loading/empty states, and confirmations.

The agent must supply the English source, contextual grouping, semantic
meaning, locations, translator guidance, parameter schema, and example required
by the internationalization specification. It must preserve administrator-
authored translations, mark affected translations for review after source or
placeholder changes, use the audited synchronization path, and run completeness
and stale-key checks before handoff. UI work is incomplete when its catalogue
changes are deferred to a later task.

The completeness audit must inspect rendered-text construction, not only
literal arguments passed directly to NiceGUI. It must cover f-strings and
other interpolated expressions, conditional labels, option dictionaries,
text assigned after component creation, intermediate variables subsequently
passed to a component, notifications, tooltips, and accessible names embedded
in component properties. A literal-only extractor is not acceptable evidence
that a screen is localized. The checked-in
`frontend/webui/scripts/extract_english_messages.py` report is the minimum
repository-wide audit; new development must not add unresolved candidates.

For Arabic, the same change must update the checked-in generated draft
catalogue: add contextual drafts for new keys, regenerate drafts for materially
changed keys, and remove entries for safely removed definitions. The agent must
preserve placeholders, use the approved Arabic terminology, refresh provenance
and hashes, and run Arabic completeness and quality checks. The generic seed
utility remains key-agnostic and is run explicitly; UI development must not add
per-key logic to it or restore translation writes to API startup.

The checked-in Arabic artifact may contain reviewed administrator wording
exported from Translation Administration. It is therefore a merge input, not a
disposable generator output. Before changing UI keys, the developer or agent
must read `frontend/webui/i18n/messages.ar.generated.json`, preserve curated
values and provenance by `message_key`, and generate only missing new entries
or explicitly invalidated machine-generated entries. A complete regeneration
that overwrites administrator wording is prohibited. Database-only edits are
not visible to source development until a complete export is deliberately
promoted to that path. The normative promotion, merge, validation, and blocked-
handoff rules are in sections 7.8.1–7.8.3 of the approved internationalization
specification.

## 4. Visual foundation

### 4.1 Color tokens

Use the existing CSS custom properties and NiceGUI color configuration. Do not
introduce near-duplicate blues, greys, or semantic colors in feature code.

| Role | Current token/value | Use |
| --- | --- | --- |
| Primary blue | `--erms-blue: #268bd2` | Primary actions, links, selected emphasis |
| Deep blue | `--erms-blue-deep: #176da8` | Strong labels, headings, active navigation |
| Soft blue | `--erms-blue-soft: #eaf5fc` | Selection, informational emphasis, icon surfaces |
| Ink | `--erms-ink: #172033` | Primary text |
| Muted | `--erms-muted: #687386` | Secondary text and metadata |
| Surface | `--erms-surface: #fff` | Cards and controls |
| Border | `--erms-border: #e1e6eb` | Fine separators and card outlines |
| Positive | `#2f9e44` | Successful/positive state |
| Warning | `#e9a23b` | Warning, attention, suspended/closed context |
| Negative | `#dc5050` | Destructive action and error |

Pale semantic backgrounds are acceptable for warnings, errors, and healthy
status panels when paired with readable text and a border. Color never carries
meaning alone.

### 4.2 Surfaces and elevation

- The application canvas, header, drawer, and content use a light visual system.
- Separate regions with fine borders, not heavy shadows or dark panels.
- Standard cards use `erms-card`: white surface, one-pixel neutral border,
  14-pixel radius, and no elevation.
- Nested cards use a related 9–12 pixel radius and must not create layers of
  redundant borders and padding.
- Dialogs may use overlay separation, but their content remains flat and
  restrained.
- Avoid gradients except established brand/login artwork or a separately
  approved visualization.

### 4.3 Typography

- Use the application font stack: Inter when available, then platform UI fonts.
- The Wathiq wordmark alone uses Righteous.
- Page title: approximately `text-2xl font-semibold`.
- Major section heading: `text-lg font-semibold`.
- Card/entity title: `text-base` or `text-sm font-semibold`, depending on
  density.
- Body: `text-sm` with readable line height.
- Supporting text: `text-xs` or `text-sm text-slate-500/600`.
- Field label: the shared `detail-field-label` treatment—small, subdued,
  consistent, and visually separate from its value.
- Stable codes and identifiers may use stronger primary color or monospaced
  presentation where copy accuracy benefits.

Use weight and spacing for hierarchy. Do not create decorative display headings
inside application screens. Sentence case is the default for labels and
headings; all-uppercase is reserved for established small navigation/category
labels.

### 4.4 Spacing and density

Use the established compact rhythm:

- 4–8 pixels between tightly related inline items;
- 8–12 pixels within compact rows and cards;
- 14–20 pixels for ordinary card padding;
- 16–20 pixels between major page regions; and
- page content padding equivalent to the current `p-5` treatment.

Do not add whitespace to make a sparse page appear more substantial. Use a
purposeful empty state or concise guidance instead.

### 4.5 Icons

Use Material Symbols already loaded by the application. Navigation uses the
outlined, unfilled weight-300 treatment. Reuse established icon meanings:

| Meaning | Icon |
| --- | --- |
| Aggregation | `folder` |
| Record | `description` |
| Open details | `open_in_new` |
| View/preview | `visibility` |
| Edit | `edit` |
| Delete | `delete_outline` or `delete_forever` for explicit permanent deletion |
| History | `history` |
| Search | `search` / `manage_search` according to current context |
| Favourite | `favorite` / `favorite_border` |
| Organization unit | `corporate_fare` |
| Role | `badge` |
| Person user | `person` |
| Service identity | `smart_toy` |
| Security | `shield` |
| Legal hold | `gavel` |

Do not choose a different icon for an established meaning. Spatial icons such
as chevrons must mirror or change direction in RTL; semantic icons do not.

## 5. Application shell

The authenticated shell consists of the fixed header, collapsible navigation
drawer, persistent navigation-history breadcrumb, bounded content canvas, and
connection-status footer.

### 5.1 Header

- Keep the Wathiq mark/name at the start edge, global search centrally
  prominent, and the current-user menu at the end edge.
- The global search is the only search control in the shell. Page filters remain
  inside page content.
- Preserve the responsive header behavior: global search becomes a full-width
  row at narrow widths.
- Do not place feature-specific commands in the global header.

### 5.2 Navigation drawer

- Use the established section order and privilege-driven visibility.
- Empty sections are not rendered.
- The expanded drawer shows icon and one-line label; the collapsed drawer is a
  usable icon rail, not a decorative state.
- The current destination uses the established pale-yellow active background,
  blue rail, dark-blue text, and `aria-current="page"`.
- Drawer scrolling is independent of the page canvas.
- A new primary destination requires an approved navigation requirement and an
  exact capability rule in `capabilities.py`.

### 5.3 Breadcrumbs

Use the persistent navigation-history breadcrumb and its restoration behavior.
Do not create a second breadcrumb system or hard-code browser-back assumptions.
Detail pages use the shared breadcrumb/back behavior and preserve relevant
collection state where the current implementation supports it.

### 5.4 Page frame

Authenticated content uses the existing bounded `erms-content` canvas. A page
begins with:

1. an optional established page-title icon;
2. one page title;
3. a short subtitle when it materially identifies scope or purpose; and
4. a non-wrapping primary action group aligned with the title.

Long titles truncate or yield space before splitting a related action group.
Do not repeat the page title inside the first card.

The Dashboard and primary collection pages for Aggregations, Records,
Classification Schemes, Organization Units, Roles, and Users use their
established lightweight outlined icon immediately before the page title. Pages
without an approved title icon hide the icon; they must not retain a stale icon
from the previously visited page.

## 6. Page composition patterns

Choose the existing pattern that matches the user task.

### 6.1 Collection/search page

Use for aggregations, records, classifications, and other discovery tasks:

1. page heading and permitted primary creation action;
2. personal/recent context where the approved feature supplies it;
3. compact search/filter controls;
4. result summary;
5. the canonical result listing; and
6. pagination or explicit load-more behavior.

Search-first pages show useful guidance, favourites, or recents before the
first search. Do not load a large unfiltered dataset merely to avoid an empty
screen.

### 6.2 Administrative catalogue

Use for users, roles, organization units, profiles, security levels, and future
administrative resources:

- a one-column `governance-card-list`;
- compact filters and sorting above the list;
- one `governance-list-card` per item;
- icon and identity at the top;
- status badge at the far edge;
- a compact `governance-list-facts` grid; and
- icon-only row/card actions in a consistent trailing action area.

This one-column card pattern is the default for action-rich administration.
Do not replace it with a generic table simply because the data is tabular.

### 6.3 Detail/command page

Use for an individual record, aggregation, user, role, organization unit,
service identity, legal hold, or similarly consequential resource.

- Identity and stable reference are visually dominant.
- Summary metadata uses shared detail fields and bounded long values.
- The main information region and command/control region use the established
  two-column command layout where there are several actions.
- Related actions are grouped by purpose and use concise group labels.
- Destructive and exceptional commands remain separate from ordinary metadata
  editing.
- At narrower widths, the command column moves below the overview without
  hiding actions or changing their order.

Record details retain the complete Digital Components interface immediately
after the record overview/metadata region. Do not move components into a
separate primary destination or require an additional dialog merely to reach
the list.

Do not turn a detail page into a vertical sequence of unrelated full-width
panels when a compact overview and command rail communicate the task better.

### 6.4 Workspace/browser page

Hierarchical or builder workflows may use a split workspace: tree/builder/list
on one side and summary or saved-item controls on the other. Follow the current
classification, organization, aggregation-browser, and advanced-search
patterns:

- use a bounded, independently scrollable browser where necessary;
- keep current selection visually clear;
- put the primary work before secondary saved/history actions;
- preserve state across drill-down where the approved workflow requires it;
  and
- collapse to one column at an intentional breakpoint.

### 6.5 Dashboard

The Dashboard prioritizes concise holdings and attention information. Charts
supplement labelled values and lists; they never replace them. Use direct
labels, visible totals, tabular numerals, accessible legends, and a truthful
zero state. New charts must use the established bordered white chart surfaces
and responsive stacking patterns.

Preserve the existing chart semantics:

- attention signals use directly labelled grouped bars for Vital and On hold;
- organizational-unit holdings use labelled horizontal bars segmented into
  Physical, Digital, and Mixed records;
- review urgency uses a directly labelled part-to-whole ring for Overdue and
  the configured upcoming-review window; and
- organizational-unit storage ranks the five largest authorized totals and
  follows them with a separated textual Other units summary.

On narrow screens, legends wrap, review urgency stacks above reminder lists,
and long organizational-unit labels truncate with the full value available in
an accessible tooltip and detail row.

## 7. Canonical components

### 7.1 Compact governed-content results

`render_compact_resource_result` and the `compact-result-*` classes are the
canonical result treatment for aggregation and record search, global search,
advanced search, and reusable favourite/recent result contexts.

The hierarchy is:

- type icon;
- stable number and title on one compact line;
- date and small semantic indicators;
- optional parent aggregation;
- optional matched-component expansion; and
- trailing icon-only actions.

Reuse this renderer rather than reproducing a record/aggregation result card.
Add options only for semantics shared by governed-content results.

### 7.2 Governance cards

`governance-card-list`, `governance-list-card`, `governance-card-icon`, and
`governance-list-facts` form the canonical administrative listing. Facts use
the same field-label hierarchy as detail surfaces. Values that navigate to a
related entity use primary-color interactive styling and a tooltip; scalar
values remain plain text.

### 7.3 Detail fields and surfaces

Use `detail-surface`, `detail-field`, `detail-field-label`, and
`detail-field-value` for ordinary metadata. A field consists of one consistent
label and one readable value. Use `—` for an unavailable scalar value unless a
more helpful approved empty phrase exists.

Long identifiers and descriptions must wrap, truncate with a tooltip, or use a
bounded quiet inset surface according to their reading value. Never allow one
unbroken value to expand the page width.

### 7.4 Digital-component cards and viewer

Use `render_component_cards`, `component_uploader`, and the existing
`component-*` classes. File name and recognizable file type lead; size, order,
dates, and index status are secondary. Component actions stay in the shared
compact action row and are capability-gated.

Do not add a second file viewer or upload treatment. Preview, download, print,
replacement, reorder, removal, and reindex remain distinct authorized actions.

### 7.5 Relationship controls

Use `relationship_select`, `style_person_select`, and
`style_relationship_chip_select` for relationship values. Options show human
business identity before internal IDs. Selected values and browse dialogs must
update atomically so the control never displays a raw unresolved identifier.

Do not use a plain numeric input for a foreign key. Do not render a scalar as a
relationship link merely because it contains an ID-like value.

### 7.6 Avatars

Use `user_avatar` and `render_user_avatar`. Initials and color are stable for a
user. Do not introduce random avatar colors on each render or a different
initials algorithm on another screen.

### 7.7 Event history

Use the shared event timeline and event-detail dialog. History is chronological
evidence, not an ordinary editable list. Preserve actor, event identity,
before/after presentation, safe reference snapshots, and navigation rules.

### 7.8 Retention and lifecycle visualization

Use the existing three-stage retention treatment for current, intermediate,
and final disposition. Preserve provenance and rule source. Do not replace it
with isolated statistic cards or a decorative chart.

The stages mean Current (active), Intermediate (semi-active), and Final
disposition. The vertical blue line and stage markers express sequence. On an
aggregation detail page, the retention panel sits beside the primary metadata
surface and wraps below it on narrower viewports. Child-aggregation and record
totals appear once in the metadata field named **Contains** and are not repeated
as oversized statistics.

### 7.9 Empty, loading, and error states

Every asynchronous content region has deliberate states:

- **Loading:** retain layout stability and show a local spinner or skeleton for
  the region being refreshed; do not blank the entire application.
- **Empty before action:** explain what the user can search, add, or configure.
- **Empty after filtering:** say that no items match and keep filter controls.
- **No permission:** hide unauthorized actions; use an approved explanatory
  state only where the user is allowed to know the resource exists.
- **Partial/unavailable:** preserve usable results and explain the limitation.
- **Error:** use a translated, safe message and an appropriate recovery action.

Use `governance-empty-state` or `governance-empty-inline` for administration
surfaces. Empty states should not be bare whitespace or only the word “None”.

## 8. Forms and data entry

### 8.1 Controls

- Standard inputs are outlined and full width within their grid cell.
- Dense controls are appropriate in filters and compact administration panels.
- Ordinary edit forms retain comfortable control height.
- Use the existing `field_input`/`FieldSpec` path for generic entity fields.
- Use `textarea` with autogrow for narrative values.
- Use selects for controlled catalogues and booleans; do not ask users to type
  stored enum codes.
- Date/time controls must follow the internationalization specification and
  never infer the server's timezone.

### 8.2 Labels, required fields, and help

Every control has a visible label. Required fields use the established visual
marker and concise explanation. Placeholder text supplements a label; it does
not replace one.

Place short contextual guidance near the relevant field. Explain why a control
is disabled when the user can reasonably act on the cause. Long guidance uses
progressive disclosure. Tooltips are not the sole home of required instructions
or validation errors.

### 8.3 Validation

Validate close to the control and preserve entered values. Messages describe
the correction in simple language. On submit, focus or reveal the first invalid
control. API validation and concurrency failures must be reconciled without
silently discarding the user's work.

### 8.4 Advanced and infrequent fields

Keep routine forms short. Put translations, diagnostics, inherited-policy
details, and other advanced inputs behind a clearly named disclosure or
secondary dialog when the approved workflow allows it. Do not conceal a field
required to complete the ordinary task.

## 9. Actions and interaction

### 9.1 Action hierarchy

- **Primary page/dialog action:** text plus established icon, unelevated primary
  button, normally one per scope.
- **Secondary action:** flat or outline treatment with text when the action is
  not repeated per row.
- **Row/card action:** icon-only, compact, with tooltip and accessible name.
- **Destructive action:** negative color, explicit wording in confirmation, and
  `delete_forever` only when permanent deletion is truly meant.
- **Status indicator:** icon or badge; it must not look like a button unless it
  is actionable.

Avoid multiple visually primary actions in one group. Preserve a stable order:
open/view, ordinary edit, specialized management, history, destructive action.

### 9.2 Icon-only controls

Every icon-only button requires:

- localized tooltip;
- localized `aria-label`;
- visible keyboard focus;
- keyboard activation;
- at least the established compact 34–36 pixel target, with adequate spacing;
- disabled state when temporarily unavailable; and
- propagation control when embedded in a clickable row/card.

The favourite button is the reference for dynamic icon, color, tooltip, and
accessible-name updates.

### 9.3 Clickable rows and cards

A clickable container has a visible hover/focus treatment and one clear default
destination. Nested buttons must stop propagation. Double-click must not be the
only route to an action. Do not make text selectable only by sacrificing
keyboard access.

### 9.4 Feedback

Use notifications for short operation outcomes:

- positive for successful completion;
- negative with close control for errors;
- warning for attention that did not fail; and
- information for neutral queued/background work.

Do not rely on a toast for information the user must retain or act upon. Put
that content in the page or a persistent dialog.

Prevent duplicate submission while a request is active. Optimistic UI changes
must roll back visibly if the request fails.

## 10. Dialogs

Use dialogs for focused creation/editing, confirmation, bounded selection, and
detailed evidence that should not replace the current page.

- Standard width is approximately 480–760 pixels according to content, always
  bounded by viewport width and height.
- Title appears once at the top.
- Guidance and consequence follow the title.
- The body scrolls when necessary; the action row remains reachable.
- Actions align to the end edge, with Cancel before the primary action in LTR
  logical order.
- A destructive confirmation names the entity and consequence.
- A mandatory reason is an explicit labelled field, not inferred from the
  confirmation button.
- Use a persistent dialog when accidental outside-click dismissal would lose
  sensitive data, a one-time credential, or a consequential decision.

Do not nest dialogs except where an established browse/select workflow
requires it and focus restoration has been verified.

## 11. Lists, matrices, and tables

### 11.1 Default choice

Use a compact list/card when items contain different facts, status, guidance,
or several actions. Use a table/matrix when users need repeated-field
comparison across many homogeneous rows.

### 11.2 Table requirements

New user-facing tables must:

- reuse a comparable Wathiq table and the `erms-page-table` or appropriate
  established specialized class;
- be inset from the containing card;
- use pale-blue headers, fine borders, compact spacing, and the surrounding
  typography;
- provide sorting for meaningful data columns and never for action columns;
- provide a compact text filter where users need to locate loaded rows;
- provide pagination for bounded reading;
- define deliberate loading, empty, partial, and error states;
- keep actions visually compact and aligned; and
- be inspected in a live browser before completion.

A raw or default-styled NiceGUI `ui.table` is prohibited. The presence of a few
legacy or specialized `ui.table` uses is not a pattern to copy.

### 11.3 Matrix requirements

A matrix is justified for genuinely two-dimensional tasks such as language by
translation-context coverage or permission by principal. Keep headers sticky
where useful, row/column labels visible, cells compact, and status perceivable
without color alone. On narrow screens, use intentional horizontal scrolling
with the identifying column retained where practical; do not squeeze text into
unreadable cells.

## 12. Search, filtering, sorting, and pagination

- Search controls state what can be searched in plain language.
- Use debounced input for local filtering and explicit submission where an API
  search may be expensive or semantically meaningful.
- Distinguish server search from filtering rows already loaded.
- Keep related filters in one wrapping row and align their lower edges.
- Show a concise result count/range.
- Use deterministic sort tie-breakers so pagination does not reorder items.
- Keep page-size choices bounded and consistent with comparable screens.
- Disable unavailable first/previous/next/last actions.
- Preserve search, page, expansion, and return-anchor state when the approved
  workflow drills into a result and returns.

Do not use wildcard syntax where partial matching is automatic. Do not expose
raw query grammar unless an approved advanced feature explicitly requires it.

## 13. Status, badges, and semantic presentation

Use outlined badges for ordinary statuses and compact categories. Use filled or
strong semantic treatment sparingly for immediate warning or destructive
meaning.

Status text uses business wording, not raw stored codes. Pair important status
with an icon or explicit label. Common semantic use is:

- green: active, open, healthy, completed;
- amber: suspended, warning, needs attention, closed where current established
  screens use warning semantics;
- red: destructive, failed, critical, vital attention where explicitly
  established; and
- blue/blue-grey: informational, neutral, built-in, inactive context.

One status must not change color meaning between screens. If a domain status
does not fit the existing palette, define it once in a shared mapping.

## 14. Responsive behavior

Desktop density is not permission to break narrow screens.

- Prefer standard NiceGUI layout configuration. Where custom CSS is necessary
  under section 19.1, use grid/flex with `minmax(0, 1fr)` and `min-width: 0` so
  long content can shrink safely.
- Major two-column layouts collapse to one column at an intentional breakpoint,
  generally around the established 760–900 pixel range.
- Controls wrap as groups; related action buttons stay together.
- Do not hide a required action on mobile.
- Tables/matrices may scroll horizontally only when a card/list transformation
  would harm comparison.
- Truncated values expose their full value through an accessible tooltip or
  detail view.
- Verify the supported desktop width and narrow/mobile width in a live browser.

Avoid fixed pixel widths unless the element has a stable semantic size, such as
an icon, avatar, narrow date column, or bounded dialog.

## 15. RTL and internationalization

All new components must work with root `lang` and `dir` changes. Follow the
internationalization specification for message keys, templates, user language,
timezone, translated entity values, and administrative translation screens.

- Prefer supported NiceGUI direction and alignment configuration; follow
  section 19.1 when troubleshooting. When CSS is necessary, use logical
  properties and logical start/end alignment.
- Mirror navigation, spatial chevrons, indentation, and directional layout.
- Do not mirror semantic icons.
- Propagated/portal content such as menus, dropdowns, dialogs, and tooltips must
  receive the effective direction.
- Isolate codes, email addresses, paths, identifiers, and other LTR tokens.
- Use the shared date/time and number formatting services when introduced; do
  not add more process-local formatting.
- Allow translated strings to expand without clipping controls.

English LTR success is not sufficient evidence. New components require Arabic
RTL browser verification.

## 16. Accessibility

The target is an operable, understandable WebUI for keyboard and assistive-
technology users.

- Use semantic elements/roles where available.
- Maintain a logical heading hierarchy with one page title.
- Every control has an accessible name.
- Every icon-only action has both tooltip and accessible name.
- Focus order follows reading and visual order.
- Dialog focus is contained and returns to its invoker.
- Visible focus must not be removed.
- Error text is associated with its control and announced where appropriate.
- Live status changes use appropriate live-region behavior without flooding.
- Text and controls remain usable at 200% zoom.
- Color is never the only signal.
- Motion is restrained and respects reduced-motion preferences where added.
- Full values remain available when visual truncation is used.

Tooltips improve discoverability but do not replace labels for form controls or
critical instructions.

## 17. Authorization and sensitive information

Page navigation and actions use exact capability checks from authoritative API
responses and shared capability helpers. The WebUI is not an authorization
boundary, but it must accurately represent authorization.

- Hide actions the current user is not authorized to invoke.
- Use a disabled action only when the approved design requires users to
  understand that the action exists and provides an exact reason it is blocked.
- Fail closed when a governed capability is absent.
- Do not infer authorization from a broad role label in presentation code.
- Do not disclose hidden entity names, counts, relationships, search matches,
  or diagnostic details through empty states or tooltips.
- One-time credentials and secrets use persistent bounded dialogs and are never
  redisplayed after dismissal.
- Raw API/database error details are not shown to users.

## 18. Content and guidance

Use concise, direct, accessible English source text suitable for translation.

- Button labels start with a verb: **Add record**, **Save changes**, **Close
  aggregation**.
- Headings describe the content, not the component: **Assigned roles**, not
  **Roles card**.
- Empty states state what is absent and, where helpful, the next action.
- Confirmation text identifies the resource and consequence.
- Avoid jargon, internal endpoint names, database terms, and raw enum codes.
- Keep one concept per sentence.
- Do not concatenate translated sentence fragments.
- Named placeholders represent complete semantic values only. Never expose
  English plural suffixes, capitalization/lowercasing operations, verb endings,
  punctuation fragments, or partial words as translation parameters.
- Translation administrators preserve placeholder names and braces exactly,
  but may reorder complete placeholders to produce natural target-language
  grammar. Adding, removing, or renaming a placeholder is a definition change,
  not an administrator translation edit.
- Use contextual translation keys when the same English word has different
  meanings.

Guidance should be adjacent to the decision it explains. Short action help may
use a tooltip. Policy, irreversible consequences, and corrective instructions
must remain visible in the page or dialog.

## 19. CSS and styling rules

Layout and RTL troubleshooting must follow section 19.1 before introducing
custom CSS or lower-level Quasar primitives. The styling rules below govern
necessary styling; they do not authorize bypassing NiceGUI configuration.

- Prefer shared semantic classes over repeated long utility strings for a
  component pattern.
- Utility classes are appropriate for local layout and small one-off alignment.
- Extend root design tokens instead of embedding a new near-match color.
- Scope feature-specific CSS under a clear feature/component class.
- Use logical properties for new directional CSS.
- Do not target fragile generated element IDs or broad framework internals when
  a component class can express the rule.
- Framework-internal selectors are acceptable only for a bounded shared
  component that cannot be styled through its public surface; document the
  reason beside the CSS.
- Responsive and RTL variants live with the component rule.
- Remove superseded styles when replacing a pattern; do not leave parallel
  visual systems active.

The long inline stylesheet in `app.py` is the current source of truth. New work
should avoid making it less maintainable. When a component is extracted into a
module, move its cohesive styles to an appropriately loaded static stylesheet
or documented style surface rather than duplicating them.

### 19.1 NiceGUI-first layout and RTL troubleshooting

The sign-in page restores document and dialog direction before authentication,
using the remembered localization context. Previously the direction script
ran during authenticated bootstrap, leaving signed-out portal content without
the full RTL setup. The native login card explicitly carries `dir` and `lang`;
its standard NiceGUI fields and layout inherit these settings. Direction-only checks initially confirmed RTL inheritance but missed physical
placement. Follow-up browser inspection on 4 October found the global RTL
`.row { flex-direction: row-reverse }` double-reversed native RTL flex rows,
and Quasar floating labels retained a physical left anchor. NiceGUI document
direction, native card `dir`/`lang`, and standard Row/Input/Select configuration
do not override those existing stylesheet rules or expose label-anchor spacing.
A narrowly scoped correction inside `.wathiq-login-card` and
`.messaging-workspace` restores native `row` flow in RTL, right-anchors field
labels and mirrors append/prepend padding. Native components and keyboard
behavior remain intact. Browser measurements confirmed Arabic password append
on the left, labels on the right, and mailbox actions flowing right to left.
The login button retains the Material login glyph: native `icon-right=login`
places it left of Arabic text, and a button-scoped RTL horizontal transform
mirrors the arrow. NiceGUI icon naming/position props expose no mirrored
variant of this glyph. English keeps the original icon and position.
Credential inputs use the native QInput `input-style` property to set
`direction: ltr; unicode-bidi: isolate` on the editable input only. Browser
inspection found these inputs previously inherited RTL with normal bidi.
The field wrapper, Arabic labels and password visibility control retain RTL;
no custom CSS is needed for credential text direction. No text, translation
key or credential validation rule changes.
English remains LTR. Rejected credentials use a specific neutral login error rather than
the generic expired-session prompt, consistently for wrong names and passwords.
Four feedback cases and two shared direction tests passed. The new English key
`authentication.error.credentials_not_accepted` has a generated Arabic draft;
2893-key coverage, ordering, placeholder, terminology and artifact validation
passed. Existing translation wording/provenance was preserved; no administrator
export was promoted. The draft was seeded to demo for review/publication while
all 2935 previously protected translation rows remained unchanged.

Saved-search cards keep the Mine/Shared badge at the top trailing edge (right
in English, left in Arabic). A native NiceGUI three-column grid reserves space
for the resource icon, wrapping metadata, and badge; Open occupies its own line.
This replaces the wrapping row that could move the badge beneath long metadata.
The source-rendered cards were checked in a local NiceGUI browser preview at
900px and narrow 360px widths in both directions, with no card overflow; the
Open callback retained the selected search. No custom CSS or translation changes
were needed.

Detail-page action groups align to the reading start: left in English and right
in Arabic. Buttons keep their source order in the reading direction, and each
wrapped line starts at that same edge. Leading button icons precede their labels
with a visible gap. This applies to management, lifecycle, audit, hold controls,
advanced actions, and credential actions. Identity-header Back/Favourite/Preview
groups retain their separate opposite-side placement.

The shared action-panel correction and verification are documented in
[detail action RTL verification](detail-action-rtl-verification.md).

The shared Users, Roles, and Organization Units item-card header uses a native
NiceGUI three-column grid: icon, wrapping title/identity, and trailing status
badge. Browser inspection found the old header inherited `direction: rtl`
but also received the global `.row { flex-direction: row-reverse }` rule,
placing its icon at the far left in Arabic. Standard Row alignment cannot
correct that double reversal. The supported Grid layout follows document
direction without a row override: the icon leads on the right in Arabic and
the left in English, while the badge stays at the opposite edge. No Quasar or
custom CSS fallback is needed.

For developers and agents, the required troubleshooting order is:

1. Reproduce the issue and inspect the existing shared component and its
   NiceGUI configuration. Start with standard NiceGUI components, documented
   configuration, layout APIs, and supported language/direction settings.
2. Explore and exhaust applicable NiceGUI solutions before reaching for
   lower-level Quasar primitives or custom/bare CSS overrides. Merely applying
   a CSS override through a NiceGUI method does not satisfy this requirement.
3. For tricky, persistent, or unclear layout/RTL problems, use the in-app
   browser to inspect the rendered UI before changing layout code. Inspect the
   component/DOM structure, effective direction, computed styles, dimensions,
   overflow, and alignment in the affected state. Compare with a working
   Wathiq component where applicable. If inspection is unavailable, report
   that limitation rather than proceeding with speculative CSS changes.
4. Identify the observed cause and make a targeted correction. Do not randomly
   alter CSS, stack overrides, or repeatedly change alignment/direction rules
   merely to see whether the screen appears to work.
5. If NiceGUI cannot express the required correction, document the applicable
   NiceGUI options investigated and why they are insufficient in the
   implementation notes. Use the smallest supported Quasar or narrowly scoped
   CSS fallback, with its reason recorded beside the code.
6. Verify the rendered correction in English LTR and Arabic RTL, at the
   affected viewport and supported narrow width, including relevant menus,
   dialogs, or other portal content. Remove superseded experimental overrides.

## 20. Testing and review standard

UI work is not complete with source inspection alone.

### 20.1 Required automated evidence

Test as applicable:

- component/helper behavior and data formatting;
- capability-driven visibility and fail-closed behavior;
- loading, empty, populated, partial, error, and conflict states;
- filtering, sorting, pagination, and state restoration;
- nested action propagation;
- accessible names for icon-only actions;
- required-field and validation behavior;
- responsive class/structure expectations;
- RTL structure and localized strings; and
- no unsafe rendering of user/API text.

Source-string assertion tests may protect an important structural contract but
do not substitute for browser interaction tests.

### 20.2 Required live-browser evidence

Compare the implementation with its named reference screen and verify:

- normal desktop width;
- supported narrow/mobile width;
- English LTR;
- Arabic RTL for internationalized components;
- keyboard-only operation and visible focus;
- long titles, descriptions, codes, and translated labels;
- loading, empty, populated, error, and permission-limited states;
- tooltips and accessible action names;
- dialog overflow/focus; and
- no clipped, overlapping, or unreachable controls.

Tables require comparison with a comparable Wathiq table. Listings require
comparison with the established compact result or governance-card listing.

### 20.3 Review questions

Every UI review should answer:

1. Which existing page/component is the visual and interaction reference?
2. Which shared renderer, helper, class, or token is reused?
3. Why is any new component pattern necessary?
4. Are repeated facts or controls present?
5. Does the component remain useful in all asynchronous states?
6. Are permissions and sensitive information represented accurately?
7. Does it work with keyboard, zoom, narrow width, long text, and RTL?
8. Is new reusable logic located where the next developer can find it?

## 21. Reference implementation map

Use this map before designing a new screen.

| Need | Reference implementation |
| --- | --- |
| Application shell, page frame, tokens | `frontend/webui/app.py`: `index`, `erms-*` styles |
| Entity definitions and generic fields | `frontend/webui/entities.py`; `field_input`, `form_payload` |
| Navigation visibility | `frontend/webui/capabilities.py` |
| Compact aggregation/record results | `render_compact_resource_result`; `compact-result-*` |
| Administration listing | `render_table` governance-card branch; `governance-card-*` |
| Favourite action | `favourite_button`, `apply_favourite_button`, `toggle_favourite` |
| User avatar | `user_avatar`, `render_user_avatar` |
| Relationship selector/chips | `relationship_select`, `style_person_select`, `style_relationship_chip_select` |
| Digital component list/upload | `render_component_cards`, `component_uploader`; `component-*` |
| Detail/command layout | record, aggregation, user, role, org-unit detail selectors; `*-command-*` |
| Event history | `show_entity_history`, `render_event_timeline`, `show_event_detail` |
| Authorization labels/guidance | `frontend/webui/authorization_ui.py` |
| ACL dependency behavior | `frontend/webui/acl_editor.py` |
| Empty administration states | `governance-empty-state`, `governance-empty-inline` |
| Page tables | `erms-page-table`, `governance-table`, and specialized table classes |
| Dashboard information cards/charts | `dashboard-*` classes and `select_dashboard` |
| Advanced split workspace | `select_advanced_search`; `advanced-search-*` |
| Persistent breadcrumb/state restoration | navigation helper functions in `app.py` |
| Complete normative WebUI design decisions | This document; the former `docs/ui-visual-design.md` is deprecated history only |

Function names and paths may evolve. When refactoring them, update this map in
the same change so the design language remains actionable.

## 22. Definition of done for a new screen

A new WebUI screen is complete only when:

1. its product behavior matches the approved specification;
2. its reference pattern and reuse decisions are identified;
3. shared components are reused or extended without semantic distortion;
4. its layout uses the Wathiq tokens, density, hierarchy, and action rules;
5. every asynchronous and permission-limited state is deliberate;
6. forms, relationships, dates, statuses, and errors use shared conventions;
7. no raw/default table or duplicate component pattern was introduced;
8. accessibility, responsive behavior, localization, and RTL are verified;
9. relevant automated tests pass;
10. live-browser comparison with the reference screen is recorded;
11. translation definitions were added, updated, or safely removed in the same
    change, protected translations were preserved, and catalogue completeness
    and stale-key checks pass; and
12. this document and its reference map are updated if the approved design
    system genuinely changed.

Recipient chip remove-icon spacing (4 October 2026): inspection of the shared
remote QSelect's default removable chip found its physical negative right
margin overlapping the Arabic label by 4.375px. NiceGUI Select's documented
`multiple`/`use-chips`/`dense` configuration controls selection or overall sizing,
not internal remove-icon spacing. Keeping the native chip preserves keyboard,
removal and disabled behavior; a custom selected-item slot is unnecessary.
The narrowly scoped remote-selector correction resets the icon margins and
adds a 6px logical trailing margin to multiple-chip content. The logical margin
belongs to content because Material icon elements force LTR direction even in
an RTL field. English/LTR and Arabic/RTL browser measurements confirmed a 6px
label/icon gap at desktop and 360px widths without chip overflow. No UI text,
translation artifact, data request, cache or database change was introduced.
The database-free preview was stopped and its temporary tab closed.
