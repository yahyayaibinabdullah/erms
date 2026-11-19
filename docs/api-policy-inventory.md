# API policy inventory

`security/operation-policy-registry.json` is generated from the registered
FastAPI HTTP routes. It shows the intended access rule for each operation.
The API and database enforce those rules when they handle a request.

## What belongs in the registry

- HTTP method and route;
- public, authenticated, globally privileged, or resource-scoped policy class;
- required global privilege and resource permission; and
- implementation-phase enforcement markers used by regression tests.

The registry deliberately excludes buttons, links, menus, screens, and mobile
widgets. Client code is not an authorization boundary, and line- or widget-based
entries create noisy diffs without proving that access is protected.

## Declare policies beside the route

- When one `require_global_privilege(...)` dependency is the complete route
  policy, the inventory reads the privilege directly from that dependency.
  Named dependencies created by the same factory work the same way.
- Put `@operation_policy(...)` directly above the handler when the policy
  involves a resource, a workflow relationship, a conditional rule, or another
  access class. For example, Disposition progress is
  `@operation_policy("relationship_scoped")` because the handler checks access
  to that job's workspace.
- Keep the authorization check in the dependency, handler or database command.
  Test protected routes with authorized and unauthorized callers. For scoped
  access, include a signed-in caller outside the authorized scope.

The inventory check fails for HTTP routes without a declaration or an
unambiguous global privilege dependency. It also covers HTTP methods hidden
from OpenAPI. A resource or workflow rule still needs its own declaration
when the route also has a global dependency.

## Typed resources

A record or aggregation permission also carries the resource-type gate. A read requires See on the current type. A mutation requires Use on each affected type. On reassignment the source and destination must both pass. A qualifying information-governance role can supply type access with its own clearance. The existing privilege, resource-state, clearance and ACL checks still apply. A type administrator can maintain definitions through the corresponding catalogue privilege. [Operation mapping](../specs/aggregation-and-record-types.md#73-operation-coverage)

On history routes, the resource permission controls admission to the timeline. The audit projection then checks each historical side independently. An auditor can identify the former and current types while the source side’s values are withheld. [Auditor example](event-history.md#when-a-record-or-aggregation-changes-type)

## Generate and review the registry

```bash
PYTHONPATH=. backend/services/api/.venv/bin/python tools/generate_policy_inventory.py
```

Change policies at the route and regenerate the JSON. The inventory test
compares the checked-in snapshot with the generated output. Summarize the
affected routes, who can use them, and the allow and deny tests when handing
off an authorization change.

## Multiple clients

NiceGUI, Flutter, and future clients share this single API registry. Each client
should consume authoritative capability responses, tolerate permissions being
revoked after rendering, and handle denial and conflict responses accessibly.

A client team may create a separate action inventory for navigation or UX test
coverage. Such an inventory is optional, belongs with that client, and must not
be described as authorization enforcement or duplicated into the API policy
registry.
