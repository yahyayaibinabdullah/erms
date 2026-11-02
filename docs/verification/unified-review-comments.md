# Unified destruction review comments

Approved requirement: replace Review notes, Overall job reason and internal
Decision reason editors with one Review comments field. Contract:
`destruction-process.md` §§5.3 and 6.6, including Save work without submitting.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| One editable field in preparation/correction/review | ReviewForm.comments; existing API transport/storage fields receive the same text | English/Arabic task tests and live NiceGUI browser preview |
| Blank draft saves/routine approvals allowed | Context-specific perform validation | All-three-route draft tests and routine review test |
| Submission/resubmission, rejection and Manager Only approval require comments | UI validation and existing submit/approval gates; stricter decide service and SQL | Required-comment tests, marked-removal rejection API/SQL test, existing three-route approval regressions |
| Comments retained with decision | Existing note author/task/round attribution; new Manager decision trigger uses that actor's task comments | Three-route approval attribution test |
| Preserve legacy content/history | Distinct editable legacy reason and note texts merge in the editor; explicit actions alone save; migration has no history DML | Clean-editor/no-write test; occupied HEAD schema upgraded with 082, full note/round/decision/event snapshots unchanged |
| Preserve concurrency and retries | Existing note/task/job versions and exact command signatures retained | Task regression suite, stale-save and retry cases; API review/approval suite |

Results on 23 October 2026: 262 disposition WebUI tests, 65 review/approval API
regressions, and one occupied-database migration test passed. Both disposable
PostgreSQL databases were dropped. Browser preview confirmed one field, required
feedback/focus, and native English/Arabic layout; Arabic workspace direction and
field label alignment were inspected after the existing direction script ran.
No layout overrides were added.

Catalogue: four new keys (review_comments, review_comments_hint,
review_comments_required, submission_comments) and updated generated prepare_hint.
All use disposition.ui context. English is lexicographically ordered and Arabic
has identical key sequence/hash coverage. The Arabic entries remain review drafts.
All other existing Arabic wording and provenance were verified unchanged; the
old generated preparation hint is retained in superseded_translations. No
administrator export was promoted, database-only translations overwritten, or
translations published. Catalogue reference, new/changed draft, compilation,
environment-template synchronization and whitespace checks passed.

Deploy migration 082 after 081, then restart API/WebUI. Fresh databases use
schema.sql alone. No new privilege, environment variable or API contract is
introduced.

Deployment verification on 23 October 2026: applied the pending migration 081
and migration 082 to `demo` atomically. Both migration registrations and the
enabled review-comments trigger were verified. Row counts and SHA-256 snapshots
of existing templates, review notes, rounds, decisions and all 114,755 audit
events matched before and after the migration. The managed local stack was restarted; API, WebUI, all managed workers and
MailDev passed the launcher health checks. No translations were published.
Operational evidence is retained locally in
`.runtime/review-comments-deployment/migration-result.json`.
