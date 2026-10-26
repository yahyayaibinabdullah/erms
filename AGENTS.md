# Project instructions

## Local stack lifecycle

- `./run-local-stack.sh` without a mode retains foreground/Ctrl-C operation;
  `up`, `down`, `status` and `restart` manage the recorded stack. See
  `docs/local-tooling.md` for ownership, health and timeout behavior.
- Stack logs and process state belong in gitignored `.runtime/local-stack/`.
  Preserve process identity checks and do not stop reused external services.

## Local email testing

- Use root `./run-maildev.py up|down|status|restart` for local MailDev testing;
  setup, TLS trust and runtime options are documented in
  `docs/local-tooling.md` under “Local MailDev with TLS and MCP”.
- `./run-local-stack.sh` starts/reuses MailDev automatically and stops only an
  instance it started. Keep the helper's lifecycle ownership checks intact.
- Keep certificates, keys, captured messages and logs in gitignored
  `.runtime/maildev/`. Never disable SMTP certificate validation or change
  persistent database settings merely to run a test. Never stop an unrelated
  MailDev process to free a port; use the launcher's port options instead.

## Specification fidelity

- An approved specification is the authoritative product contract. Implement
  exactly what it requires; do not invent privileges, entities, workflows,
  states, API contracts, UI behavior, or other product requirements that are
  not stated in the specification or separately requested and approved by the
  user.
- If implementation appears to require a product-level addition or departure
  from an approved specification, stop and obtain the user's explicit approval
  before making that change. Do not treat a technical shortcut, convention, or
  inferred preference as approval.
- Maintain requirement-to-implementation-to-test traceability for specified
  features. Do not declare a phase or feature complete while an approved
  requirement lacks implementation or verification evidence.

## Environment variable templates

- Every newly added environment variable must be documented in `.env.example`
  and every relevant service template in the same change. A code default does
  not replace template documentation. Apply the same reconciliation when
  renaming, changing the default of, or removing a setting.
- Check the API, WebUI and text-indexer templates according to the actual
  consumer: `.env.example.api`, `.env.example.text_indexer`,
  `backend/services/api/deploy/api.env.example`,
  `frontend/webui/deploy/webui.env.example`, and
  `backend/services/text_indexer/deploy/text-indexer.env.example`. Do not add
  another service's settings to a service-only template.
- `backend/services/api/deploy/api.env.example` is the authoritative API
  template. Edit it, then run `python3 tools/sync_api_env_template.py` to
  regenerate `.env.example.api`; never edit the generated copy directly.
  Run `python3 tools/sync_api_env_template.py --check` before handoff.
- Document each setting's purpose, default or required value, service ownership,
  and restart requirements. Keep intentional local/server default differences
  explicit. Use safe placeholders for credentials and machine-specific paths;
  never copy private `.env` values into tracked templates.
- Existing private environment values must be preserved. Local stack startup
  appends missing safe defaults through `tools/reconcile_local_env.py`; it does
  not update production environment files. Include deployment upgrade guidance
  when a new setting requires manual configuration, and report template changes
  and any operator action in the implementation handoff.

## Database-backed tests

- Never run a test suite against the development, staging, production, or any
  other persistent ERMS database.
- Before a database-backed test run, create a new uniquely named disposable
  PostgreSQL database dedicated to that run.
- Initialize the disposable database from the repository's canonical schema or
  the migration path required by the test.
- Point the complete test process, including fixtures, at that disposable
  database only.
- After the run finishes, whether it passes or fails, terminate remaining
  connections if necessary and drop the disposable database cleanly.
- Report database creation and cleanup failures; do not silently leave test
  databases behind.

## Canonical database SQL

- SQL files must contain portable PostgreSQL SQL only. Never put `psql`
  meta-commands such as `\\i`, `\\ir`, `\\set`, or `\\copy` in any `.sql` file.
- `database/schema.sql` is the complete, self-contained latest schema for a new
  empty database. It must never include, invoke, or otherwise depend on a
  migration file.
- A new empty database is initialized from `database/schema.sql` alone.
- Migration scripts exist only to upgrade an existing database containing
  data. Repeat required DDL in `schema.sql`; do not make the canonical schema
  execute migrations.
- Seed scripts are separate from schema creation and migrations. They must
  target the latest canonical schema, must not be invoked by `schema.sql`, and
  must not be disguised as migrations even when SQL must be repeated.
- Event-history rows created by seed scripts or seed utilities must use source
  `seeding`; source `migration` is reserved for actual database upgrades.

## WebUI layout and RTL troubleshooting

- Start layout and RTL troubleshooting with standard NiceGUI components,
  documented configuration, layout APIs, and supported direction settings.
  Explore and exhaust applicable NiceGUI solutions before using lower-level
  Quasar primitives or custom/bare CSS overrides.
- For tricky or persistent layout/RTL problems, use the in-app browser to
  reproduce and inspect the rendered UI before changing layout code. Inspect
  component structure, effective direction, computed styles, and dimensions;
  do not randomly change CSS to see whether it works.
- Base each fix on an observed cause. If a Quasar or CSS fallback is necessary,
  document the NiceGUI options investigated and why they cannot solve it, keep
  the fallback narrowly scoped, and verify the result in both LTR and RTL.
- Follow the detailed troubleshooting order in
  `docs/webui-design-language.md` section 19.1.

## Frontend table design

- Never introduce a raw or default-styled NiceGUI `ui.table`.
- Before adding or changing a table, inspect a comparable Wathiq table and
  reuse its established presentation and interaction pattern.
- User-facing tables must use Wathiq's standard light-blue headers, borders,
  spacing, typography, action treatment, filtering where relevant, sortable
  columns, pagination controls, and deliberate empty/loading/error states.
- UI table work is incomplete until its rendered appearance has been compared
  with existing Wathiq tables in a live browser.

## WebUI performance

- All work under `frontend/webui` and its supporting API routes must follow the
  normative `docs/webui-performance.md` contract.
- Do not reintroduce catalogue parsing on message-render paths, duplicate page
  requests, serial independent requests, destructive dashboard loading states,
  or optional assets on the initial authenticated critical path.
- Every new cache must define its scope, key, freshness policy, invalidation,
  failure behavior, and identity/language isolation.
- Performance-sensitive UI work is incomplete until repeated navigation,
  background-task abandonment, data freshness after mutation, and both LTR and
  RTL behavior have been verified.
- Never call `api.list(resource)` for a tenant-grown collection such as users,
  roles, organization units, classifications, aggregations, records, or holds.
  Use true server pagination or a bounded type-ahead selector. A client-side
  pagination control over a 100/500-row download is not pagination.
- Relationship controls must use bounded remote search, retain selected values,
  and fetch individual selected IDs when needed. Hierarchy views must page each
  branch independently; never download a complete hierarchy to calculate one
  row's inherited state.

## Translation artifacts during WebUI development

- Before adding, changing, or removing any user-visible WebUI text, read and
  follow sections 7.5 and 7.8.1–7.8.4 of
  `specs/internationalization-and-user-preferences.md`.
- Treat `frontend/webui/i18n/messages.ar.generated.json` as the canonical merge
  base. It may contain administrator-curated translations promoted through the
  Translation Administration export workflow; it is not disposable generated
  output.
- Merge by `message_key`. Preserve administrator-authored, imported, reviewed,
  and published wording and provenance. Generate only missing new keys or
  explicitly invalidated machine-generated values. Never regenerate the whole
  artifact over curated translations.
- Always provide generated Arabic drafts for untranslated active UI keys in
  the same change; do not leave English source copies for later translation.
  For the authorized local `demo` database, use the explicit Arabic seed utility
  with `--missing-only` to fill missing drafts after catalogue synchronization.
  Preserve all existing translations and leave drafts unpublished for review.
- Keep `frontend/webui/i18n/messages.en.json` sorted lexicographically by the
  complete contextual `message_key` after every catalogue edit. Reorder every
  maintained language artifact to that exact sequence without changing its
  text or provenance. Source discovery, insertion, database, and merge order are
  never valid catalogue ordering rules.
- Database-only administrator edits are invisible to source control until a
  complete export is deliberately promoted to the checked-in artifact. If a
  newer export is known to exist but is unavailable, stop artifact replacement
  and obtain it rather than overwriting those edits.
- UI work is incomplete until English and maintained-language active-key
  coverage agrees and placeholder, blank, terminology, stale-key, provenance,
  and artifact-hash checks pass. State the artifact/key changes and remaining
  review requirements in the implementation handoff.
