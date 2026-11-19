# Warm LibreOffice worker benchmark

These historical measurements compare the disposable prototype with the former fresh-process converter. The deployed pool and its restart and recovery behavior are described in the [API deployment guide](../deployment.md#libreoffice-conversion-pool).

## Measurements, 19 November 2026

On macOS 15.6.1 ARM64 with headless Chrome 157.0.8103.79 and loopback HTTP, two warm workers reduced the median time to the first page for a single viewer by 2.40 seconds for DOCX, 2.28 seconds for XLSX and 1.80 seconds for PPTX. All three concurrent viewers saw their first pages a median 1.97 seconds sooner. The warm pool raised server memory use and made the queued spreadsheet slower in five of six bursts.

| Full rendition | Current, solo | Two warm, solo | Current, three viewers | Two warm, three viewers |
| --- | ---: | ---: | ---: | ---: |
| DOCX, 200 pages | 6.70 s | 4.29 s | 7.46 s | 4.70 s |
| XLSX, 40 pages | 4.20 s | 1.92 s | 4.54 s | 5.43 s |
| PPTX, 60 pages | 5.44 s | 3.64 s | 6.53 s | 3.97 s |
| All three first pages ready | | | 7.46 s | 5.49 s |

Values are medians. One current run and two independent warm runs each exercised 18 opens, for 54 successful opens. Each current table entry represents three trials and each warm entry represents six. The current path ran three exports concurrently in each burst. The pool ran two. XLSX waited 3.27–3.46 seconds for a worker in five bursts. In the sixth, DOCX waited 1.48 seconds and XLSX painted in 1.99 seconds. Preparing both workers took 3.75–3.94 seconds at server startup, outside the click timings.

| RSS with three viewers | Current, range across bursts | Two warm, range across bursts |
| --- | ---: | ---: |
| Idle API children immediately before burst | 0 MiB | 476–1,097 MiB |
| Peak API children, including converters | 909–1,003 MiB | 1,063–1,414 MiB |
| Peak server, API and WebUI trees combined | 1,070–1,208 MiB | 1,257–1,614 MiB |
| Peak three Chrome process trees | 2,286–2,376 MiB | 2,283–2,451 MiB |
| Peak server and browsers together | 3,294–3,434 MiB | 3,501–4,033 MiB |

Before the first document open, the warm API children occupied 291–338 MiB. Before the final burst, they still occupied 911 MiB in one run and 1,097 MiB in the other. Two worker slots bound simultaneous work, but these samples show that slot count alone does not give a predictable memory ceiling. The short test cannot establish a long-term leak or plateau.

The page counts and all-page text and geometry digests matched across all three completed runs. Every final page rendered. The tests verified that closing all dialogs released the rendition headers and chunks. An earlier pilot saw a worker crash during startup after its PID file appeared and a probe succeeded while it was still opening the placeholder document. It produced no completed samples and was excluded. The first successful warm run began while that failed browser trial was unwinding. The independent repeat started with the previous trials fully stopped. All four disposable databases were dropped, and the pool trials verified resident shutdown and removal of their temporary profiles. The [per-sample measurements](warm-office-pool-results.json) retain both successful pool runs separately, including queue time, export time, memory, fixture hashes and output digests.

**Recommendation.** Keep the existing converter as the default. The first-page gain warrants a deployment-host trial with a shared worker budget, idle retirement and a process memory limit. Repeat the mixed burst and run sustained traffic before choosing a pool size. Check the slowest viewer as well as the time for the batch to finish.

## Method

All measured runs used the same installed LibreOffice 26.8.0.3 binary. The current path creates a new profile and process for each conversion. The prototype starts two private headless desktops before API readiness. Each holds a small synthetic text document open to keep the desktop alive. The normal conversion command forwards its job to the leased desktop through LibreOffice's local profile IPC. The worker must stay alive through the export. Startup waits for the PID file and the open-document lock on the synthetic Writer document, then verifies a separate PDF export before admitting requests. Worker startup is measured separately. No converter is attached to the development stack.

A pool lease allows one active export per worker. Two workers can admit two additional waiting requests. A full queue rejects new work, and time spent waiting consumes the conversion timeout. The browser benchmark drives up to three requests. Production authorization, XLSX print preparation, per-request workspaces, rendition publication, PDF byte ranges, viewer expiry and release all run on the existing application path.

All runs use the same 200-page illustrated DOCX, a 40-sheet XLSX with formulas and charts (one printed page per sheet), and a 60-slide PPTX with tables. Files are generated or copied once, then reused byte for byte. Chrome opens each fixture alone three times. Three separately signed-in Chrome instances then open one file of each format together, three times, rotating format assignments. Each open gets a fresh rendition. Browser clocks measure Preview click to completed first-page canvas, polled every 20 ms. Every viewer jumps to and renders the final page. On the first solo open of each format the test also hashes page boxes, rotations, text and text transforms for every page. This checks textual and geometric equivalence across both arms. It does not compare pixels, chart colors or accessibility tags.

Memory is the sum of resident set sizes in one process snapshot, sampled approximately every 100 ms plus the cost of `ps`. The server total includes the API, its LibreOffice processes and other children, and the WebUI process tree. Browser memory includes the participating Chrome process trees. Database and OS cache memory are excluded. Shared mappings can be counted in multiple processes. The peak of a total is calculated from simultaneous samples. Idle memory is sampled immediately before each batch.

## Reproduce

Supply the standard API and WebUI virtual environments, the Chrome/Selenium interpreter used by the repository browser runner, a PostgreSQL account permitted to create disposable databases, and the same LibreOffice executable for both trials. The fixture generator uses openpyxl and python-pptx. The Chrome harness currently targets macOS. Run the trials in sequence.

```sh
python tools/office_preview_benchmark/fixtures.py "/path/to/200-page-sample.docx" .runtime/office-fixtures

for workers in 0 2
do
  backend/services/api/.venv/bin/python tools/run_webui_integration.py \
    --browser chrome --browser-scope office-pool \
    --browser-python /path/to/selenium/bin/python \
    --office-fixtures .runtime/office-fixtures --office-workers "$workers" \
    --output ".runtime/office-test-$workers"
done

python3 tools/office_preview_benchmark/compare.py \
  .runtime/office-test-0 .runtime/office-test-2 .runtime/office-comparison.json
```

Set the existing `LIBREOFFICE_BINARY` to the real executable and provide `DATABASE_URL` through the usual local configuration. Use new output directories for subsequent runs. The runner creates a fresh uniquely named database from the canonical schema per trial and drops it at teardown. Each run writes per-open timings and RSS in `browser-results.json`, conversion arrival/start/end and resident PIDs in `office-jobs.jsonl`, and database cleanup status in `lifecycle.json`. The pool reports worker shutdown and profile removal in `office-shutdown.json`.


## Scope of a production decision

The prototype leases workers in one API process. Enabling two residents in every API worker would multiply the memory budget. Deployment would need a host-wide concurrency and admission budget, bounded waits, and a policy for recycling a resident after idle periods, large exports or a crash. A broker shared by API workers is one way to enforce that budget.

The current caller retains its processing-copy lock during a successful conversion. In the prototype the forwarding command inherits that lock, while the long-lived LibreOffice desktop performs the actual export. A production implementation would also need to keep the disposition fence valid if the API or forwarding process dies mid-job, supervise orphaned children, and verify deletion of intermediate files. Persistent private profiles and in-memory document state would need isolation and erasure checks across users. The benchmark uses synthetic files and verifies normal dialog release and normal server shutdown.

This experiment measures three document fixtures and bursts of three viewers on one Mac. It does not measure steady-state throughput over hours, hard process kills, or performance on the deployment host. These results apply to the first open that requires a conversion. Revisiting a component already retained by the same viewer continues to reuse its full PDF without acquiring a worker.
