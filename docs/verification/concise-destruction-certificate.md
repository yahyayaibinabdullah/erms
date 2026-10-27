# Concise digital destruction certificate

Approved replacement for destruction-process §16 and DEST-48: the certificate
shows the prominent organization, Arabic/English title, Committee for Appraisal
and Destruction of Sharjah Archives approval statement, human-readable job and
destruction numbers, actual digital completion date, participating people with
their organizational units, and certificate generation date. It omits the
aggregation listing and repeated request details, including visible checksum.

The organization uses existing Disposition settings and localized tenancy-root
fallback. Statement dates use the working timezone, localized month names and
UTC offset. Completion time comes from permanent digital-erasure proof, not the
generation timestamp or a physical confirmation. Preparation identifies the
actual completing Officer; approved current-round decisions identify File
Administrator/Unit Manager; permanent execution proof identifies the Manager.
Skipped stages produce no participant. Manager Only does not invent an Officer.
Names and unit translations follow the existing Disposition values-language
policy; unavailable entity translations retain their existing name fallback.

The snapshot retains permanent proof, approved request ID/checksum and physical
confirmation reference internally. Template and snapshot checksums remain in
artifact provenance. Read-only metadata/search rules are unaffected. The
template contract now repeats participants rather than aggregations. The
repository working v2, deterministic builder, manifest and template guide are
updated; v1 is retained for download. Existing issued PDFs are unchanged.

DT-2026-1 was rendered using a read-only demo connection and actual settings;
the application PDF and filled DOCX were visually checked. The preview fits on
one portrait page and includes all four actual participants. This preview does
not replace the issued document, save evidence, replay destruction or send
email. No database migration, environment variable or WebUI catalogue key was
introduced. Arabic statement wording follows the approved terminology for
Sharjah Archives, دار الوثائق في إمارة الشارقة.

Verification: the initial completion/template run passed 58 cases and exposed
one revision-history test whose content mutation used the contract's old title
capitalization. The contract and builder now use the same title. A final run
passed all 16 completion/recovery, Standard/Manager Only participant and template
revision-history cases, including the initially failing case. Both uniquely
named disposable databases were dropped. Real PDF rendering verifies one page,
embedded Changa, the job reference and absence of the aggregation listing.
Compilation, manifest and whitespace checks passed; API environment templates
remain synchronized. No translation artifact replacement or new UI key is
needed for this document-only wording change.

Arabic terminology correction: the title is شهادة الإتلاف الرقمي, the statement
uses لجنة الفرز والإتلاف and تطبيق وثق الإتلاف الرقمي. Job remains عملية الإتلاف
to distinguish the overall process from a workflow مهمة. The repository DOCX,
manifest, statement source and specification were reconciled, and the read-only
demo preview was refreshed. Existing issued certificates remain unchanged.
The focused snapshot and real-PDF tests passed (2 cases) in a fresh disposable
database, which was dropped. The refreshed PDF and DOCX render were visually
verified as one page with the corrected Arabic title and statement.

Participant-unit correction: Officer preparation now uses the completed task's
audited acting role to resolve the person's organizational unit. A job owner or
routing unit cannot identify that person's unit. Demo confirms Shyma's role is
in Records Unit, while the job owner is Records Management Department. The
corrected preview shows Records Unit for Shyma. The participant header now uses
the existing catalogue wording الدور; Name and Organizational unit already
match the catalogue. Two focused integration/real-PDF cases passed, including
an Officer whose role unit differs from the job owner. The disposable database
was dropped. No issued PDF or historical event was rewritten.
