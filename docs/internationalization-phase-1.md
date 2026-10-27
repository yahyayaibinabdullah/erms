# Internationalization Phase 1 implementation contract

This document records the implemented foundation for the approved
`specs/internationalization-and-user-preferences.md`. The approved specification
remains authoritative; this is an implementation map, not a replacement.

## Configuration and bootstrap

`DEFAULT_WORKING_TIMEZONE` is required by the API and is validated as an IANA
timezone during startup. Deployment examples set it to `Asia/Dubai`; application
code and database seeds do not supply a fallback. The authenticated
`GET /api/v1/i18n/bootstrap` response supplies the effective language,
direction, working timezone, enabled-language metadata and formatting settings,
catalogue revision, and the checked-in English source messages needed at initial
render. It is privately cacheable for 60 seconds and varies by authentication.

## Preferences

`GET /api/v1/preferences` returns either the persisted preference or a synthesized
effective value. An unset preference uses the enabled registry default (initially
English) and the configured default working timezone. `PUT /api/v1/preferences`
requires `If-Match`; version `0` means that no preference row exists. Updates are
row-scoped, audited, and reject stale writes. Only enabled language tags and
canonical IANA timezone identifiers are accepted.

## Date and time boundaries

- PostgreSQL connections explicitly use UTC. Instants remain `timestamptz` and
  calendar values remain `date`.
- API resources continue to carry offset-bearing instants. The preference API
  carries an IANA timezone identifier, never a fixed UTC offset.
- `frontend.webui.locale_services` converts aware instants for display and
  converts offset-free wall input using the selected working timezone. It rejects
  daylight-saving gaps and ambiguous wall times instead of using the host zone.
- Browser components must consume bootstrap language, direction, and timezone;
  the device zone is not authoritative. Phase 3 applies these values to the
  document root and remediates individual components.

## Contextual English source inventory

`frontend/webui/i18n/messages.en.json` is the authoritative checked-in manifest
for converted keys. Every definition carries context, semantic meaning, common
locations, translator guidance, grammatical role, parameter schema, and a
rendered example. The complete manifest is always serialized in ascending
lexicographic `message_key` order. Every maintained language artifact and
Translation Administration export must use exactly the same sequence.
`check_i18n_catalogue.py` rejects unsorted manifests, language-artifact ordering
drift, unknown/stale references, and invalid placeholder contracts.
`extract_english_messages.py` inventories legacy
literal UI calls with source and code context for the Phase 2 conversion:

```bash
python frontend/webui/scripts/extract_english_messages.py
python frontend/webui/scripts/check_i18n_catalogue.py
```

Named placeholders use `{name}` and literal braces use `{{` and `}}`. The shared
renderer requires exact parameter names, HTML-escapes each value, and wraps each
interpolated value in Unicode bidirectional isolation marks.

## Authorization

The reserved person-only global privilege is `localization.administer`. It is
seeded only to `SYS_ADMIN` and `ALL_PRIVS`. The seven approved entity rights are
`classification_scheme.modify_metadata`, `classification.modify_metadata`,
`identity.users.administer` for users, `role.modify_metadata`, `org_unit.modify_metadata`, and
`security_level.modify_metadata`, and `profile.modify_metadata`. They are present in the protected `ALL_PRIVS`
compatibility profile. Users deliberately reuse ordinary user administration;
the other entity metadata rights remain independently assignable through the
normal authorization model. Aggregations and Records have no multilingual metadata privilege or
storage.
