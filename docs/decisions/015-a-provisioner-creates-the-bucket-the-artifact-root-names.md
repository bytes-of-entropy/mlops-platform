# 015: A one-shot provisioner creates the bucket the artifact root names

- **Date:** 2026-08-25
- **Status:** accepted
- **Component:** compose
- **Milestone:** M0

## Context

MLflow was configured with `--default-artifact-root s3://mlflow/` against `http://minio:9000`, and
**nothing anywhere created the `mlflow` bucket.** No `mc mb`, no init step, no call in compose, in
preflight or in the DAG. MinIO does not create buckets on write, so the first `log_artifact` would have
failed against a stack that reported entirely healthy.

It survived a green M0 for a specific and repeatable reason: the smoke DAG logs a **param and a metric**,
and both of those go to the Postgres-backed tracking store. Nothing in the smoke path, and nothing in the
120-test tier, ever wrote an artifact. The artifact path had never been walked. It was found by a human
opening the MinIO console and looking at the bucket list.

This is the fourth instance of one shape in this repository: **a configured thing nobody had exercised.**
Records 005, 011 and 012 were the other three, all about claims regarding pinned images. This one is a
claim about a configured destination, and the lesson is the same one: a healthcheck says a service
answers, and says nothing about whether the thing it is configured to talk to exists.

## Decision

A one-shot `minio-init` service creates the bucket and exits. MLflow depends on it with
`service_completed_successfully`, so the server cannot start before its artifact root exists.

Three details are load-bearing rather than incidental:

- **Same image and same pin as `minio`.** That image already ships `mc`, which its own healthcheck runs,
  so provisioning introduces no new registry reference and nothing further to keep pinned. A dedicated
  `mc` image would have been a second moving part for no additional capability, and a tag invented
  without verifying it exists is a broken first run.
- **`MC_HOST_spine` rather than `mc alias set`.** `mc` reads its target from that variable, so no
  credential appears in a command line, in this service's argv or in `ps`. The first draft passed them as
  `$$`-escaped shell variables, which kept them out of the rendered `config` output but tripped the
  inline-credential contract test; the variable form satisfies that test the same way every other
  credential in the spine does, and is better besides.
- **No `restart` policy.** A provisioner that restarts never completes, so the condition waiting on it
  would never fire and `up --wait` would sit until its timeout and then blame MLflow.

## Alternative rejected

**Have MLflow create its own bucket at start-up.** Its advocate has a real case, and it was briefly the
recommendation here: the built image already carries `boto3` for exactly this connection, no service is
added, the quickstart envelope is untouched, and no contract needs generalising. It is also cohesive, in
that the component needing the bucket makes it.

It lost on **least privilege**. Creating the bucket at MLflow's start-up means the MLflow role needs
`CreateBucket` permanently, on every boot, forever. With a provisioner, only that step needs it and MLflow
is left needing read and write *inside* one bucket. Locally both run as MinIO root so the difference is
invisible; the moment M3 replaces root credentials with a real role on EKS, the difference is a
`s3:CreateBucket` grant on a serving role that a reviewer would be right to question. A second argument
reinforced it: M2 gives Spark a reason to write to object storage, so a second bucket is plausibly coming,
and with the rejected option either MLflow starts creating buckets it does not own or the second consumer
grows its own copy of the logic.

## Prediction (recorded before the evidence)

Everything except the container behaviour is verified here: the full local gate is green, and the envelope
figures below are computed rather than estimated. What no machine here can check is whether the
provisioner actually runs, because this machine has no container runtime. So:

- **Probability the round trip passes on the first run on the build machine: about 70%.** The logic is
  simple and the gating is a standard compose condition, but three details are unverified against the real
  image at once.
- **Most likely single failure, at roughly 15%: the entrypoint override.** `entrypoint: ["/bin/sh", "-c"]`
  assumes that image provides `/bin/sh`. If it does not, the container exits immediately with an exec
  error, which is loud, unambiguous and a one-word fix to `/bin/bash`. This is the same class of
  assumption that record 011 was written about, made deliberately this time and written down.
- **Second most likely, at roughly 10%: `mc mb --ignore-existing` being spelled differently** in that
  release, which fails with a usage message rather than anything subtle.
- I do **not** expect the `MC_HOST_spine` mechanism to fail; it is long-standing `mc` behaviour.
- I do **not** expect the quickstart envelope to be exceeded, because it is already measured: peak
  **3840 MiB** and **2.00 CPU**, unchanged from before this service existed.

## Deciding evidence

The tier ran on the build machine on 2026-08-26 and **failed**: `3 failed, 116 passed, 5 errors`, with
every one of the eight traced to one cause, `service "minio-init" didn't complete successfully: exit 1`,
which fails `up` and errors everything downstream of it.

Scoring the prediction above, unedited:

- **"About 70% the round trip passes on the first run": wrong.** It did not pass.
- **"Most likely single failure, roughly 15%, the entrypoint override": refuted.** `compose ps` shows
  the container ran `"/bin/sh -c mc mb --…"`, so that image does provide `/bin/sh`. The assumption I
  flagged as likeliest to break was the one that held.
- **"Second most likely, roughly 10%, `mc mb --ignore-existing` being spelled differently": correct, and
  it was the cause.** Run in the foreground, `mc` printed its *top-level* help into an interactive pager
  and exited 1. The 10% branch was the right mechanism at the wrong odds: I ranked a guess about a shell
  above a guess about a CLI contract, and the CLI contract is the thing neither I nor any test here had
  ever executed.
- **"The `MC_HOST_spine` mechanism will not fail": unsettled.** `mc` never got as far as resolving an
  alias, so this was neither confirmed nor refuted and is now moot.
- **"The quickstart envelope will not be exceeded": confirmed on the build machine.** The whole contract
  tier passed there, 116 tests including the amended envelope and the new one-shot contracts. The design
  held; only the container behaviour failed.

**The decision stands and the implementation changed.** A one-shot provisioner is still the right shape,
for the least-privilege reason that decided it, and none of that reasoning depended on `mc`. What changed
is the tool: the provisioner now runs `ensure_buckets.py` in the image this repository already builds for
MLflow, where `boto3` already lives.

The reason is worth recording, because it generalises past this bug. `mc mb --ignore-existing` was chosen
because the MinIO image ships `mc`, so it needed no new dependency; that was true and irrelevant. It cost
a full cycle on the build machine to discover a flag spelling, and the same job in `boto3` is one call
with two documented error codes meaning "already there" and everything else raised, which can be reasoned
about before running rather than after. It also needs no config file, no alias resolution and no TTY,
three things the CLI wanted and none of which this job needs. **Reusing a tool that happens to be present
is not the same as reusing a contract you can predict**, and this repository has now been wrong four times
about what an external image provides. The pattern is the point: prefer the interface whose failure modes
are enumerable.

Verified locally after the change: `ruff`, `ruff format`, `mypy` over 24 files, and `111 passed, 13
skipped` across 124 collected. The container behaviour is again unverified, which is the honest position:
this is the second attempt at a step no machine here can execute.

**The second attempt ran green.** The build machine reported `124 passed, 0 skipped` on 2026-08-26: the
provisioner created the bucket, MLflow started behind `service_completed_successfully`, and
`test_an_artifact_round_trips_through_minio` logged an artifact through the MLflow client, read the object
back out of MinIO with `boto3` and compared the bytes. **The artifact path has now been walked**, which is
the sentence this record existed to make true and the one a green M0 could not have produced.

Two things follow that are worth separating from the pass itself. `MC_HOST_spine` is now permanently
unsettled rather than temporarily so: `mc` is gone, so the prediction about it can never be scored, and it
is recorded as unresolved rather than quietly dropped. And the count matched the number
`docs/SETUP.md` had derived for it in advance, `124`, which is the first time a derived row in that table
has been checked against a real run.

## What would change my mind

For the provisioner: a second consumer needing a bucket with different credentials, which would argue for
per-consumer provisioning rather than one shared step. For the envelope model: a one-shot that genuinely
must be larger than what it gates, which `test_a_provisioner_is_smaller_than_what_it_gates` would catch
and which would mean the peak has to absorb the difference rather than hide it.

## Consequences

**Two contracts were generalised, and one of them was over-approximating.**

`test_every_service_declares_a_healthcheck` becomes
`test_every_service_is_either_healthchecked_or_waited_for`. The old rule was right about what it defended,
`up --wait` returning before the stack is usable, and wrong to assume a healthcheck is the only way to
defend it. Completion is a *stronger* gate: a healthcheck says a service answers, completion says the work
is finished. Two assertions close the gap this opens: a service carrying neither still fails, and a
service waited on for completion may not declare a healthcheck, because something waiting for a
long-running service to complete is a hang rather than a dependency.

The quickstart envelope now charges a **peak rather than a sum**. Summing every declared limit assumes
every service is resident at once, which a one-shot is not: MLflow cannot start until it exits. The sum
was a conservative over-approximation that was invisible while it happened to hold, and it stopped holding
exactly when the CPU total sat at 2.00 against a 2.0 budget with no headroom for anything. A one-shot is
now charged what it costs *over* the cheapest thing it blocks, which is zero in the ordinary case where a
provisioner is smaller than its consumer. **This fix did not need the envelope relaxed; it exposed that
the envelope was measuring the wrong quantity.**

Makes easy: a second bucket, one line. Makes hard: nothing measurable. Rules out: MLflow starting before
its artifact root exists, and a future service that neither answers nor finishes.
