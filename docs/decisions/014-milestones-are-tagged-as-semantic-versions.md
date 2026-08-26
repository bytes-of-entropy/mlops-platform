# 014: Milestones are tagged as semantic versions, and M0 stays a release candidate until the tier is green

- **Date:** 2026-08-25
- **Status:** accepted
- **Component:** repo-wide
- **Milestone:** M0

## Context

The milestone tag read `r3-m0`, where `r3` identified this repository inside a planning document that is
not published alongside it, so a reader outside the project holds no key for it. This repository has a
second reason the graph repository does not: M2 publishes Helm charts that the two flagship repositories
pin by release rather than tracking. A consumer pinning a chart needs a version it can order, compare and
range over. A milestone label cannot be any of those, so a version was arriving here regardless.

There is also a claim problem the old tag had independently of its name. It sat twenty-four commits behind
HEAD, at a commit that predates the smoke DAG whose own message says it closes M0, and M0's exit condition
is a green integration tier that has never been green on any machine. The tag asserted a closed milestone
that no run has demonstrated.

## Decision

Milestones are tagged as annotated semantic versions, each closed milestone taking the next minor, and
`v1.0.0` reserved for the commit at which this repository's publication gate passes.

M0 is tagged `v0.1.0-rc.1` rather than `v0.1.0`. Every component M0 needs is committed and the contract
tier is green, but the six integration tests that start the stack and assert the spine end to end have
never run green. A pre-release is exactly the claim the evidence supports: code complete, not
demonstrated. `v0.1.0` is tagged at the commit where the tier first runs green, which may be this one, and
if it is then the two tags sit together and the rc is the record of why that was not known in advance.

## Alternative rejected

Tag `v0.1.0` now and treat the tier as a known outstanding defect. Its advocate is right that the code is
complete, that the one identified cause of every observed failure is already fixed by record 013, and that
a repository whose tags trail its work reads as under-confident. It loses because it inverts the one
discipline this repository is built on. The exit condition for M0 was written before the work and names a
green tier; a tag that declares M0 closed while that condition is unmet moves the gate instead of meeting
it, and the gate not moving is the whole mechanism. A pre-release costs one suffix and concedes nothing.

## Prediction (recorded before the evidence)

The next run of the integration tier on the build machine, with record 013's fix in place and no further
code change, settles this. My prediction, written before that run:

- Probability the tier reaches `120 passed, 0 skipped` on the first attempt: about 40%. Record 013 fixed
  the one cause every observed failure traced to, but that run never got far enough to exercise what came
  after it, so an untested path is being reached for the first time rather than a fixed one being retried.
- Most likely single failure, at roughly 35%: the Airflow image not shipping `psycopg2`. The identical
  assumption was already false for MLflow and produced record 011, and it is documented here as assumed
  and never checked, which is the same shape of gap that failed once.
- The two unexplained skips in the best run so far resolve as accounting rather than as a defect: one is
  the Makefile-parity skip when GNU Make is absent, and I expect the second to be the same class. Around
  75%.
- I do not expect a Spark failure. The `UnknownHostException` in the earlier run was debris from an
  aborted network setup rather than a Spark fault, and record 013 removes the abort.

## Deciding evidence

The tier ran on the build machine on 2026-08-25 and reached `120 passed, 0 skipped`. M0 is closed and
`v0.1.0` is tagged. Scoring the four predictions above, none of which has been edited:

- **`120 passed, 0 skipped` on the first attempt: predicted at about 40%, and it did not happen.** The first
  attempt returned `118 passed, 2 skipped in 267.77s`, with zero failures and zero errors. The shortfall was
  not in the tier at all: two preflight tests execute the Postgres init script and compare its digest against
  the Python implementation's, and they skip without `sh`, `sha256sum` and `od`. Git for Windows ships all
  three, and PowerShell did not have that directory on `PATH`. Adding it made both run, and the next full run
  reached the pass condition. So the number was missed, for a reason the prediction was not about, and the
  honest reading is that it was wrong rather than nearly right.
- **Airflow not shipping `psycopg2`, predicted at about 35% as the most likely single failure: refuted.**
  `docker run --rm apache/airflow:2.9.2-python3.11 python -c "import psycopg2; print(psycopg2.__version__)"`
  returns `2.9.9 (dt dec pq3 ext lo64)`. The reasoning was sound, since the identical assumption was false for
  MLflow and produced record 011, and the conclusion was still wrong.
- **The two unexplained skips being accounting rather than a defect, predicted at about 75%: correct as to
  class, wrong as to identification.** They were accounting. They were not the Makefile-parity skip this
  record guessed at; they were the two POSIX-shell tests above, a different mechanism reached by a different
  route.
- **No Spark failure: correct.** None occurred, and the `UnknownHostException` from the first run did not
  recur once the port collision was gone, which is what record 013 said of it.

One of four clean, one refuted, one half right, one missed. That distribution is why this section is worth
more than a summary written afterwards would have been.

The `v0.1.0-rc.1` tag stays where it is rather than being deleted. It is the record that M0 was code complete
before it was demonstrated, and removing it would destroy the only evidence that the distinction was drawn in
advance rather than claimed after the fact.

## What would change my mind

For the versioning half: anything that reads tag names programmatically, or a consumer that needs to pin a
milestone rather than a version. For the release-candidate half: nothing short of a green tier, which is
the point of stating the condition rather than judging it.

## Consequences

Makes easy: a chart version the flagship repositories can pin and range over, and a tag whose suffix tells
a reader that M0 is not yet demonstrated without their having to find the sentence that says so. Makes
hard: nothing mechanical, since no tooling here reads a tag. Rules out: closing M0 by assertion. The
promotion from `v0.1.0-rc.1` to `v0.1.0` now requires a run, which is the constraint worth buying.
