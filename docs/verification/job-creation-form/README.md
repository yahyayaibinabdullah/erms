# Disposition job creation corrections

Verified 21 October 2026. Destruction Process sections 2.1 and 5.5 require the
Officer profile for Standard/Simplified preparation and the Manager profile for
Records Manager Only. The context projection now supplies the current configured
route, and the form uses it to select the eligible creation roles and job types.
Database authorization remains authoritative at submission.

The creation form automatically uses its sole eligible acting role; it displays
the existing role selector when several are eligible. Changing job type refreshes
the choices, retains a still-valid selection, and replaces an ineligible selection.
Audit attribution is preserved. Other command dialogs retain their existing role
selection behavior. No new text, translation keys, environment settings, database
migrations or persistent demo configuration changes were needed.

Verification:

- 67 focused WebUI tests passed, covering all three routes, Officer/Manager
  restrictions, English/Arabic, automatic selection, and changing job types.
- 11 API projection tests passed in a newly created disposable canonical-schema
  database, which was dropped by the runner.
- A separate disposable browser fixture verified Manager Only creation in English
  and the Arabic RTL profile. Destruction was available and the single-role
  selector absent. A browser submission created `FORM-FIX-PREVIEW` with
  `records_manager_only`, `manager_preparation`, and an `INFO_GOV_MGR` acting role
  in the command receipt. The preview database was dropped after verification.
- Screenshots: [English](manager-only.png), [Arabic profile](manager-only-arabic.png).
  Unpublished Arabic disposition labels retain the preview's existing English
  fallback; no translation artifact was replaced.
