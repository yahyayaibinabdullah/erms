# Automatic disposition/destruction role attribution

Approved requirement: remove acting-role fields used only for authorization and
attribution. Preserve real assigned-person and destination-role-queue choices.
Contract: disposition.md §15 and destruction-process.md, Automatic acting-role
attribution.

Implementation uses `disposition/acting_role.py` on each existing API-projected
operation-specific eligible-role list. Lowest role ID makes the choice stable
across ordering and language. It is internal data, never a hidden form control.
Current role/task/resource SQL authorization is unchanged. Exact command retries
remain bound to the same role and UUID. No fallback retry with a different role
or privilege merging is introduced, and no new requests or caches are added.

| Surface | Role source | Preserved business input |
| --- | --- | --- |
| Job creation, assignment, ownership, membership, acceleration, recovery | Existing management context for the action | Person, owner, roots, reasons and confirmations |
| Task review, external decision, execution, certificate retry | Task-eligible workspace roles | Proposals, evidence, decisions and confirmations |
| Task claiming | Task-eligible roles only | Claim confirmation/reason |
| Task release and handover | Eligible task/management roles | Destination person or role queue |
| Evidence correction | Correction roles returned with the document page | File, destination and reason |
| Template revision | Template-authorized roles | DOCX and revision reason |
| Request/report generation and retry | Action-specific Officer/Manager roles | Action confirmation |
| Email | Roles explicitly allowed for that document | Recipient preview and send action |

Verification, 23 October 2026:
- 244 disposition WebUI tests passed, including English and Arabic fixtures,
  multiple eligible roles, stable automatic attribution, no acting-role controls,
  exact retry identities, and preserved task destination choices.
- Five API regressions passed on a newly created disposable PostgreSQL database:
  assignment/admission, independent Officer/Manager authority, evidence correction
  with current-role rechecks, template-upload attribution/current assignments,
  and request/external-decision role gates. Database cleanup completed.
- In-app browser inspected actual NiceGUI assignment, template-upload, task and
  handover components. English/Arabic assignment now contains Assigned person
  and Change reason only. Arabic task forms show no acting-role selector.
- Existing history columns retain the acting role. No new user-visible text or
  catalogue definition is introduced. English/Arabic artifacts and provenance
  remain untouched; catalogue reference checks passed.
- Python compilation, diff whitespace and API environment-template sync passed.

No database migration, API contract, privilege, environment setting or persistent
demo data change is required. Restart the WebUI to activate the change.
