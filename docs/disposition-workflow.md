# Destruction workflow reference

The job workspace uses a compact stage tracker. This full branching diagram is
a documentation reference; actual routing follows the job’s saved review route.

In a job or task workspace, the Aggregations tab's **Search aggregations**
field searches only memberships of that job. Press Enter to match aggregation
number or title, owning organization unit name, or classification code or title.
Matching is case-insensitive and accepts partial text. It does not search the
job number or the other table columns. The field displays this scope as a hint
in English and Arabic; the separate Membership filter remains available.

```mermaid
flowchart TD
START(["Start"])
CREATE["Active job created"]
A["Records Officer preparation"]
V{"Saved review route?"}
X{"File Administrator role configured on owning unit or an ancestor?"}
B["File Administrator review"]
C["Organization Unit Manager review"]
D{"Any aggregation marked not for destruction?"}
E["Correct rejected destruction job"]
T["Records Officer correction"]
F["Records Manager review"]
G{"Any aggregation marked not for destruction?"}
Q["Approve and execute all active proposals"]
R["Remove proposal-blocked disposition units"]
H["Generate Request for Destruction Form"]
I["External approval pending"]
S{"External authority approves?"}
J["Save destruction number and approval letter"]
K{"Any physical or mixed material?"}
L["Confirm physical destruction and upload its certificate"]
U{"Any digital content to destroy?"}
M["Digital destruction"]
N["Generate and save digital certificate"]
O["Download Certificate of Destruction (Digital)"]
P["Completed"]
END(["End"])
MC["Records Manager correction"]
EMPTY["No governing roots remain: return to assigned preparer"]
START --> CREATE
CREATE --> A
A -->|"Submit for review"| V
A -->|"Records Manager Only"| Q
V -->|"Standard"| X
V -->|"Simplified"| F
X -->|"Yes"| B
B --> C
C --> D
X -->|"Skipped"| C
D -->|"Yes"| E
E --> T
T --> V
D -->|"No"| F
F --> G
G -->|"Yes"| E
G -->|"No"| Q
Q --> R
R --> H
R -.-> EMPTY
EMPTY -.-> T
EMPTY -.-> MC
H --> I
I --> S
S -->|"Rejected"| E
S -->|"Records Manager Only"| MC
MC -->|"Approve and apply proposals"| Q
S -->|"Approved"| J
J --> K
K -->|"Yes"| L
L --> U
U -->|"Yes"| M
U -->|"No"| P
K -->|"No"| M
M --> N
N --> P
P --> END
P -.-> O
classDef boundary fill:#e3f2fd,stroke:#1565c0,stroke-width:3px;
class START,END boundary;
```


## Reading review rounds on Job details

After a return, the single tracker highlights correction work and says
“Preparing review round 2” (or the next round). The return notice shows who
returned it, when, from which stage, and the reason. Expanding “View previous
rounds” shows recorded submissions and decisions, not a second tracker.
Unreached stages are omitted. Use “Load earlier rounds” for older history.
The next immutable round is created only when submitted or approved through
the existing workflow. Previous rounds and their decisions remain unchanged.


## Recovering a reopened member

Reopening an aggregation preserves its job membership and blocks progress. An
authorized IGU can use **Accelerate disposition eligibility** on the aggregation
to close it and restore its existing job's pending status when its current
retention action and organizational scope remain compatible. The reopening
flag clears atomically. Removal and re-addition are unnecessary. Ordinary
reclosure alone does not restore the member.

Existing blockers and closure restrictions remain. Recovery does not advance
the job or resume destruction, and approval validity follows the existing approved-facts comparison. Exact
restoration may retain approval; changed approved facts use the existing
correction/return flow. Saved preparation proposals remain in place. Explicit removal remains
available for incompatible members. See the
[approved amendment and upgrade guide](disposition-in-job-acceleration.md).
