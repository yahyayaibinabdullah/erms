# Missing Arabic drafts on local-stack startup

Approved requirement: actual local-stack startup/restart imports missing Arabic
drafts from the checked-in catalogue while preserving every existing translation
and leaving review/publication to an administrator. Internationalization §7.5
and local-tooling document this launcher-only exception to explicit seeding.

`run-local-stack.sh` invokes the existing Arabic seed utility with
`--missing-only` after database readiness and endpoint preflight, before starting
MailDev or application workers. The API virtual environment, resolved exported
DATABASE_URL and project PYTHONPATH are used. No credential is added to this
command line. The utility synchronizes definitions first, so absent translations
become source-copy drafts and then receive the checked-in Arabic text. Failures
stop the launch and appear in the existing private stack log. API startup,
schema creation, migrations and production service startup do not seed Arabic.
No environment variable, migration, cache or service ownership rule was added.
An `up` against an already-ready stack remains a no-op; restart after pulling.

Verification on 27 October 2026:

- 17 isolated shell/controller tests passed, including exact missing-only
  invocation on the resolved target, stopping before owned services on failure,
  process supervision and cleanup. The initial sandboxed run could not open
  Bash /dev/fd logging pipes; the same tests passed with required process access.
- Three database-backed cases passed in a fresh disposable database: the actual
  CLI imported an absent Arabic row and left it unreviewed/unpublished, a second
  call was idempotent, and manual/imported/generated/reviewed drafts plus an
  existing published translation were preserved exactly. API startup still
  performs no Arabic seeding. An earlier added fixture omitted its required
  audit reason; that fixture was corrected before the successful run.
- All disposable databases, including the failed fixture run, were dropped.
- The authorized demo managed restart completed ready. Its hook reported
  stored=0, corrected=0, failed=0, awaiting_generation=0, protected=3880.
- Shell syntax, catalogue coverage/order, Arabic terminology, environment
  template synchronization and whitespace checks passed.

No UI message key or translation wording was added/changed/removed. The Arabic
artifact's specification hash was reconciled with the approved spec amendment;
all per-item wording and provenance were preserved. No administrator export was
promoted and no translation was published. Existing wording corrections remain
outside the missing-only workflow and still require review in each database.
