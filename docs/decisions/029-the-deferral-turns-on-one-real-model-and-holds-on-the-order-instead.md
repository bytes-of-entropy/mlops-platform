# 029: The deferral turns on one real model, which now exists, and holds on the order instead

- **Date:** 2026-09-25
- **Status:** accepted
- **Component:** repo-wide
- **Milestone:** M2, maintenance
- **Amends:** record 001 (defer the registry, drift and canary milestones until two real workloads
  exist), on its release condition only. Record 028 carried its numbering and left this open
  deliberately

## Context

Record 001 releases the deferral when both flagships exist and there are two real workloads, and
`COMPONENTS.md` repeats the count. That set no longer exists. Repo 2 was dissolved and its number
retired, its components folding into Repo 1's `narrate/` at its M6, so the portfolio has one
flagship, Repo 1, with this platform as the substrate it deploys onto and Repo 4 being profile and
writing. A condition naming two workloads from both flagships is therefore not a strict gate but a
void one: nothing that can now happen satisfies it.

The planning documents have already moved, in five statements. `REPO_ROADMAPS.md` section 4 defers
until Repo 1 gives the platform a real workload; its M4 exit criterion asks for a real model, Repo
1's; section 8 says the three are worth building only once there is a real model to promote, monitor
and roll back; the diagram in that section says on a real workload; and `BUILD_CONVENTIONS.md`
section 6 says a real workload to carry. All five are singular.

Record 001's own reasoning was never plural either. Its context objects that a promotion policy
invented before there is a model to promote encodes guesses about a workload nobody has run, and its
rejected alternative objects that a drift trigger tuned against synthetic data proves the plumbing
works and says nothing about whether the trigger fires when it should. One real model satisfies both
arguments. The count of two described the shape of the plan at the time, when two flagships were
planned, rather than anything the argument required.

Repo 1's M1 closed at `v0.2.0` with its evidence in that repository's `docs/results.md`:
precision@1% of 0.79 on a 95% interval of [0.68, 0.88] from tuned gradient boosting. The model the
condition was waiting for exists.

## Decision

The release condition is one real model from Repo 1, and it is met. The deferral nonetheless
continues, on a different reason which this record states rather than implies: the cross-repo order
in `REPO_ROADMAPS.md` section 8 places this repository's M4, M5 and M6 after Repo 1 publishes, and
Repo 1 has not published. The two reasons are kept apart because they expire at different times, and
because until this record the deferral was justified by the absence of something that now exists.

## Alternative rejected

Leave the condition as written and read it generously, counting Repo 1's tabular baseline and its
later Spark and graph work as two workloads, or counting this platform's own smoke DAG as the
second. Preserving the wording of an accepted and published record has real value, and a stricter
gate is the conservative direction for a repository whose discipline is mostly about not
over-claiming.

It loses on what that strictness is actually worth. A condition no achievable state satisfies does
not constrain the decision it governs, it hands the decision to whoever is reading and leaves the
record as cover rather than as a constraint. The generous readings make the problem plain, because
each one requires inventing a second workload the record did not mean, which is the reasoning
backwards from a preferred conclusion that this record set exists to catch.

## Prediction (recorded before the evidence)

The next time this deferral is revisited, the question asked will be whether Repo 1 has published
rather than whether a real model exists, because this record moves the live reason to the order. I
expect the registry work, when it starts, to promote the M1 model at `v0.2.0` rather than to wait
for a second workload, and I expect no further restatement of the condition before Repo 1 publishes.
If that model turns out to be unpromotable for a reason nobody has anticipated, this prediction has
failed and the reason belongs in its own record rather than in a revision of this one.

## Deciding evidence

Repo 2's dissolution and the retirement of its number, which is what makes the plural unsatisfiable
rather than merely demanding. Five statements in the planning documents already in the singular
against two here in the plural. Record 001's own context and rejected alternative, both reasoning
about one model. And Repo 1's `v0.2.0` tag with the write-up committed at it.

## What would change my mind

A second real workload arriving, whether a second flagship or a workload belonging to this platform,
would make the plural meaningful again, and this record could then retire rather than be superseded.
Repo 1 publishing would retire the ordering reason and leave nothing deferring this work at all, at
which point it is either scheduled or the deferral is re-justified on a reason not yet written down.

## Consequences

The gate is checkable and the stated reason for the hold is the one actually operating. That is
worth more than it sounds, because the previous arrangement allowed the work to be deferred
indefinitely while pointing at a condition about models, and indefinite deferral behind a stated
condition is a failure this repository already has on its record once.

The cost is that the cover is gone, which is the intended effect rather than a side effect. Once
Repo 1 publishes there is no documented reason left to defer the registry, drift and canary work, so
it is scheduled, or a new reason is written down and defended on its merits.
