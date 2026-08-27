# 016: A service that exited non-zero gets its own section in the failure report

- **Date:** 2026-08-26
- **Status:** accepted
- **Component:** tests
- **Milestone:** M0

## Context

The integration tier's failure report exists because a failure is produced on the build machine and
read somewhere else, so `compose up failed with exit code 1` on its own costs a round trip. It gathers
`compose ps --all` and `compose logs --tail 30`, and each section is capped when rendered.

On 2026-08-26 it failed at the one job it has. A one-shot provisioner exited 1, `up` refused, and the
report said `service logs (last 40 of 74)`. The forty lines it kept were Postgres announcing it was
ready to accept connections, MinIO's startup banner, and Spark's log4j notice. **The output of the only
container that failed was in the thirty-four lines that were dropped.** The report named the failure
and discarded its cause, which cost exactly the round trip the report was built to prevent.

The mechanism is worth stating precisely, because it is not a truncation bug. `compose logs` with no
service argument is one interleaved stream across every service, so it is a *single shared budget*.
Quiet services lose to chatty ones, and a container that starts, prints one line and exits is the
quietest thing in the stack while also being the most interesting.

## Decision

Every service whose container exited non-zero gets **its own section**, with its own budget, gathered
per service rather than from the shared stream. The interleaved tail stays, because cross-service
ordering is what diagnoses a startup race; what changes is that it can no longer be the only thing
present.

Failing services are identified from `compose ps --all --format json`, reading `ExitCode` per service.
Both JSON shapes compose has emitted across versions are accepted, and every failure path returns an
empty list, because this code runs while something has already gone wrong and must never mask it.

## Alternative rejected

Raise the shared tail from 30 lines to something large enough that the failing service survives it. Its
advocate is right that it is one constant and no new code, and it would have worked for this incident.

It loses because it does not fix the mechanism, it buys headroom against it. The budget is still shared,
so the fix holds only while the ratio of chatty to quiet output stays roughly what it is today; add a
service, or a service that logs more on the day it fails, and the quiet container is crowded out again.
It also makes every *other* failure report longer in exchange, which is the cost paid on all the runs
where the shared tail was already sufficient.

## Prediction (recorded before the evidence)

I expect this to change no test outcome, because it only runs on the failure path: the suite should be
identical, green or red, with this in place. Confidence: high.

I expect the JSON parsing to be the part that is wrong, if anything is, at roughly 20%: `ExitCode` is
read from a shape I have not observed on the build machine, only reasoned about, and this repository has
now been wrong four times about what an external tool provides. The failure mode is deliberately
harmless, an empty list and a report no worse than today's, which is why it is written this way rather
than more precisely.

## Deciding evidence

Half settled, and the half that matters is not.

**"No test outcome changes": confirmed.** The build machine reached `124 passed, 0 skipped` on 2026-08-26.
The suite is identical with this in place, which is what the high-confidence half of the prediction claimed.

**"Roughly 20% the JSON parsing is wrong": unsettled, and unsettled for a reason worth naming.**
`exited_badly()` is reached only from `diagnostics()`, and `diagnostics()` is reached only when `up` has
already refused. Nothing failed, so **this code has never executed**, and the run that proves the
provisioner works is exactly the run that cannot exercise the report describing its failure. That is not
bad luck; it is the structural property of diagnostic code, which runs least often when the system is
healthiest and is most needed when it is not.

The prediction therefore stands open rather than being closed by association with a green suite. This
record is not settled by the next green run either, only by a red one, and it may sit open for a long time.
**That is preferable to recording a pass it did not earn.** The alternative — a test that forces a failure
to exercise the path — is a real option and was not taken here, because writing it after a green run is
work at the wrong milestone (`REPO_ROADMAPS.md` §8: no further scaffolding before the flagship produces a
number). It is the obvious first thing to add the next time this repository is open for work.

## What would change my mind

A compose version whose `ps --format json` omits `ExitCode`, which would mean identifying failed
containers another way rather than falling back to the shared tail.

## Consequences

Makes easy: reading a remote failure once instead of asking about it. Makes hard: nothing; the added
work happens only when something has already failed. Rules out: a report that names a failure while
discarding the output that explains it, which is the specific way this report failed.
