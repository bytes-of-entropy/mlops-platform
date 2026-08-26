# 010: One DAG crosses the spine, and that is what closes M0

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `airflow/dags/`, `tests/`
- **Milestone:** M0

## Context

Everything M0 asserts about the spine is asserted about each service on its own. Every image is
pinned, every service declares a healthcheck, every dependency waits for health, the cycle is
idempotent, and the preflight refuses a start that would be wrong. All of it true, and none of it
about whether any two of these containers can reach each other. A healthcheck is a service answering
its own port; seven of them passing is seven services that are individually alive.

So the gate had a hole in the middle, and `COMPONENTS.md` had recorded the hole as a plan: the
`airflow/dags/` row said M1 and "empty until a flagship has a pipeline worth scheduling". That
sentence is right about pipelines and wrong about wiring. It defers the wrong thing: a *pipeline*
needs a workload and therefore a flagship, but *proof that the wiring works* needs neither, and
deferring it means the milestone that claims a working spine closes without anything having crossed
it. There was no record making that trade, which is how a defer becomes a habit.

## Decision

One DAG, one task, and the smallest write that touches everything: `airflow/dags/m0_smoke.py`
creates an MLflow experiment, opens a run, logs one param and one metric, and marks it finished.
Airflow parsing it, Airflow executing it, MLflow accepting the writes and Postgres holding the row
are four boundaries in one artefact, and a failure anywhere along it is a failed task rather than a
mystery in a log.

It calls the MLflow REST API through the standard library. The Airflow image is pinned and has no
install step, so `import mlflow` in a DAG would pass the formatter, the linter and review, then fail
at task-run time inside the container, a dependency that exists only in the mind of whoever wrote
the DAG. That generalises past this file, so it is a rule rather than a habit:
`test_the_dag_imports_nothing_the_image_does_not_ship` allows Airflow and the standard library and
nothing else.

**Asserted at the far end, not the near one.** MLflow's API reporting a `FINISHED` run proves Airflow
reached MLflow. The same run id turning up in the Postgres `runs` table proves MLflow reached its
backend store rather than answering from memory until the next restart. The near-end assertion alone
would leave the more expensive half of the path unproven, which is the same mistake as trusting a
healthcheck.

**Run synchronously, with `airflow dags test`.** A manual trigger plus a poll would additionally
prove the scheduler notices new work, and would make the assertion depend on how long that takes on
the machine of the day. `up --wait` already gates on the scheduler being alive, so the flaky version
buys almost nothing and costs a test that fails at slow moments and reports a broken spine.

**The contract tier reads the DAG as text.** It imports Airflow, which lives in an image and
deliberately not in this repository's dev dependencies, since installing a scheduler to check a file is a
worse trade than parsing it. So `tests/dagfile.py` is the single reader, and both tiers take the
dag_id, the experiment name, the param and the metric from the file that declares them. Declared
once and read twice, a rename stays consistent; written out again in a test, a rename breaks nothing
on the authoring machine and everything on the one with Docker.

`COMPONENTS.md` moves the `airflow/dags/` row to M0 and states the split explicitly: this folder owns
smoke coverage at M0 and real pipelines when a flagship has one.

### What this deliberately does not prove

MinIO is not touched. Logging an artefact goes through the artifact store rather than the tracking
API and would need an S3 client the Airflow image does not ship, so the object-storage leg of the
spine is still asserted only by the idempotency tier's own MinIO round-trip. Stated in the DAG's
docstring as well as here, because a smoke test that overstates its reach is worse than no smoke
test: it converts an unknown into a false assurance.

## Alternative rejected

**Build a small image with `mlflow` installed and use the client.** Fifteen lines of DAG become five,
the client handles the experiment-already-exists case, and the code looks like the code a reader
would write at work. Rejected on milestone boundaries: `images/` is M1, and this would put an
unreviewed Dockerfile and a second pinned base image into M0 to save ten lines. The weaker version of
the same idea, `pip install mlflow` in the container at start-up, is worse than it looks, because it
makes the first `up` on a machine depend on PyPI resolving today, which is exactly the property
`005` was written about.

Weaker alternatives, and why each lost:

- **A real pipeline now, reading a real dataset.** There is no dataset here, so it would be a
  fictional one, in the folder that is supposed to hold real ones. A fake pipeline is not a smaller
  version of a real one; it is a different and worse artefact.
- **Trigger the DAG and poll for success.** Covered above: proves one more thing, in exchange for a
  timing dependency in the assertion.
- **Query MLflow from the host's published port.** Simpler than an `exec`, and it tests the port
  publication too, which is a separate claim that belongs to whoever writes it, not something to
  smuggle into this one. The query runs inside the container, over its own loopback.
- **Let the smoke DAG be scheduled.** A timer would fill the metadata database with proof of nothing
  and make `runs` grow on any machine left running. `schedule=None`, asserted.

## Prediction (recorded before the evidence)

I expect the import rule to be the one that earns its place, because the natural next DAG someone
writes reaches for a library. I expect the first real run on the build machine to fail once before it
passes, most likely on the MLflow REST payload shape rather than on the wiring, since the payloads
here were written from the API documentation and never executed. I expect the MinIO gap to be closed
at M1 by an image that has an S3 client, not by this DAG growing.

## Deciding evidence

None from a running stack: this machine has no container runtime, so the DAG has never been parsed by
an Airflow or executed by anything. Both new contract guards were falsified before being trusted:
adding `import mlflow` produced `the smoke DAG imports ['mlflow'], which the pinned Airflow image
does not ship`, and deleting `MLFLOW_TRACKING_URI` from the compose file produced `the smoke DAG
reads MLFLOW_TRACKING_URI, which the airflow service does not set`. Both files were restored and
confirmed clean.

The REST payloads are from MLflow's HTTP API documentation for the 2.x tracking server. Until the
build machine runs the integration tier, this record's claim is about the shape of the proof rather
than about the spine.

## What would change my mind

An Airflow release that removes `dags test`, which would force the trigger-and-poll shape and with it
a timing dependency worth reconsidering. A flagship pipeline arriving in this folder, at which point
the smoke DAG's job is done by something real and it should be deleted rather than kept as a second
thing to maintain. Or MLflow gaining a tracking-API path to artefacts, which would let one DAG cover
the MinIO leg as well and make the gap above worth closing here.

## Consequences

Easy: M0 closes on something crossing the spine rather than on seven services each answering their
own port, and the claim is checked at both ends of the path. The `airflow/dags/` folder stops being a
`.gitkeep` and its milestone row stops promising a deferral nobody recorded. A rule now exists for
DAG dependencies, which is the constraint every later DAG in this portfolio will meet first.

Hard: the full profile is now load-bearing for a test, so the integration tier needs roughly 20 GB
rather than the quickstart's 4, so the M0 gate can no longer be run end to end on a small machine, and
the module brings that stack up once and shares it across three tests to keep the cost bearable. The
DAG is Python that no local suite can execute, which is why so much of it is asserted by reading. The
contract suite goes from 96 tests to 103 and the integration tier from 8 to 11.
