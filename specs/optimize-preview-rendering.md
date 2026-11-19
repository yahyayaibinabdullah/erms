# Optimize Preview Rendering

**Approved for implementation by the project owner, 19 November 2026.** Phase 1 covers original PDFs in saved records and private drafts. The existing full PDF.js viewer and the digital-component preview navigation specification govern reader behavior. Phase 2 covers converted PDFs in saved records and private drafts, as requested by the project owner on 19 November 2026.

| ID | Phase 1 requirement | Verification |
| --- | --- | --- |
| OPR-1 | Open original PDFs by a same-origin authenticated URL. The WebUI keeps the API session credential server-side and relays binary bytes with bounded memory. Load optional viewer assets only on preview. | Browser first-page render, network trace, peak memory, English and Arabic reader, thumbnail navigation and repeated opens. |
| OPR-2 | Support full GET, metadata-only HEAD and single HTTP ranges with exact lengths, 206 and 416 semantics. Locate segments using their stored sizes and fetch only intersecting payloads. Start with the existing PostgreSQL schema. | Compare returned bytes at the beginning, across an irregular segment boundary and near EOF. Verify late seeks avoid earlier payloads. |
| OPR-3 | Authorize every request under the current saved-component view or private-draft policy. Pin the original version for each open. Replacement, revoked access, deletion, draft promotion or expiration must prevent further reads of stale content. Preserve processing-copy and destruction safeguards. | Through the API, exercise authorized, denied, stale and abandoned reads. Check processing-copy and connection cleanup. |
| OPR-4 | A saved PDF open produces one content-view event across probes, retries and page jumps. Private draft preview produces none. Preserve independent Print and Download controls and hidden annotation editors. | Inspect event history and existing viewer/capability regressions. |
| OPR-5 | Closing or switching stops outstanding work. Keep server buffers bounded under simultaneous viewers and avoid reading or retaining the entire original on open. | Exercise cancellation, concurrent viewers, session isolation and component switching. |
| OPR-6 | Measure before editing the transport and repeat on the same deterministic text and image PDFs, browser, scenarios and network profiles. | Report click to first page, late-page latency, bytes to first page, storage payload read and API/WebUI/browser peak memory. Distinguish measured samples, inferred byte counts and limitations. A representative large PDF renders before complete transfer and a late seek reads only relevant payloads. |

Use the repository's disposable database runner for database-backed measurements. Record fixture sizes, raw samples and cleanup. Choose PDF.js prefetch and chunk size using the measurements. Consider indexed segment offsets only if locating segments becomes a measured bottleneck.

## Converted-document phase

Measure conversion latency separately. The initial recommendation is to perform one bounded conversion per open, then serve its binary output via an authenticated response. Evaluate temporary rendition reuse only if justified by measurements, with explicit authorization, expiry, disposition and cleanup rules. Annotation persistence and changes to the print/download workflows are outside this transport phase.

## Phase 1 implementation

The [preview dialog](../frontend/webui/component_preview.py) obtains metadata using an authorized HEAD. For a saved open, its UUID request ID identifies one content-view event and makes a retried open idempotent. Every subsequent request validates that receipt against the current login session, component and active content set, and checks the SHA-256 ETag and current access. Drafts use their separate owner, membership, completion and expiry checks. The [WebUI relay](../frontend/webui/pdf_transport.py) uses the NiceGUI browser session to supply the API bearer token. It relays the range, status and inline security headers with private, no-store caching.

The [viewer bridge](../frontend/webui/static/pdfjs/erms-viewer.mjs) opens the URL with 128 KiB PDF.js ranges and disables streaming and automatic prefetch for originals. Small PDFs can finish in one binary GET. Large PDFs use the initial GET to discover range support, then seek using 206 responses. Some bytes from the initial GET can already be in transit when PDF.js cancels it.

The [storage reader](../backend/services/api/content_storage.py) computes the requested interval from segment sizes, then queries only the matching immutable segment IDs. Each SQL payload result is bounded to 256 KiB. Connections return to the pool between network writes. Saved responses retain their existing disposition processing-copy registration until completion or disconnect. Database schema, configuration templates and translation catalogues require no changes for this phase.

## Measurement results, 19 November 2026

Headless Chrome 157.0.8103.79 on macOS, real record Preview button, full NiceGUI, API and PostgreSQL. The baseline was measured on the working viewer before transport edits. A second, instrumented comparison used the original source at `64a024a5c2d3` and the upgraded worktree. Each run used a new database initialized from the canonical schema and dropped on exit. Both received identical deterministic PDFs through the normal upload API.

| PDF | Pages | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| Searchable text | 3,200 | 43,415,066 | `e09e2f5989205a59a9b207992e3891f39df9c6edab3380dbd904884de978a85c` |
| Grayscale raster | 160 | 42,014,207 | `d009bb9367efa2a1fd4e3bd4869e22e4b3e4880e186d148649680cdec20b6065` |

On the shaped link, first-page time fell from 4.58–4.60 s to 0.81–0.84 s for the text PDF and from 4.41–4.48 s to 0.52 s for the scan. The scan’s final page took 264–269 ms, up from 37–40 ms when the complete scan was already resident. The browser requested about 512 KiB during that jump. The text fixture’s final content was already covered by data fetched around its trailing cross-reference table.

### Raw paired samples

“Local” is loopback. “Shaped” adds 40 ms per document response and limits each response to 32 MiB/s, applied to both the historical WebSocket document message and the upgraded binary HTTP bodies. Static viewer assets use loopback in both profiles. Each browser ran two opens per profile and fixture in alternating order. Timing starts at Preview click and ends at the first rendered canvas. Jump time runs from selecting the final page to its completed render.

Payload columns use MiB. UI bytes count application bytes emitted by the WebUI up to the first rendered page, including the base64-bearing message or any initial binary GET bytes. DB bytes count logical bytes returned by the storage reader, including work on a cancelled GET. PostgreSQL disk I/O and compressed wire size are separate quantities. Peak resident memory is sampled about every 100 ms during each open and jump for the whole API, WebUI and Chrome process tree respectively. Absolute peaks include fixture upload, allocator history and other browser processes. The two samples illustrate these fixtures and link profiles.

| Transport | PDF | Link | First page ms | Final page ms | UI to first MiB | DB to first MiB | DB during jump MiB | Peak API / WebUI / Chrome MiB |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Base64 | Text | Local | 3306 | 155 | 55.21 | 41.40 | 0.00 | 331 / 552 / 1282 |
| Base64 | Text | Shaped | 4602 | 127 | 55.21 | 41.40 | 0.00 | 288 / 501 / 1345 |
| Base64 | Text | Local | 2790 | 164 | 55.21 | 41.40 | 0.00 | 323 / 514 / 1333 |
| Base64 | Text | Shaped | 4580 | 150 | 55.21 | 41.40 | 0.00 | 321 / 565 / 1474 |
| Base64 | Scan | Local | 2644 | 41 | 53.42 | 40.07 | 0.00 | 298 / 646 / 1595 |
| Base64 | Scan | Shaped | 4478 | 37 | 53.42 | 40.07 | 0.00 | 256 / 493 / 1533 |
| Base64 | Scan | Local | 2842 | 34 | 53.42 | 40.07 | 0.00 | 263 / 534 / 1176 |
| Base64 | Scan | Shaped | 4413 | 40 | 53.42 | 40.07 | 0.00 | 262 / 485 / 1270 |
| Ranges | Text | Local | 918 | 53 | 0.90 | 1.15 | 0.00 | 131 / 94 / 919 |
| Ranges | Text | Shaped | 840 | 46 | 0.78 | 3.40 | 0.00 | 118 / 93 / 1008 |
| Ranges | Text | Local | 598 | 59 | 1.03 | 2.90 | 0.00 | 118 / 94 / 1089 |
| Ranges | Text | Shaped | 814 | 45 | 0.78 | 3.65 | 0.00 | 120 / 95 / 1096 |
| Ranges | Scan | Local | 351 | 99 | 0.69 | 1.44 | 0.50 | 120 / 93 / 1097 |
| Ranges | Scan | Shaped | 517 | 264 | 0.57 | 3.94 | 0.50 | 121 / 108 / 1103 |
| Ranges | Scan | Local | 265 | 105 | 0.82 | 1.32 | 0.50 | 121 / 108 / 1106 |
| Ranges | Scan | Shaped | 522 | 269 | 0.57 | 3.82 | 0.50 | 121 / 109 / 1103 |

The initial pre-edit loopback measurements on smaller fixtures were 983 ms to first page for an 800-page, 10,791,769-byte text PDF and 681 ms for a 40-page, 10,503,646-byte scan. The first upgraded loopback run on those same files took 542 ms and 227 ms respectively. In a separate 4 MiB/s stress run the original 3,200-page text PDF missed the 60-second first-page deadline. That failure is excluded from the paired 32 MiB/s samples. The upgraded viewer also passed component switching during an active transfer, concurrent range reads and explicit stream cancellation under the 4 MiB/s profile.

Three Chrome windows sharing one signed-in user opened the 40.1 MiB scan through independent Preview actions on the 4 MiB/s per-response profile. All three opens overlapped. The first pages rendered in 776, 731 and 729 ms, with all three ready within 778 ms of the first click. Sampled peak RSS was 123 MiB for the API, 136 MiB for the WebUI and 1,691 MiB for the combined Chrome process tree. This concurrency sample covers the upgraded transport only.

### Reproduction and verification

Run `tools/run_webui_integration.py --browser chrome --browser-scope pdf-performance --browser-python <browser-venv-python>` with the API virtual environment and the local disposable runner configuration. Supply a fresh output directory with `--output` to retain the report, storage and transfer counters, and cleanup evidence. To reproduce the old side, use the same benchmark tooling with the pre-upgrade application source and add `--pdf-baseline`. Each run creates and owns its database. The benchmark includes the fixture generator and leaves the application stack under user control.

- OPR-1 and OPR-6 use the [paired browser benchmark](../tools/webui_browser_pdf_performance.py). It checks that both SQL payload and WebUI bytes at first render are smaller than the file.
- OPR-2 through OPR-5 use the [original-PDF API regressions](../backend/services/api/tests/test_original_pdf_ranges.py), [staging regressions](../backend/services/api/tests/test_staged_component_preview.py), [disposition fence test](../backend/services/api/tests/test_disposition_destruction.py), and the browser switch/abort check. The API tests verify the exact segment IDs and byte counts read across an irregular boundary. The browser check verifies that abandoned streams release their processing-copy registrations.
- The [saved component journey](../tools/webui_browser_components.py) and [record draft journey](../tools/webui_browser_records.py) exercise the shared reader and language-specific behavior.

The focused verification passed 19 API tests and 95 WebUI tests. Chrome passed the English and Arabic saved-component and record-draft journeys, including text selection, thumbnails, record navigation, staged cancellation and the converted-document regression. The catalogue reference and active-key coverage check passed. The existing preview failure message is reused in both languages.

A broader WebUI entity test run also reproduced three source-layout assertion failures on the untouched baseline: personal-dialog container counts, aggregation page-size source text and governed-move control counts. Those checks are independent of the PDF paths.

## Phase 2 implementation and operation

Each converted component visited in a viewer dialog has its own rendition UUID. Switching components retains that UUID for the lifetime of the dialog. Returning to the component sends an authorized metadata-only HEAD with the existing rendition UUID and a fresh audit request ID. If the source has changed or the handle has expired, the viewer prepares a fresh rendition. The authorized opening HEAD stages the selected source in bounded blocks, runs the existing converter with its configured limits and returns the length and SHA-256 ETag of the resulting PDF. Subsequent HEAD and GET requests use the same open ID, login session and source version. The regular PDF.js viewer requests 128 KiB ranges through the same-origin relay. A concurrent retry of the opening HEAD with its original ID shares the completed conversion. Opening the document in a second viewer creates a separate ID and conversion. Any API replica can serve a request.

PostgreSQL holds one header in `preview_renditions` per converted component in each viewer and the binary data in `preview_rendition_chunks`, keyed by `(open_id, chunk_no)`. Each chunk holds up to 256 KiB. One HTTP range can read part of a chunk or cross a chunk boundary. The range handler seeks directly to that offset. The header and all chunks publish in a single transaction. Saved previews produce one content-view event per deliberate selection, including a return visit. Each content request rechecks saved-record access or private draft ownership and privilege. Conversion scratch files use isolated workspaces; saved-file processing retains its disposition fence and crashed workspaces can be recovered on API startup.

### Cleanup and deployment

- Switching components closes the old PDF.js frame and stops its reads. Converted components stay available across switcher pages and visits to original PDFs or native media. Closing the dialog releases all its rendition IDs. If a conversion commits after close, its completion handler requests release again. Closing another dialog leaves these IDs alone.
- A connected, open viewer renews its retained IDs every 2 minutes, including components hidden by the switcher. Renewal and release act only on IDs owned by the authenticated login session, in batches of up to 100, and return no content. Renewal moves the deletion deadline forward without fetching document bytes, rerunning the converter or extending the login idle deadline. An expired rendition cannot be renewed. Abandoned renditions expire 10 minutes after their last successful renewal or authorized content request. The existing session-cleanup worker sweeps up to 100 expired headers per cache-maintenance pass (default cadence 60 seconds). Fresh conversions also reclaim a batch. Reads enforce expiry immediately. After expiry, reopening starts a new conversion.
- A foreign key deletes all chunks when their header is removed. Deleting the login-session row, source content set or draft component cascades to the header. Replacing saved content evicts previews of the superseded version. Disposition removes the associated bytes when it erases the content set. Logout/revocation immediately prevents reads through normal authentication; physical deletion can also occur on release, idle cleanup or deletion of the session row.
- Both tables are UNLOGGED and disposable after PostgreSQL crash recovery. Their contents can be omitted from logical backups with `--exclude-table-data=public.preview_renditions --exclude-table-data=public.preview_rendition_chunks`. Regular PostgreSQL vacuuming makes deleted space available for reuse. A temporary peak can leave allocated relation files above the current live-data size.
- Apply [migration 118](../database/migrations/118_converted_preview_renditions.sql) to existing databases before restarting the API, WebUI and session-cleanup worker. Fresh installations use the canonical schema and baseline. No new configuration settings, UI strings or translation keys are needed. The worker should remain enabled even when no users are opening documents.

### Paired 200-page workbook measurements

The same DOCX (2,579,277 bytes) and its original PDF (3,777,390 bytes) were uploaded to fresh disposable databases through the record upload API. Chrome opened each file four times through the Preview button and rendered pages 1 and 200. Each series alternated loopback with the Phase 1 shaped profile (40 ms per document response, 32 MiB/s). The DOCX used a fresh LibreOffice process and conversion per open. The PDF control used the Phase 1 range transport throughout.

| File and transport | Link | First page, ms | Page 200, ms | Converter, ms | WebUI bytes to first page |
| --- | --- | --- | --- | --- | --- |
| DOCX base64 | local | 15479 | 41 | 5831 | 5,036,862 |
| DOCX base64 | limited | 15637 | 41 | 6001 | 5,036,862 |
| DOCX base64 | local | 13976 | 41 | 4600 | 5,036,862 |
| DOCX base64 | limited | 15318 | 41 | 5681 | 5,036,862 |
| PDF control before | local | 448 | 40 | — | 3,711,854 |
| PDF control before | limited | 817 | 47 | — | 3,351,302 |
| PDF control before | local | 411 | 39 | — | 3,515,246 |
| PDF control before | limited | 816 | 45 | — | 3,383,966 |
| DOCX ranges | local | 8011 | 63 | 6907 | 3,515,246 |
| DOCX ranges | limited | 7382 | 69 | 6241 | 3,384,174 |
| DOCX ranges | local | 6025 | 51 | 5540 | 3,515,246 |
| DOCX ranges | limited | 6043 | 43 | 4999 | 3,384,174 |
| PDF control after | local | 444 | 50 | — | 3,515,246 |
| PDF control after | limited | 816 | 76 | — | 3,351,302 |
| PDF control after | local | 474 | 50 | — | 3,646,318 |
| PDF control after | limited | 1685 | 68 | — | 3,449,710 |

The upgraded DOCX path read 2,579,277 original bytes once on each open, then zero source bytes during the final-page jump. The generated rendition supplied 131,072 bytes during each measured jump. The four DOCX opens sampled WebUI peak RSS of 151–170 MiB before and 81–85 MiB after. Memory includes process history. Both phases reported 200 pages and rendered the first and last pages. Conversion still accounted for 5.0–6.9 seconds of each upgraded open. PDF.js requested most of this particular illustrated PDF before first paint. Its initial whole-file GET can overlap range requests before cancellation. Logical rendition reads before first paint therefore reached 4.04–7.03 MB, even though first-paint WebUI transfer was 3.38–3.52 MB. These measurements do not imply that every PDF layout or cold conversion will improve by the same amount.

The original baseline harness rendered all eight opens and recorded their timings, then failed its historical large-PDF assertion that logical source reads at first paint must be smaller than the PDF. The measured overlap above also occurred for this smaller original-PDF control. The workbook-specific checks now validate the original control separately from the converted source, the conversion count, actual HTTP transport, byte reads on page jump, and zero remaining converted headers/chunks after close. The large synthetic PDF gates still run for their original fixtures.

Reproduce with the Phase 1 Chrome command above, adding `--pdf-workbook "/path/to/How to Invest in Cryptocurrency.docx"` with its sibling PDF in the same directory. The pre-upgrade converted transport uses `--pdf-baseline` with the pre-change application. The browser report retains per-open RSS, bytes, first/final page latency, and conversion times. The runner records database creation and cleanup.

[Converted API regressions](../backend/services/api/tests/test_converted_pdf_ranges.py) cover immutable ranges, retries, independent opens, authorization, replacement, discard, expiry, failed conversion and reclamation. [Disposition verification](../backend/services/api/tests/test_disposition_destruction.py) exercises erasure of derived data. The Chrome workbook benchmark exercises a real conversion and verifies cleanup on close. The saved/draft UI tests and English/Arabic draft journeys exercise abandonment, native components and the shared reader.


### Viewer retention verification

Chrome opened the 200-page DOCX, switched to its original PDF, opened a second convertible text file, then revisited the DOCX and text. LibreOffice ran exactly twice. Both return visits used their original rendition URLs. After the dialog closed, the disposable database contained zero rendition headers and zero chunks. Separate tests exercise a return during an in-flight conversion, source invalidation, a late conversion completing after close, refresh of hidden components, audit events, and cross-session isolation. Moving database timestamps across the 10-minute boundary verifies that renewal cannot revive an expired row.

One cold DOCX sample in the first browser run hit the existing first-paint transfer limit exactly (3,777,390 WebUI bytes). Completed HTTP bodies accounted for 3,253,102 bytes. The independent repeat passed the transfer gate and the component-switch and deletion checks. The timing of cancellation of PDF.js’s initial GET still affects that byte metric.

### Deployment amendment — warm LibreOffice workers

The API launcher owns one pool per service instance. A private supervisor starts
`LIBREOFFICE_WORKERS` headless LibreOffice processes and assigns one complete PDF
export at a time to each. The deployment default is 1. Restart the API service
after changing this value. All Uvicorn workers in that instance share the pool.
The viewer continues to retain completed renditions under the existing rules.

Each slot checks its resident by opening a private synthetic document and exporting a
readiness PDF. Idle slots check process liveness and replace exited workers. During
export the supervisor monitors both the resident and the forwarding command. On a
resident crash it discards partial output and permits one requeue within the original
timeout. A timed-out or failed export retires the resident. Every request retains
its original source version, workspace and processing-copy locks through conversion.

The WebUI submits an authorized preview request to the API. An API request
process stages the source and submits a job to the supervisor's private Unix
socket. A ready slot takes the next job. When a crashed job is requeued, any
available slot can take it. With a one-worker pool this means waiting for a
replacement. An idle process is checked about every 250 ms, and an active one
about every 200 ms. A failed readiness export keeps that slot out of service
and schedules another startup attempt after ten seconds. Closing the API
launcher shuts down the supervisor and its residents. The API's HTTP health
response covers API availability; the functional converter probe runs inside
the supervisor.

Verification used one- and two-slot pools to export the complete 200-page
DOCX, 40-page XLSX and 60-slide PPTX. Terminating a real resident during DOCX
export produced a complete PDF on retry and a new resident PID with a
successful readiness export. The [deployment regressions](../backend/services/api/tests/test_office_pool.py)
also exercise one shared slot under two Uvicorn processes, requeue to a
surviving slot, worker replacement, cleanup and restart-only sizing.

## Deferred proposal — pre-generate shared PDF renditions on save

**Deferred for further review and analysis. Implementation requires separate approval.**

For a newly saved digital component that LibreOffice can convert and whose size exceeds a configurable threshold, the save transaction would enqueue a database job for that source version. The save would return after commit, without waiting for LibreOffice. A background worker would produce **one shared, complete PDF rendition per source version** and store its header and chunks separately from the original content. Below-threshold components and private drafts would continue to use the current viewer-scoped conversion.

### Interactive preview takes priority

Foreground and background requests would use the same job for a source version. An authorized viewer opening the component would get the following behavior.

| Rendition state at open | Proposed behavior |
| --- | --- |
| Ready | Serve the shared PDF immediately through the existing authenticated range-loading path. |
| Queued | Promote the job ahead of queued background work. The viewer waits for that export, which also populates the shared rendition. |
| Converting | Join the in-flight job. Concurrent viewers can use the same result as soon as it is published. |

The worker would publish the header and all chunks atomically after rechecking the source version and applicable conversion settings. A worker crash could be retried without exposing a partial PDF. Replacement, deletion or disposition would invalidate the old rendition and prevent a late job from republishing it. Each open and range read would still check current access. Only a user opening the preview would generate a content-view event. Closing a viewer would release that viewer's access while the shared PDF remained available under its own retention policy.

### Tradeoffs and review criteria

- **Interactive latency during imports.** Background work should claim only available capacity, with interactive jobs served first. With the default single worker, a preview arriving during an unrelated background export still has to wait. Measure queue wait and click-to-first-page time during bulk saves before deciding whether to reserve separate background capacity and pay its additional memory cost.
- **Database growth and retention.** The measured 2.58 MB DOCX produced a roughly 3.78 MB PDF. A durable rendition adds storage, write-ahead logging, replication traffic and backup volume. Review retention, eviction, rebuild after conversion-setting changes, and erasure during disposition before choosing a storage policy.
- **Threshold and wasted conversion.** File size alone predicts neither conversion cost nor the likelihood of a preview. A 5 MB threshold would miss the measured 200-page DOCX. Review size, conversion time and preview frequency by format before selecting a threshold.

A proposed pilot would cover newly saved eligible versions and leave historical backfill for a separate decision. Compare first-page time for ready and unfinished renditions, interactive queue wait under bulk saves, additional database bytes, and the fraction of pre-generated PDFs ever opened. Use those results to compare conversion at save time with conversion on first preview followed by shared retention.
