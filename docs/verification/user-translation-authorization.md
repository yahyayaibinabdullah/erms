# Unified user translation authorization

Approved change: users' localized names and descriptions use
`identity.users.administer`, exactly like ordinary user administration. The
separate `user.modify_metadata` privilege is retired. The entity endpoint,
editor capability check, policy generator/registry, privilege seed and latest
canonical schema agree. Historical migration 019 remains intact for upgrade
reproducibility; migration 090 removes the old memberships/dependencies/privilege
and deprecates its two message definitions, retaining their audit history and
translations. No former metadata-only holder receives user administration.
Other entity metadata permissions and UI catalogue administration are unchanged.

The editor disables translation fields until their selected-language baseline
loads successfully. Background load errors now restore the editor client
context, display the translated API error and leave fields disabled, rather
than swallowing a 403 and later blaming language selection. Abandoned or stale
loads do not show a notification. No user-visible message keys were added.
Two privilege-label keys were removed from active English/Arabic catalogues;
Arabic wording/provenance is preserved in deprecated_items. The existing 75
Job/Task drafts are preserved and remain unpublished pending approval.

The fresh-schema authorization/entity/profile run passed 30 cases and exposed
one fixture error: a synthetic legacy privilege omitted its required description.
The fixture was corrected without changing the implementation. Frontend tests
passed four cases, including English/Arabic failure presentation and user-admin
capability checks. Catalogue reference/order/coverage, terminology and whitespace
checks passed. Database-backed suites run only in uniquely named disposable
databases, with cleanup recorded by the runner.

Final upgrade verification from HEAD through migrations 087–090 passed 16
cases, including the corrected retirement test, allowed/denied real translation
requests, stale-write protection, canonical-field preservation, idempotent
retirement/history retention and the complete operation-policy inventory.
Both failed and successful disposable runs reported database cleanup. The
inventory generator also now classifies two already implemented disposition
routes (approval summary and removal candidates) under their existing scoped
policy so regeneration remains complete; their authorization did not change.

Migration 090 was applied to local demo and the managed stack restarted ready.
A read-only effective-policy check confirmed Fathiya's existing user-admin
right authorizes Nour's localized metadata endpoint. No user name was changed.
All 75 Job/Task proposals remain unreviewed drafts; the missing-only seed added
or corrected zero entries. Active-key/placeholder/markup and artifact hash checks
passed across all 3,880 remaining active keys. No administrator export was
promoted and no translation was published. Deployments must apply migration
090; pulling catalogues/restarting alone does not replace protected database
translations, as documented in local-tooling.
