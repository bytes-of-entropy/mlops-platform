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

Empty for the container half until the tier runs. Filled in a later commit that does not touch the
Prediction above.

Verified here already: `ruff`, `ruff format`, `mypy` over 24 files, and `111 passed, 13 skipped`, the two
new integration tests among the skips because they need a runtime. The envelope is computed as peak
3840 MiB and 2.00 CPU with `minio-init` charged **zero** on both, which is the model below working as
intended rather than a coincidence.

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
