# Evidence-retention reference: Phase 22 investigation

Status: clarification approved by the specification owner on 20 October 2026
and applied to disposition revision 1.7 and implementation-plan revision 1.3.
The investigation below records the wording and evidence before that amendment.

Both approved specifications and their tracked revisions were rechecked at
`82bb4ed`. Neither defines a separate evidence-file retention duration, expiry
trigger, approving authority, deletion operation, or expiry worker.

The reference occurs in `specs/disposition.md` section 14.2 and requirement
DISP-35. Section 14.2 says that supporting files follow an approved
evidence-retention policy, and conditionally requires permanent identifiers,
provenance, descriptive metadata, deletion date, deletion authority and a
deletion event if a file is subsequently deleted under that policy. That is a
preservation obligation and a reference to a policy; it does not define one.

The wording first appears in Git commit `39e5f61` (7 October 2026). It is
unchanged in the subsequent tracked specification revisions through `82bb4ed`.
There is no accompanying policy definition in the destruction extension or
elsewhere in the repository's specifications and documentation. The history
supports calling this an unresolved reference carried forward through revisions;
it cannot prove the author's original intent.

The destruction extension, sections 16 and 17.2, does explicitly require
certificates and uploaded evidence to be governed Wathiq records, stored in the
configured evidence classification's latest open root. The common retention
model resolves a root's local rule first and otherwise its effective
classification rule. This provides the existing retention mechanism for
governed records. Neither document explicitly identifies that rule as the
separate policy referenced by DISP-35 or specifies how deletion of a referenced
evidence file releases its immutable links while retaining permanent proof.

The Phase 22 implementation plan consequently overstates the contract when it
calls this an **existing approved retention policy**. A separate approved
expiry/deletion policy cannot be inferred from that sentence alone.

Phase 22 implements the defined certificate and completion behavior and preserves
evidence. It introduces no evidence-retention setting, fixed duration, timer,
purge privilege, or deletion workflow.

The specification owner approved the proposed clarification on 20 October 2026:
“I approve the proposed clarification, removing that undefined separate expiry
feature from Phase 22 while preserving protected evidence and provenance.”

The approved amendment has been applied to `specs/disposition.md` section 14.2
and DISP-35, and the Phase 22 verification scope in
`specs/disposition-implementation-plan.md`. Supporting evidence remains protected
as governed records outside the destroyed units, with permanent identifiers,
provenance and event history. A separate expiry/deletion workflow is deferred
pending an approved policy. Any future approved evidence-deletion policy must
preserve identifiers, provenance, descriptive metadata, deletion date, deletion
authority and deletion events permanently.

The originally proposed patch is retained unchanged as approval evidence at
`docs/verification/disposition-phase-22/evidence-retention-clarification.proposed.patch`;
its three scope changes are now applied. The requirement ledger retains the
historical unresolved-policy finding and records its resolution separately.
Live Arabic verification subsequently passed in the in-app browser on
20 October 2026; see `docs/disposition-phase-22.md`.
