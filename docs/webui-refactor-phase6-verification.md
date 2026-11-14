# Phase 6 — Overall verification

**Phase 6A–6U is complete for the approved local scope.** Each feature has its
own owner, regression gate and report. The final acceptance suite passes
**1,628 unit, 420 interaction and 74 real-API assembled tests**.

The latest work completed 6N–6U. All changes remain local and uncommitted on the
user's `refactor-API-python-file` branch. Branch and HEAD stayed at `839b770` during
this continuation; no branch, commit, push, pull request or history operation was
performed. **Stop here: Phases 7 and 8 require the user's next instruction.**

## Individual gates

Every row below is complete and includes Chrome/Edge comparison evidence. Counts
are the full suites at that row's gate; do not add them together as unique tests.
Historical exceptions, retained failures and corrected fixtures are explained in
the linked reports rather than erased from the evidence.

| Phase/report | Feature owner | Unit | Interaction | Real API |
| --- | --- | ---: | ---: | ---: |
| [6A](webui-refactor-phase6a-verification.md) | Relationship types | 1,550 | 209 | 43 |
| [6B](webui-refactor-phase6b-verification.md) | Audit and history | 1,563 | 210 | 43 |
| [6C](webui-refactor-phase6c-verification.md) | Shared entity controls | 1,576 | 217 | 46 |
| [6D](webui-refactor-phase6d-verification.md) | Classification | 1,592 | 223 | 47 |
| [6E](webui-refactor-phase6e-verification.md) | Security configuration and access | 1,603 | 243 | 49 |
| [6F](webui-refactor-phase6f-verification.md) | Login sessions | 1,603 | 255 | 51 |
| [6G](webui-refactor-phase6g-verification.md) | Organization | 1,603 | 264 | 55 |
| [6H](webui-refactor-phase6h-verification.md) | Text indexers | 1,603 | 285 | 57 |
| [6I](webui-refactor-phase6i-verification.md) | Account and preferences | 1,603 | 296 | 57 |
| [6J](webui-refactor-phase6j-verification.md) | Translation administration and Inspector | 1,613 | 312 | 59 |
| [6K](webui-refactor-phase6k-verification.md) | Legal holds | 1,618 | 326 | 60 |
| [6L](webui-refactor-phase6l-verification.md) | Digital components and preview | 1,624 | 337 | 61 |
| [6M](webui-refactor-phase6m-verification.md) | Aggregations | 1,624 | 345 | 62 |
| [6N](webui-refactor-phase6n-verification.md) | Records and capture | 1,624 | 345 | 64 |
| [6O](webui-refactor-phase6o-verification.md) | Security operations | 1,624 | 359 | 66 |
| [6P](webui-refactor-phase6p-verification.md) | Governance custody | 1,624 | 370 | 68 |
| [6Q](webui-refactor-phase6q-verification.md) | Global/full-text search | 1,625 | 379 | 69 |
| [6R](webui-refactor-phase6r-verification.md) | Advanced and saved search | 1,626 | 384 | 71 |
| [6S](webui-refactor-phase6s-verification.md) | Dashboard | 1,626 | 384 | 72 |
| [6T](webui-refactor-phase6t-verification.md) | Disposition | 1,626 | 397 | 73 |
| [6U](webui-refactor-phase6u-verification.md) | Messaging and notifications | 1,628 | 420 | 74 |

## What changed and what was verified

Feature controllers, dialogs, state and lifecycle ownership moved out of the root
application into dedicated modules. The root still assembles them and supplies
explicit callbacks for shared navigation and cyclic destinations. Existing
feature renderers were reused. No feature receives the whole application state
or imports the root application as its implementation dependency.

Each extraction has original-behavior evidence, source/state comparisons,
focused tests and full regression gates. The final native messaging journeys
preserve English/Arabic controls, keyboard focus, navigation and request counts.
Their only visual differences are live monitor timestamps. The preceding N–T
reports record their own comparisons, including narrowly reviewed rasterization
or timestamp differences and reproduced original product errors.

No functionality, layout, wording, translation provenance, API contract, schema,
public URL or browser-history change was intended or introduced by these moves.
No new cache was added. Existing bugs were preserved and documented. Test-only
fixture corrections respect the existing product rules; the previously unexplained
footer retry failure was reproduced and corrected as a fixed-wait test race in 6U.
The separately approved aggregation visibility fix belongs to Phase 2.

Configuration authority, API-template consistency, active translation references,
Arabic terminology and the 24 test-runner safety checks pass. All 4,071 translation
keys and artifact bytes remain unchanged. No environment or operator update is
required for this refactor. Every database-backed run used a unique disposable
local PostgreSQL database, followed by cleanup and an independent absence check;
N–U reports include failed development runs in their cleanup accounting.

## Remaining boundary and known findings

Phase 7 is the application-wide verification step; Phase 8 is cleanup and final
acceptance. Those phases have not started. Firefox, Safari and CI remain deferred
at the user's request. Passing the local gates is evidence against regressions,
not a guarantee that all possible workflows or pre-existing defects have been found.

The [prioritized working register](webui-refactor-existing-observations.md) separates
reproduced defects, unexplained observations, test issues and the separately
approved fix. The highest-priority reproduced issue is governed movement failing
because `compatible_aggregations` is undefined. The empty contained-record filter
also remains recorded, as requested. Other preserved findings include component
and favourite notification errors, a saved-query shape error and pagination icon
errors. No product fixes for these are included.

At the end of the **whole** WebUI refactor, recheck all findings after Phases 7/8
and deliver the user's requested final prioritized defect/abnormality list, with
impact, evidence and recommended next action. Revisit the unresolved loading,
refresh-cancellation, localization and focus observations rather than calling
them fixed merely because later runs passed.
