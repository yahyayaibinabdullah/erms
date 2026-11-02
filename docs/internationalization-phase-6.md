# Internationalization Phase 6 implementation contract

Phase 6 creates the governed best-effort Arabic bootstrap and human-review
workflow required by the approved internationalization specification.

## Generator boundary

The API exposes a bounded generation-input feed containing only Wathiq-owned
English source text, contextual grouping, semantic meaning, common locations,
translator guidance, grammatical role, named-placeholder metadata, and a
rendered example. It never includes users, records, credentials, audit content,
or other user data. The Arabic feed also supplies the approved Wathiq domain
terminology reference.

An approved generator returns contextual message keys and Arabic candidates.
Batch ingestion records the generator name, model, model version, and generation
time on every stored candidate. It validates nonblank text, template syntax,
named placeholders, and markup before writing. Invalid candidates are reported
per key and are not stored.

Translation Administration includes visible placeholder-contract guidance.
It explains that tokens such as `{count}` are complete dynamic values, may be
reordered for natural Arabic grammar, and must otherwise be preserved exactly.
Language-specific fragments—plural suffixes, capitalization instructions,
verb endings, punctuation pieces, and partial words—are prohibited as
placeholder contracts and must be corrected in the authoritative English
definition rather than forced on an administrator.

An absent translation or untouched English `source_copy` may be replaced. For
a non-source language, `source_copy` identifies an untranslated fallback and
cannot be published. Deliberately unchanged wording must first be saved as a
manual translation with a reason.
Manual, imported, previously generated, reviewed, or published translations
are otherwise protected. The artifact can declare an exact known defective
generated value as superseded; only that exact value may be staged as a
corrected unreviewed draft, while differing administrator text remains
protected. Every accepted result remains `origin = generated` and
`status = draft`, has no reviewer, and publishes nothing. A system administrator
may review and publish it individually or use **Review and Publish All**.

## Coverage and review

Selecting any supported-language card displays statistics for that language:
active keys, drafts, unreviewed drafts, reviewed translations, published
translations, unpublished translations, and translations needing quality
attention. The API retains the older generated-draft fields for compatibility,
but the administration summary is no longer restricted to Arabic or phrased as
though a background generator were running. Arabic-specific terminology
guidance remains applicable only when Arabic is selected. Drafts continue to
appear in the contextual, filterable editor with their origin, guidance,
semantic meaning, placeholders, review control, and publication gate.

## Draft review, publication, and export

The administrator workflow follows one rule: **any valid draft may be
published**. A valid draft is not blank, preserves the message's named
placeholders, uses valid template syntax, and contains no disallowed markup.

- **Source copy**, **generated**, **imported**, and **manual** say where the
  draft came from. They help with filtering and audit history. They do not
  grant or remove permission to publish it.
- Publishing is the administrator's review decision. An individual Publish
  action records that administrator as both reviewer and publisher.
- The supported-language cards are the language selector for administration.
  The selected card controls the listing, editing, export, and **Review and
  Publish All**. The lower controls filter keys only; they contain no language
  selector. Export and bulk publication show the chosen language but do not
  ask for it again.
- A bulk action inside a visible language or context group uses that visible
  scope. It is all-or-nothing: if one selected draft is invalid, none of the
  selected drafts are published.
- Export never changes database state. An import file declares its own
  language; Wathiq displays and validates that value instead of using the
  currently selected card. Import saves valid values as drafts and never
  publishes them automatically.

English export uses the English definition when no published English revision
exists. If an administrator has published revised English wording, that wording
is exported instead. When **Use reviewed drafts when newer than the published
text** is selected, a newer reviewed but unpublished English draft may be used.
For other languages, export uses published text by default and the same option
may include newer reviewed drafts.

## Generated Arabic bootstrap

The approved generator is OpenAI Codex using GPT-5.6 Sol Light and prompt
profile `wathiq-arabic-bootstrap-v2-contextual`. The checked-in generated artifact covers
all current contextual English definitions. It retains UTC generation time,
batch ID, model identity, and SHA-256 hashes of the approved specification,
English catalogue, and terminology reference. The explicit seed utility
`database/seeds/004_seed_generated_arabic_ui_translations.py` stores the
artifact over untouched Arabic source-copy rows, using audit source `seeding`;
it is repeatable and protects administrator work. Exact values declared
superseded are staged as corrected drafts through the same audited path. API
startup does not apply or reapply generated drafts.

For routine WebUI development, always supply Arabic drafts for untranslated
active keys alongside their English definitions. Run the explicit seed utility
with `--missing-only` against the authorized target to fill untouched source-copy
drafts while preserving every existing translation, including values previously
declared superseded. This mode is repeatable and does not publish translations.
Generation and seeding remain explicit development/deployment steps, rather than
API-startup side effects.

Every named-placeholder set matches its English definition. No generated draft
is reviewed or published. The corrected generation pass translates complete
messages in context into Modern Standard Arabic; it does not perform word-by-word
replacement. Independent validation rejects blanks, placeholder
mismatches, unexplained English prose, duplicate or missing keys, and malformed
quality flags. Every artifact entry must pass the mandatory automated validity
checks with no unresolved generation flags. Generated drafts remain visibly
identified by their origin and require a system administrator's explicit
Publish or Review and Publish All action before publication.

## Continuing Agentic-AI maintenance

> **Required before any future WebUI catalogue change:** read the current
> checked-in artifact first. It may contain administrator-curated wording
> promoted from Translation Administration. Merge by `message_key`; never
> regenerate the file wholesale or overwrite curated values.

`frontend/webui/i18n/messages.ar.generated.json` is the source-controlled
generated Arabic draft catalogue consumed by the seed utility. It is not a
published runtime catalogue. Whenever Agentic AI develops or changes WebUI
functionality, the same implementation change maintains both the authoritative
English definitions and this generated Arabic draft catalogue.

The agent adds contextual Arabic drafts for new keys, regenerates entries whose
English meaning or placeholder contract materially changes, and removes entries
whose definitions are safely removed. Deprecation remains aligned across both
catalogues when compatibility requires retaining a key. Each regeneration
refreshes model/prompt provenance, generation time, batch ID, and source hashes,
then runs exact-key coverage, placeholder, blank, unexplained-English,
terminology, stale-entry, and idiomatic-quality checks.

The seed program is generic and is not edited for individual keys. It applies
the complete current file explicitly to the selected database and replaces
absent or untouched `source_copy` rows. It also recognizes the artifact's
declarative superseded-value map: an exact known defective generated value can
be staged as a corrected draft, including when that value had been published.
Review and publication state is cleared so all corrections can use the bulk
review action. Differing administrator-authored or imported text remains
protected. A changed source otherwise follows the governed reconciliation
workflow rather than silent reseeding.

## Administrator artifact round trip

Translation Administration can export a complete, placeholder-safe copy of a
selected language catalogue. Published text is used by default; a deliberate
option may use newer reviewed drafts. The download is seed-compatible, records
catalogue and per-item provenance, and does not modify the checked-in file.
Manual wording is marked `manual_admin_export` rather than machine-generated.

The adjacent import action accepts one complete JSON artifact. The file declares
its language tag, English and native names, direction, and formatting settings.
Wathiq displays and validates that language plus every active key and
placeholder before writing, and presents importable, protected, unchanged,
missing, and invalid counts. If the language is new, a successful import creates
it and immediately refreshes Translation Administration so its card appears.
Import requires an audit reason and stores accepted values as unreviewed
`imported` drafts. It never overwrites an
existing manual, imported, reviewed, or published value and never publishes
automatically. Any valid draft is eligible for the atomic bulk
review-and-publication action, regardless of its origin.

### Canonical promotion and subsequent agent merge

The administrative database and the repository do not synchronize
bidirectionally by magic. Database edits become available to future development
only when an administrator exports the complete language artifact and that file
is deliberately promoted to the repository. For Arabic it must replace
`frontend/webui/i18n/messages.ar.generated.json`, pass all artifact validators,
and be committed. Until then, the export is only a download and the edits remain
database-local.

After promotion, the checked-in file is the merge base for all later Agentic-AI
work. The agent preserves administrator/imported/reviewed/published values and
their provenance, adds and generates only missing new keys, refreshes metadata
for changed definitions, marks preserved translations for review when meaning
changes, rejects placeholder incompatibility, and removes only safely removed
keys. Exact corrected machine values may use `superseded_translations`; this is
not permission to replace arbitrary administrator text. Full-file regeneration
over a promoted artifact is prohibited.

Before handoff the agent must report key additions, changes, removals, review
requirements, and whether a database export was promoted. If a newer database-
only administrator version is known to exist but no export is available, the
agent must stop artifact replacement and obtain a fresh export rather than lose
those corrections.

## Verification evidence

- the terminology synchronization test compares the implementation directly
  with section 21.1 of the approved specification;
- artifact validation proves complete unique-key coverage and exact placeholder
  parity;
- protected-seeding tests prove that manual and reviewed values survive;
- batch tests cover provenance, invalid placeholders, failure reporting,
  review and publication, and coverage reporting;
- all 324 API/database tests pass against the repository runner's isolated,
  disposable PostgreSQL databases, which are removed after the run;
- all 214 WebUI tests, catalogue completeness, Python compilation, JSON
  validation, and `git diff --check` pass;
- the corrected artifact contains no blank values, duplicate or missing keys,
  placeholder mismatches, unexplained English prose, or unresolved automated
  quality flags.
