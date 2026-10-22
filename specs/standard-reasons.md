# Standard Reasons — Enhancement Specification

**Status:** Draft — pending approval  
**Project:** ERMS / Wathiq  
**Prepared:** 22 October 2026  
**Revision:** 0.1

## 1. Purpose

Make Reasons fields easier to complete by offering administrator-maintained
standard reasons while continuing to accept any custom reason. Standard
reasons have translations for multiple supported application languages.

This document proposes a small enhancement. It does not change an approved
workflow until approved. The exact fields covered must be confirmed in section 7.

## 2. User experience

- **SR-01:** Each in-scope Reasons field offers a searchable dropdown of active
  standard reasons and retains an editable free-text reason.
- **SR-02:** Selecting an option populates the editable reason with its displayed
  wording. The user can amend, replace, or extend it, or type a custom reason
  without selecting an option. Selection is optional; no reason is preselected.
- **SR-03:** Existing required-field rules, length limits, validation, permissions,
  and submission behavior continue to apply to the final text. A standard reason
  does not grant permission or bypass any workflow requirement.
- **SR-04:** With no active options, users can still enter custom text. Failure
  to load suggestions must not prevent entry or submission of a valid reason.

## 3. Administration and settings

- **SR-05:** Provide **Standard reasons** within **Administration → Settings**,
  using the existing `app.settings.manage` privilege. Authorized administrators
  can add reasons, edit wording and translations, set display order, and activate
  or deactivate options. Deactivation is the removal mechanism.
- **SR-06:** Each option has a stable identifier, required nonblank English
  wording, optional translations keyed by supported language tag, display order,
  and active status. Identifiers remain stable when wording changes.
- **SR-07:** Use the shared database-managed application-settings registry,
  persistence, validation, audit, and concurrent-edit protection defined in
  [Application Configuration](application-configuration.md) and
  [Administration Settings](administration-settings.md). No parallel settings
  store, environment setting, or new privilege is introduced. Related edits
  are validated and saved atomically with the existing settings change reason.
- **SR-08:** Changes require no service restart and become available within the
  existing 30-second general-settings cache lifetime. Cache isolation follows
  the logical database and effective language; reads require only the user's
  existing access to the relevant Reasons field, not settings-management access.
  Saving settings invalidates the applicable local cache. Expired-cache read
  failures leave custom entry available. Later refreshes must not replace text
  already entered in an open form.

## 4. Languages and historical accuracy

- **SR-09:** Show options in the user's effective interface language. Follow
  [Internationalization and User Preferences, section 5](internationalization-and-user-preferences.md#5-language-resolution-and-fallback):
  exact language, then base language for a regional tag, then canonical English.
  Reject blank or whitespace-only translation values; an absent translation
  uses fallback. Administrators may maintain translations for multiple supported
  languages without a deployment.
- **SR-10:** Standard-reason wording is administrator-maintained settings data.
  UI labels and help text follow the existing UI translation and governed
  catalogue-artifact requirements. Do not create a separate language registry
  or automatically translate custom text.
- **SR-11:** Submit and preserve the final reason text through the existing
  action contract and history mechanism. Later edits, deactivation, language
  changes, or settings resets must not rewrite previously recorded reasons.
  No new action API field or historical reason-code relationship is required.

## 5. Initial defaults and upgrades

- **SR-12:** Populate the approved initial list for new installations and add
  missing defaults during an explicit upgrade, following the existing settings
  initialization conventions. Preserve administrator changes, translations,
  ordering, and deactivation choices. Startup must not recreate or overwrite
  customized defaults. Any seed-created event-history rows use source `seeding`.

The following is the initial candidate explicitly raised by the requester;
its inclusion remains subject to approval of this draft:

| English | Arabic |
| --- | --- |
| For testing purposes | لأغراض الاختبار |

Other candidates for discussion are **Created or submitted in error**
(تم الإنشاء أو التقديم عن طريق الخطأ), **Duplicate entry** (إدخال مكرر),
**Incorrect or incomplete information** (معلومات غير صحيحة أو غير مكتملة),
and **To correct an administrative error** (لتصحيح خطأ إداري).
These are suggestions, not approved defaults or a universal standard list.
Final wording and relevance depend on the actions covered.

## 6. Acceptance and verification

Implementation must record requirement-to-implementation-to-test evidence for
SR-01–SR-12. Verification must demonstrate:

| Requirements | Required evidence |
| --- | --- |
| SR-01–SR-04 | Select, search, edit, replace, and submit a reason; custom-only entry; unchanged validation; empty-list and load-failure behavior. |
| SR-05–SR-07 | Authorized maintenance and translations; unauthorized writes rejected; blank values rejected; atomic saves, concurrent-edit protection, and audit history. |
| SR-08 | Changes visible within 30 seconds without restart; repeated navigation and language isolation; no overwriting an open form's entered text. |
| SR-09–SR-10 | English, Arabic, and regional/base-language fallback; missing translations; applicable catalogue validation and provenance checks. |
| SR-11 | Existing action submission remains compatible; recorded reasons remain unchanged after settings edits and deactivation. |
| SR-12 | New-install and repeat-upgrade behavior; administrator customization and deactivation preserved. |

Live-browser verification must cover LTR and RTL, keyboard selection, custom
entry, and the settings editor. Follow `docs/webui-performance.md` for suggestion
loading, bounded server search where needed, cache behavior, and navigation.
Database-backed tests must use a uniquely named disposable database initialized
from the canonical schema or required migration path and dropped after the run.

## 7. Decisions required before implementation

1. Identify the exact Reasons fields/actions covered. This draft does not
   authorize replacing every reason field in the application.
2. Confirm whether those fields share one list or require lists scoped to
   particular actions. Action-specific lists need their scope recorded here.
3. Approve the initial English/Arabic defaults and their wording.

Approval of this draft must resolve these points before implementation begins.
