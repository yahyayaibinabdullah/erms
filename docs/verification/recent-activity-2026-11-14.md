# Records and Aggregations activity verification — 14 November 2026

Each landing page now requests its own authorized activity cards, with number
and title included. The request log showed one scoped activity request and one
favourites request per completed switch. It showed no per-card resource, parent
or closure requests during those switches. Before the change, the demo
diagnostic counted 164 and 186 follow-up requests respectively, after an
activity query that took roughly 0.6 seconds. Those are historical demo
observations, separate from the disposable benchmark below.

## Large disposable database

Native macOS PostgreSQL 18.4, with LLVM JIT unavailable. The maintained fixture
contained 8,400 aggregations, 18,400 records, 36,800 components and **1,220,984**
history rows. The benchmark reader had 568,800 events in its rolling activity
window, including 16,800 aggregation changes, 368,000 record changes and
184,000 component views. The original combined query returned 300 entries.
Each scoped query returned 150, exactly 50 per operation. The benchmark compared
IDs, operations, timestamps and the original defined order. Only entries tied
on all original display keys could exchange places. The new query resolves
that final tie by event ID descending.

Times are milliseconds. SQL samples use the same fixture and caller. HTTP
samples include authentication and JSON response delivery over loopback.

| Measurement | All samples (ms) |
| --- | --- |
| Original combined SQL | 19,720 / 19,482 / 22,768 |
| Aggregations SQL | 229 / 188 / 193 |
| Records SQL | 291 / 304 / 630 |
| Aggregations HTTP | 314 / 281 / 253 / 246 / 359 / 240 / 225 |
| Records HTTP | 372 / 329 / 358 / 370 / 359 / 382 / 484 |

Each new plan used the existing activity indexes. The component-view index was
scanned once per query. The reader had ordinary ACL access to the returned
resources. The governance audit path was exercised separately in API tests.
The output includes the selected card fields and no full resource rows.

To reproduce the database benchmark from the repository root:

```sh
backend/services/api/.venv/bin/python tools/benchmark_recent_activity.py \
  --baseline-ref 6ddcdf5abbad2adc68225dce8dcf2fad6574e746 \
  --output .runtime/recent-activity-verification/repeat
```

The runner builds a fresh uniquely named database from the canonical schema
and reference data. It loads the existing dashboard fixture and synthetic
aggregation events, runs maintenance, and drops the database on exit.
The successful run's plans, individual timings and request logs are under
`.runtime/recent-activity-verification/large-03/`. The earlier large attempt
stopped on an exact timestamp/resource tie that the original SQL did not
order by operation. The comparison was corrected to check the defined order
and exact membership within ties. Both attempt databases were dropped.

## WebUI switches

A temporary launcher instrumented the isolated WebUI on the same large fixture.
It timestamped the native click, observed replacement of the activity panel,
and sampled after two animation frames. Times exclude tool dispatch and
polling. Each repeated switch showed five correct cards from that page's
snapshot followed by five freshly authorized cards.

| Layout | Destination | First measured refresh | Return snapshot | Return refresh |
| --- | --- | ---: | ---: | ---: |
| English LTR | Aggregations | 384 ms | 41–43 ms | 258–392 ms |
| English LTR | Records | 428 ms | 42–44 ms | 409–441 ms |
| Arabic preference, RTL | Aggregations | 271 ms | 40–43 ms | 259–341 ms |
| Arabic preference, RTL | Records | 522 ms | 42–43 ms | 391–441 ms |

The disposable Arabic catalogue used English fallback for the observed panel
labels. The browser direction was RTL. The first measured RTL Records switch
already had a snapshot, visible after 40 ms. Both **View all** dialogs showed all
150 entries in the English browser check. An authorized edit to a synthetic
record appeared on the next Records refresh after 392 ms, after its old title
appeared from the same page's snapshot at 42 ms. Rapid Aggregations → Records
→ Aggregations switching finished with aggregation cards. No browser errors
were recorded in the repeated timing checks. The browser tab was closed and
the isolated processes and database were removed.

## Demo switches after the local stack restart

In the signed-in demo WebUI, one visit to each page populated its activity
snapshot. I then measured five switches in each direction in the same Chrome
tab. Each switch showed five cached cards for the destination, followed by a
replacement panel with five refreshed cards. The stack logs confirmed that all
ten scoped activity requests returned HTTP 200.

| Destination | Cached cards observed | Fresh cards observed | Additional wait after cached cards |
| --- | ---: | ---: | ---: |
| Aggregations | 402 ms (385–418) | 466 ms (438–486) | 64 ms (53–68) |
| Records | 396 ms (394–405) | 473 ms (453–508) | 77 ms (59–103) |

The table shows medians and observed ranges. The timer started when the
automation issued the click command. That command returned after 347–374 ms
across the ten switches, so the first two columns include the time spent
dispatching the click. Polling first detected each render 12–30 ms after the
previous observation around the transition. The additional wait is the median
of the paired differences within each switch, which removes the shared click
dispatch time and still includes polling uncertainty.

Using the click acknowledgement as an alternate reference, the median time
to observe cached cards was 38 ms for Aggregations and 26 ms for Records. The
median time to observe fresh cards was 101 ms and 103 ms, respectively. The
acknowledgement records when the command returned. The actual click may have
occurred earlier, and the polling records when the panel was first observed.
These timing boundaries differ from the native click and animation frame
timestamps used in the disposable benchmark above.

Individual observations, in milliseconds from click command dispatch:

| Switch | Destination | Click acknowledgement | Cached cards | Fresh cards | Additional wait |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | Aggregations | 359 | 390 | 456 | 66 |
| 2 | Records | 362 | 394 | 453 | 59 |
| 3 | Aggregations | 347 | 385 | 438 | 53 |
| 4 | Records | 368 | 394 | 462 | 68 |
| 5 | Aggregations | 367 | 410 | 469 | 59 |
| 6 | Records | 370 | 396 | 473 | 77 |
| 7 | Aggregations | 349 | 418 | 486 | 68 |
| 8 | Records | 374 | 399 | 479 | 80 |
| 9 | Aggregations | 365 | 402 | 466 | 64 |
| 10 | Records | 373 | 405 | 508 | 103 |

## Regression evidence

- Seven disposable API regressions passed. They cover signed-in and unsigned
  callers, permission revocation, authorization before the cap, ties and
  deduplication, component view attribution, governance audit metadata,
  compatibility for callers that omit the resource filter, and equivalence to
  canonical view predicates.
- 87 focused client, state and panel tests passed. Seventeen additional NiceGUI
  interaction tests passed using asyncio auto mode.
- A wider WebUI test run encountered four source assertions unrelated to
  activity. All four were reproduced against the unchanged baseline commit.
- Existing Dashboard and search visibility SQL variants were compared byte
  for byte with the baseline. New ACL attribution is enabled only when
  loading activity cards.
