# 007. A kept volume pins the credentials of the first run

**Status:** accepted
**Date:** 2026-08-23

## Context

The first integration run on the build machine failed with three broken idempotency tests, and
the reason was not in compose's output at all. It was in the Postgres container's log:

```
FATAL:  role "bytesofentropy" does not exist
```

`POSTGRES_USER` and `POSTGRES_PASSWORD` are read by the `postgres` image's entrypoint **only when
the data directory is empty**. On every subsequent start they are ignored, because the roles already
exist inside the volume. `postgres-data` is a named volume that `make down` deliberately keeps —
that is the whole point of `test_state_survives_down_and_up`, and record 001's reasoning about
`down --volumes` making idempotency indistinguishable from starting over.

So the two properties are the same property seen from two sides. The volume that lets the suite
prove state survives a restart is the volume that pins whatever credentials the *first* `up` on that
machine created. Change `.env` afterwards and nothing happens: the healthcheck starts asking
`pg_isready -U <new user>`, Postgres answers that no such role exists, the service never reaches
healthy, `up --wait` fails, and the tests that depend on `up` report as broken idempotency.

Re-cloning does not help, and this is the part that cost the most time. The compose project name is
derived from the directory basename, so a fresh clone into a folder named `mlops-platform` reuses
`mlops-platform_postgres-data` — the same volume, with the same roles in it. The clone is new; the
state is not.

## Decision

Keep the volume behaviour exactly as it is, and fix what the failure *says*.

`make down` continues to keep volumes and only `make clean` removes them. The recovery for this
state is one command, `make clean`, and the thing that was missing was any way to know that from
the output.

The integration tier now gathers `compose ps --all` and `compose logs --tail 30` when a compose
call fails, and carries both into the assertion message. The line above — the one that names the
missing role — is in the container log and nowhere else, so a report that reads only the failing
command's streams is structurally incapable of containing the diagnosis. The build-machine runbook
names this failure mode with its error string and its one-line fix.

## Rejected alternatives

**Make `make down` remove volumes.** Deletes the property under test. `test_state_survives_down_and_up`
would pass trivially against a stack that starts over every time, which is the failure record 001
already refused.

**Have the integration tier `clean` before it runs.** It would have hidden this, and at the price of
silently destroying whatever a developer had in MinIO and Postgres, on a suite that is supposed to be
safe to run. A test that removes state to avoid a state-dependent failure is not testing idempotency.

**Hardcode `POSTGRES_USER` so it can never drift.** Puts a credential name in the repository, does
nothing about `POSTGRES_PASSWORD` — which fails the same way and with a much less obvious message —
and makes the reviewer's `.env` a partial fiction.

**Compare `.env` against the roles in the volume before starting.** Requires an authenticated
connection as a superuser whose name is the unknown. The check needs the answer it is looking for.

## Prediction (recorded before the evidence)

I expect eight new test items, no change to any existing assertion, and `make clean` followed by
`up-quickstart` to bring the stack to healthy on a machine whose `.env` is filled in.

I expect the same class of failure from MinIO to be less likely but not impossible: it re-reads its
root credentials on every start, so a changed `MINIO_ROOT_USER` produces an authentication failure
in the tier's `mc` calls rather than an unhealthy container. If that appears, it is this record
again with a different service, and the fix is the same one command.

What would change my mind: if the gathered log turns out to be empty at the moment of failure —
because `--wait` tears containers down before the logs can be read — then the diagnosis has to move
earlier, into a `ps`-and-log capture that runs on a timer during `up` rather than after it.

## Deciding evidence

Measured here: **65 passed, 8 skipped**, up from 61 / 8, with the report rendering the postgres case
end to end from synthetic input. The gathering itself cannot be measured on this machine — it needs
a runtime — which is the same limitation as record 006 and is why the failure path is exercised
through a pure function rather than only through a live stack.

## Consequences

The eight skips on a runtime-less machine are unchanged; the three counts in the runbook become
65 / 8, 70 / 3 and 73 / 0.

Anyone who changes a credential in `.env` after a first `up` must run `make clean`. That is now
stated where it is needed rather than left to be rediscovered, and the failure names itself if it is
not.

The general lesson is one the earlier records keep circling: the report is part of the contract. A
test that fails without saying why has told you only that a machine you cannot see is unhappy.
Records 005 and 006 both cost a round trip for the same reason, and this one is the first where the
answer was sitting in a log the assertion could have read.
