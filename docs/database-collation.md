# PostgreSQL collation for Arabic and English

## Recommended database default

For Wathiq deployments where Arabic is primary and English is also supported,
use **UTF-8, the ICU provider and locale `ar`** as the recommended database
default. ICU `ar` applies Arabic sorting conventions and still handles English
and other Unicode text. Choosing it does not change the UI's default language,
user language preferences, RTL layout, translations or stored text.

| Choice | Behavior | Wathiq recommendation |
| --- | --- | --- |
| `libc` with an OS locale such as `en_US.UTF-8` | Uses the operating system's collation rules; the same locale name can behave differently on macOS and Linux. | Preserve for an existing installation until a deliberate rebuild is approved; do not use it as the preferred default for a new Arabic-primary deployment. |
| ICU `ar` | Uses Arabic-specific Unicode collation rules, including treatment of hamza forms and vowel marks. | Preferred default for Arabic-primary, Arabic/English deployments. |
| ICU `und` | Uses the language-neutral root collation as a shared starting point. | Appropriate when a deployment deliberately wants a neutral multilingual default rather than Arabic tailoring. |

ICU improves consistency between operating systems when the same ICU/CLDR
version and settings are used. Its results can change with library/data
versions; it is not a promise of identical ordering across all future upgrades.
Both providers support Arabic storage when the database encoding is UTF-8.
See [PostgreSQL locale providers](https://www.postgresql.org/docs/18/locale.html)
and [ICU locale tailoring](https://unicode-org.github.io/icu/userguide/collation/customization/).

## Measured examples

These ascending-order examples were checked with read-only queries on
28 October 2026 using PostgreSQL 18.4 on macOS/Postgres.app:

- `demo`: provider `libc`, locale `en_US.UTF-8`.
- `demo4`: provider `icu`, ICU locale `ar`, recorded collation version
  `153.128.47`.

They describe the measured environment, not every libc implementation or ICU
version. Each row compares the same input values using default `ORDER BY`.

| Example | `demo`: libc | `demo4`: ICU `ar` |
| --- | --- | --- |
| Arabic names | First **أحمد**, then **أسامة**, then **إبراهيم** | First **إبراهيم**, then **أحمد**, then **أسامة** |
| Vowel marks | `علم` → `عماد` → `عَلَم` | `علم` → `عَلَم` → `عماد` |
| Arabic/Western digits | `ملف ١` → `ملف ٢` → `ملف 1` → `ملف 2` | `ملف 1` → `ملف ١` → `ملف 2` → `ملف ٢` |

The marked form `عَلَم` remains near `علم` under ICU `ar`, ahead of `عماد`.
The Arabic rules give vowel marks a later comparison weight than base letters.
The provider does not simply remove those characters. The
[Unicode Arabic collation rules](https://github.com/unicode-org/cldr/blob/main/common/collation/ar.xml)
describe the language tailoring.

Reproduce the examples separately in each database without modifying rows:

```sql
BEGIN READ ONLY;
WITH samples(example, value) AS (
    VALUES
        ('names', 'أحمد'), ('names', 'أسامة'), ('names', 'إبراهيم'),
        ('vowels', 'علم'), ('vowels', 'عماد'), ('vowels', 'عَلَم'),
        ('digits', 'ملف ١'), ('digits', 'ملف ٢'),
        ('digits', 'ملف 1'), ('digits', 'ملف 2')
)
SELECT example, array_agg(value ORDER BY value) AS ascending_order
FROM samples
GROUP BY example
ORDER BY example COLLATE "C";
ROLLBACK;
```

### Sorting, equality and numeric order

The default database comparison is deterministic. In both measured databases,
`علم = عِلْم` and `Apple = apple` are false: sorting related forms close together
does not make them identical. Arabic search normalization, accent/case
insensitivity and nondeterministic equality are separate decisions; this
recommendation enables none of them. See
[PostgreSQL comparison determinism](https://www.postgresql.org/docs/18/sql-createcollation.html).

ICU `ar` alone does not enable natural numeric ordering. Both defaults sorted
`File 1`, `File 10`, `File 2`. Natural ordering requires an explicit numeric
collation option. Wathiq's existing `erms_code_natural` collation uses
`und-u-kn` for its supported code-ordering paths; the database default does not
replace that collation or the explicit `C` ordering used by portable exports.

Per-column or per-query `COLLATE` takes precedence over the database default.
User-facing lists must retain the internationalization specification's ordering
by effective localized value, approved locale collation and stable code/ID
tie-breakers. English-facing ordering can use an approved English collation.
The examples therefore do not promise that every screen has the same ordering.

## Provisioning and checking a database

Use PostgreSQL 18 with ICU support. Connect to a maintenance database such as
`postgres`, outside a transaction, and choose the intended database name and
owner according to deployment policy:

```sql
CREATE DATABASE erms
    WITH TEMPLATE template0
         ENCODING 'UTF8'
         LOCALE_PROVIDER icu
         ICU_LOCALE 'ar';
```

Then load the canonical schema and the separate initialization files in the
order described in [database setup](../database/README.md). Database creation
is external to `database/schema.sql`; applying that file does not select or
change the database's default provider. Explicit options prevent an accidental
inheritance of `libc`, ICU `en-US` or another server-template default.
See [PostgreSQL CREATE DATABASE](https://www.postgresql.org/docs/18/sql-createdatabase.html).

Verify the actual database, rather than inferring its provider from an OS-style
locale label:

```sql
SELECT datname,
       pg_encoding_to_char(encoding) AS encoding,
       datlocprovider,
       datlocale,
       datcollate,
       datctype,
       datcollversion
FROM pg_database
WHERE datname = current_database();
```

The recommended result includes `encoding = UTF8`, `datlocprovider = i` and
`datlocale = ar`. `datcollate`/`datctype` can still show an OS locale such as
`en_US.UTF-8` while ICU `ar` is active; those fields alone do not establish the
provider. Record the collation version with deployment verification evidence.

The existing local launcher/bootstrap initializes schema/data, but does not
force this database locale. Provision a database explicitly before connecting
the stack, or perform a controlled rebuild if a newly created local database
inherited different defaults. Existing databases/volumes are not converted by
pulling code, loading the schema or restarting the application. No new `.env`
variable or editable application setting is introduced by this recommendation.

## Restores, rebuilds and upgrades

An ordinary clone should preserve its source provider and locale. Moving from
libc to ICU `ar` is an intentional exception: back up the source and any target
being replaced, create a fresh target explicitly with ICU `ar`, apply the latest
schema and restore data without overwriting the new database definition.
The default provider/locale is not changed in place with `ALTER DATABASE SET`.

Compare logical schema definitions and every table's rows and sequence states
against the same saved backup snapshot. A live source continues updating worker
heartbeats, credential-use timestamps and gateway health after backup; those
updates are not schema drift or restore data loss. The locale, sorting behavior,
internal object IDs, storage layout and statistics need not match the source.
Keep the approved locale difference explicit in the verification report.

`tools/verify_canonical_schema.py --reference-archive ...` preserves the backup's
locale in its disposable comparison databases; it is a schema/data parity gate,
not a locale-conversion command. For a deliberate conversion, also verify the
target's ICU `ar` metadata and Arabic/English sorting and run API regressions in
a separate disposable ICU `ar` database. Read-only checks can verify the retained
target; mutable test fixtures must never run on it. See the
[canonical baseline verification guide](database-canonical-baseline.md).

Before OS, PostgreSQL or ICU upgrades, record relevant versions and check
collation-version warnings. Rebuild affected dependent objects, including indexes
whose ordering depends on those collations, then verify results before refreshing
recorded version metadata.
`ALTER COLLATION ... REFRESH VERSION` and
`ALTER DATABASE ... REFRESH COLLATION VERSION` only acknowledge the new version;
they do not rebuild indexes or switch providers. Follow
[PostgreSQL's collation upgrade procedure](https://www.postgresql.org/docs/18/sql-altercollation.html).
