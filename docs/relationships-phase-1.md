# Record and Aggregation Relationships Phase 1

Phase 1 implements the standalone relationship foundation defined in
[the approved specification](../specs/record-and-aggregation-relationships.md#9-implementation-phases).
Relationship screens and live-browser verification belong to phase 2.
Disposition blockers, job review, and retained disposition links belong to the
future disposition implementation.

## Implementation

`database/schema.sql` contains the complete fresh-install schema. Migration
`049_resource_relationships.sql` upgrades an existing database. Both install
separate aggregation and record link tables, relationship types with stable
codes, type deactivation, multilingual label storage, versioned catalogue edits,
privileges, and event-history triggers. The schema does not invoke a migration or seed. The separate
`database/seeds/relationship-types.sql` installs the eleven approved types with
English and Arabic labels, records source `seeding`, and preserves existing
entries on rerun.

One row represents both directions. Symmetric endpoints are normalized before
insertion, and a unique constraint prevents concurrent reverse duplicates.
Directional reverse creation resolves to the same stored direction. Self-links,
cross-kind types, and mutation of link identity are rejected. Different types
between the same endpoints are supported; no transitive links are generated.
Type identity and symmetry are immutable, and an in-use type cannot be deleted.
Deactivated types remain readable and removable but cannot create new links.

The database checks `relationships.link` and existing view authorization on
both endpoints for explicit linking/unlinking. It does not require metadata
modification privileges or ACL permissions. Catalogue mutation requires
`relationships.administer`. Ordinary authorized resource deletion cascades its
links without requiring separate link authority and records the removals in
immutable event history, following the user's approved deletion decision.

Linked targets that become inaccessible are returned as redacted objects with
no identifier, number, or title. They are excluded from target search and cannot
authorize unlinking. Relationship audit states and reasons are also redacted
when either endpoint is inaccessible. Audit retention does not grant access to
a deleted or otherwise inaccessible endpoint.

## API

All routes are under `/api/v1/relationships` and require authentication. `kind`
is `aggregation` or `record`; it does not permit cross-kind links.

| Route | Behavior |
| --- | --- |
| `GET /types/{kind}` | Paged catalogue; active-only by default; bounded multilingual search; language-tag display fallback |
| `GET /types/{kind}/{type_id}` | Fetch a selected type, including a deactivated type |
| `POST /types/{kind}` | Create a type with canonical English names and language-keyed translations; Arabic required |
| `PATCH /types/{kind}/{type_id}` | Edit labels, individual language translations or active status with `If-Match`; preserve immutable code/kind/symmetry |
| `DELETE /types/{kind}/{type_id}` | Delete an unused type with `If-Match` |
| `GET /{kind}/{resource_id}` | Paged links with localized directional names, type filtering, sorting, and redacted targets |
| `GET /{kind}/{resource_id}/targets` | Bounded remote search or hydration of an individually selected visible ID |
| `POST /{kind}/{resource_id}` | Create a forward or reverse link |
| `DELETE /{kind}/{resource_id}/{link_id}` | Remove the link from either endpoint |

Catalogue and link pages return `items`, `total`, `limit`, and `offset`.
Catalogue/link pages are capped at 100; target search is capped at 50.
No relationship cache is introduced; each request evaluates current access and
reads current rows. The operation-policy registry documents these routes.

## Verification and traceability

The database/API regressions are in
`backend/services/api/tests/test_resource_relationships.py`.

| Requirement | Phase 1 evidence and remaining scope |
| --- | --- |
| REL-01 | Aggregation and record APIs work independently; invalid kinds and cross-kind types are rejected |
| REL-02 | Self-link and duplicate rejection, named reverse directions, different types, no transitive link, removal from either endpoint, and concurrent opposite-endpoint writes |
| REL-03 | Seeded separate catalogues, bilingual labels, create/edit/deactivate/delete, stale-version rejection, immutable identity, and in-use deletion rejection; administration UI remains phase 2 |
| REL-04 | Relationship insertion does not change containment; view-only linking succeeds without metadata modification authority |
| REL-05 | API returns named reverse links; live navigation remains phase 2 |
| REL-06 | Access revocation redacts the target and audit states; target search and unlinking reject inaccessible targets; UI remains phase 2 |
| REL-07 | Global linking authority plus view-only ACL access; missing privilege and catalogue/link privilege separation; direct SQL enforcement; UI remains phase 2 |
| REL-09 | Attributed create/delete events and cascade-removal evidence; disposition review reasons remain deferred |
| REL-10 | Server pagination, filtering, bounded search, selected-ID hydration, literal wildcard escaping; UI freshness and navigation remain phase 2 |
| REL-12 | Eleven seeded types have Arabic labels; fourteen new contextual keys cover privilege names/descriptions and relationship API errors; browser presentation remains phase 2 |
| REL-08, REL-11, REL-13 | Deferred to disposition implementation |

Verified fresh-schema relationship tests, the upgrade migration from baseline
`cc23b60017915309e318adad45b3bd0ae1ab0b60`, and neighboring privilege,
localization, favourites, and entity-translation API regressions. Each run used
a unique disposable PostgreSQL database, initialized through the appropriate
schema path and dropped after the run. No persistent ERMS database was used
for tests or upgraded.

Run the fresh-install regressions with:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py backend/services/api/tests/test_resource_relationships.py
```

For an upgrade check, the runner accepts `--baseline-ref=<pre-049-commit>` and
`--migration=database/migrations/049_resource_relationships.sql` before the
test targets. These options initialize only the newly created disposable
database; they never upgrade the configured persistent database.

## Localization validation

Merged only fourteen new keys into `messages.en.json` and the canonical
`messages.ar.generated.json`; all 2,965 existing Arabic entries and their
provenance are unchanged. Exact key coverage, canonical ordering, nonblank
values, placeholder contracts, new-key terminology, stale-key references, and
the English-artifact hash pass. New Arabic values are generated drafts requiring
human review; no new administrator export was promoted or claimed.

The repository-wide terminology checker still reports eleven existing
violations. Comparing against the baseline proves the set is unchanged and
none belongs to a new relationship key. Curated administrator translations
were preserved. This repository-wide validation limitation remains outstanding;
phase 2 must include Arabic review and browser verification.

On 8 October 2026, the user resolved that terminology baseline: corrected the
checker's vital-record spelling, approved **مجموع التحقق** and **قاعدة الحفظ**
for the two affected catalogue entries, and retained **المِلفّات الحاوية** with
diacritics. The checker now ignores Arabic diacritics during comparison. The
full terminology check passes. The two wording corrections retain previous
provenance and exact superseded values for guarded runtime synchronization.

## Deployment

Apply migration 049 through the normal database upgrade process, then run
`database/seeds/relationship-types.sql` separately before starting the updated
API. For an empty database, initialize from `database/schema.sql` and then run
the same seed separately. Restart the API and reload/restart any WebUI process serving
the changed translation manifest. Run
`database/seeds/004_seed_generated_arabic_ui_translations.py` with `DATABASE_URL`
set to each upgraded database, then review and publish the new Arabic drafts
through Translation Administration. Startup definition synchronization alone
creates English source placeholders; it does not seed the generated Arabic
artifact. The explicit Arabic seeder preserves protected translations.

Both privileges are explicitly granted to `ALL_PRIVS`, `INFO_GOV_OFFICER`, and
`INFO_GOV_MGR`. `SYS_ADMIN` gains neither privilege. There is no built-in
ordinary business-user profile to update: operators grant `relationships.link`
to the intended existing custom profiles through normal profile administration.
No new resource ACL permission or per-resource setup is required. No environment
variable or environment template changed; API template synchronization checks
pass.
