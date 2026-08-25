# 009: A volume records what it was built with, and `up` refuses when it disagrees

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `preflight/`, `postgres/init/`
- **Milestone:** r3-m0

## Context

Three defects in this repository's first month were the same defect. An unread `.env` (`004`), an
init directory mounted from a path Docker silently created (`004`), a login the image was never told
to create (`008`), and the credential pin that record `007` documented rather than detected, and each
produced a stack that came up, reported healthy, and was wrong. Not one of them produced an error at
the moment it was caused. Every one of them was diagnosed later, from inside a container's log, by
someone who had already lost an hour to the assumption that a healthy stack is a correct one.

`007` closed with a recovery command and better failure output. That was the right fix for the state
it found, and it left the underlying asymmetry untouched: the volume knows which credentials created
it, `.env` knows which credentials are being offered, and nothing compared the two. The comparison
was available and simply had no home, because the repository's only mechanism for a precondition was
a sentence in a runbook.

A runbook step is a hope. `make clean` was documented from the day `007` was written, and the
knowledge still arrived after the failure rather than before it.

## Decision

Make the preconditions a program, and make the two commands that would otherwise hide them depend on
it.

`preflight/` holds what has to be true before a start: the container runtime is usable, the seven
required variables have values, and the Postgres volume was initialised with the pair now in hand.
`make doctor` runs it; `up` and `up-quickstart` take it as a prerequisite in both entrypoints, so the
answer cannot be skipped by someone who did not know to ask. The package imports without a container
runtime: the classification and the comparison are pure, and exactly one check shells out.

The comparison needs a record, so `postgres/init/00-record-init-credentials.sh` writes one during the
single initialisation where `POSTGRES_USER` and `POSTGRES_PASSWORD` have any effect at all. It writes
a **salted** SHA-256 of `salt:user:password`, with the salt generated inside the volume. Unsalted, a
digest of a credential pair is a password oracle for anyone who reads a file that lives in a volume
this repository invites reviewers to keep, a worse problem than the one being solved.

Two implementations of one digest agree until the day they do not, so a test runs the shell script
under a real `sh` and compares its output against `preflight.credentials.fingerprint`.

Alongside the comparison, `READ_TIMING` classifies every required variable as `FIRST_INIT` or
`EVERY_START` with a prose consequence each, and two tests keep the table and `.env.example` exactly
in step in both directions. The classification is the part a reader needs and cannot derive: four of
the seven are pinned by a volume, three are rotatable, and only the entrypoint sources say which.
A table with no test is decoration, which is why this arrived in the same commit rather than as the
separate contract rule it was planned as.

Three statuses, not two. `UNKNOWN` exists because "cannot tell" is sometimes the honest answer (a
volume that predates the fingerprint holds no record), and it never blocks a start. Blocking it would
push a reviewer holding real history toward the one command that destroys it. `UNKNOWN` also never
becomes `OK`: a run that stops early lists the checks that never ran, by name, because a short list
of green lines reads as a clean bill of health.

### This reverses part of `007`

`007` rejected "compare `.env` against the roles in the volume" and that rejection was correct as
stated: querying roles requires connecting as the very credentials under test, so the check fails in
exactly the case it is meant to explain and cannot distinguish a wrong password from a database that
is not up yet. Reading a file the first initialisation wrote has neither problem. It needs no
connection, no running Postgres, and no credential, only the volume. The mechanism changed, so the
conclusion changed with it; `007`'s reasoning about `down` keeping volumes stands unamended.

## Alternative rejected

**Make the volume name depend on the credentials.** Derive a suffix from the pair, so a changed
password addresses a different volume. Nothing to compare, nothing to record, no script inside the
image. It is rejected because its failure mode is worse than the one it removes: changing `.env`
would silently orphan a database holding MLflow runs and Airflow history, and the stack would come up
empty and healthy. That is the exact shape of every defect this record exists to end, and a refusal
that names the recovery loses nothing by comparison.

Weaker alternatives, and why each lost:

- **Parse the image tag and the project name to run a bare `docker run`.** Restates a pin and guesses
  at a name compose already computes. `docker compose run --rm --no-deps --entrypoint sh postgres`
  makes compose resolve both, which is why the doctor is the fourth invocation site under the
  `--project-directory` rule from `004` rather than a fifth way of naming things.
- **Fail when `.env` is absent.** Exporting the variables into the environment is a supported way to
  configure this stack, and compose prefers the shell over the file. The check reports which source
  supplied each value instead of asserting a file that need not exist.
- **Keep the preconditions in `tests/conftest.py` and have the doctor import the suite.** The suite
  and the doctor need the same two answers, but pointing the dependency that way would let the
  preconditions be written to suit the suite. They moved into `preflight/`, and the arrow points one
  way only: tests to preflight, never back.
- **Move the integration tier's `describe_process` into `preflight` with everything else.** It writes
  for someone reading a CI log days later; the doctor writes for someone standing at a prompt with
  the machine in front of them. One report cannot be terse and exhaustive at once, so it stayed.

## Prediction (recorded before the evidence)

I expect the volume check to fire for real at least once on the build machine, because a volume
already exists there from the runs that produced `007` and it predates the fingerprint, so the
first honest answer it gives will be `UNKNOWN`, not `FAIL`, and that is the outcome that tests
whether three statuses were worth having. I expect the digest-agreement test to be the one that
catches a future edit, and I expect at least one more check to join this package before M2 without
the package's shape changing.

## Deciding evidence

The read-timing classification is from sources, not from a running stack: the `postgres` image's
entrypoint runs `docker-entrypoint-initdb.d` only while creating an empty data directory, and
Airflow 2.9.2's `entrypoint_prod.sh` runs `airflow users create ... || true` with `--username`
defaulting to `admin`, so with a database that already holds an admin the create is a silent no-op.
That is what makes `AIRFLOW_ADMIN_PASSWORD` first-init rather than rotatable.

Both new critical guards were falsified before being trusted. Reversing the join order inside the
shell script produced a failure naming both digests. Adding an eighth variable to `.env.example`
produced `declared in .env.example but not classified: ['MLFLOW_TRACKING_TOKEN']`. Both files were
restored and confirmed clean.

The volume comparison itself has been exercised only against constructed `VolumeState` values and a
real `sh`; no container has run it, because this machine has no container runtime. Until the build
machine runs `make doctor` against the volume that exists there, this record's claim is about the
mechanism and not about the stack.

## What would change my mind

A `postgres` image that stops honouring `docker-entrypoint-initdb.d`, or a decision to stop keeping
the volume across `down`: either removes the pin and with it the reason to record anything. If the
doctor grows past roughly a dozen checks, or starts needing a running stack to answer, it has become
a health check rather than a preflight and should be split.

## Consequences

Easy: `up` refuses instead of starting something wrong, on both entrypoints, with the recovery named
in the failure and the cost of that recovery (the MLflow runs and Airflow history inside the volume)
stated in the same sentence. The four pinned variables are documented where they are also asserted.
The suite and the doctor can no longer disagree about whether this machine is configured.

Hard: an init script inside the Postgres image is now part of the contract, and a file in the volume
is a thing that can be corrupted or absent, which is what `UNKNOWN` is for. `make up` gained a
Python dependency on a path that previously needed only Docker, and the doctor starts a throwaway
container to read one file, which costs a second or two on every start. The contract suite goes from
68 tests to 96.
