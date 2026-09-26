# 028: The deferred milestones are renumbered, and record 001 stands exactly as written

- **Date:** 2026-09-25
- **Status:** accepted
- **Component:** repo-wide
- **Milestone:** M2, maintenance
- **Amends:** record 001 (defer the registry, drift and canary milestones until two real workloads
  exist), on its milestone identifiers only and on nothing else

## Context

Record 001 defers three milestones and names them M3, M4 and M5. That numbering was retired when the
milestones were made monotonic, because it placed the cloud milestone numerically before three
milestones that precede it in every other respect. Four documents in this repository now carry the
current scheme, across six separate statements: `COMPONENTS.md` maps `infra/` to M3 and names M4 the
registry and promotion gate, M5 drift detection and the retrain trigger and M6 canary and rollback;
`README.md` states in two places that Terraform at M3 has not started; `docs/architecture.md` states
the same; and record 015 speaks of the moment M3 replaces root credentials with a real role on EKS.

Record 001 is the sole remaining site of the old numbering in this repository, and it is the one site
that cannot simply be corrected. It is published, it is cited from both `COMPONENTS.md` and
`docs/architecture.md`, and its prediction is unscored, its deciding evidence still reading that it was
decided on judgement and should be revisited after the first two interviews that reach this
repository. A reader who follows either citation therefore meets three numbers for three deferrals and
has nothing telling them which set is live.

## Decision

Record 001 is left byte for byte as it was written, and this record carries the mapping. The decision
in 001, that the registry, drift and canary work waits until there is something real to promote,
monitor and roll back, stands unchanged and is not reopened here. Only its identifiers are superseded:

| Record 001 says | The current scheme says |
| --- | --- |
| M3, registry and promotion | M4 |
| M4, drift and retrain trigger | M5 |
| M5, canary and rollback | M6 |
| M6, the cloud footprint | M3 |

This record deliberately does not touch the condition under which the deferral ends. Record 001 and
`COMPONENTS.md` require two real workloads and both flagships, while the planning documents now
require one workload from one flagship, Repo 2 having been dissolved and its number retired. That is a
question about what the gate should be rather than about what the milestones are called, and it is
settled separately.

## Alternative rejected

Edit record 001 in place. It is three numbers in one file, it would leave a single consistent set
across the repository with no indirection for a reader to follow, and it is plainly the cheaper
change. It loses on what a record is for. The records are the append-only part of this repository's
history, and the numbering a record used is a fact about the state of the plan when the decision was
taken. A record that quietly acquires today's numbers stops being evidence of what was decided and
becomes a description of what is currently believed, which the other documents already provide. The
objection is sharper here than it would be for a closed record, because 001's prediction is still
live: it is a record a future reader is expected to weigh against an outcome, and one edited after
publication is worth less for exactly that purpose.

## Prediction (recorded before the evidence)

Record 001 is the last site of the retired numbering in this repository and in the planning documents,
so a search for milestone identifiers across both should return the current scheme everywhere else
once this record lands. I expect the indirection to cost nothing in practice, because both citations
of 001 sit in documents that already carry the current numbers, and a reader arriving through either
one meets the correct scheme before meeting the record. I expect the mapping above to be consulted
once, when the registry work is eventually scheduled, and never again.

## Deciding evidence

The five surfaces named in the context were read rather than assumed, and no superseding marker for
001 existed anywhere under `docs/decisions/` before this record. The planning document that disagreed,
the component inventory in `BUILD_CONVENTIONS.md`, carried the same retired scheme as 001 and was
corrected to follow this repository, on the ground that a published repository's numbers are the ones
a reader already has.

## What would change my mind

A third numbering appearing anywhere, or a change to the deferral's release condition that moves the
milestones again. In either case the mapping stops being a single correction and becomes a moving
target, at which point this record should itself be superseded by one that states the scheme rather
than the difference between two schemes.

## Consequences

Record 001 stays quotable and its prediction stays scoreable against the outcome it was written to
anticipate, and the mapping lives in one place rather than being restated wherever the deferral is
mentioned.

The cost is real and worth naming, because this record does not modify 001: a reader who arrives at
001 directly, by file listing or by search rather than through either citation, still meets M3, M4 and
M5 with nothing on the page to warn them. A single cross-reference line in 001's header would close
that gap without touching its reasoning, its decision or its prediction, and it is not done here only
because leaving the record untouched was the narrower choice.
