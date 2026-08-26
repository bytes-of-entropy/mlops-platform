# 011: What is inside an image is a claim, and two of ours were wrong

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `compose/`, `images/`, `tests/`
- **Milestone:** M0

## Context

The first start on a machine with a container runtime failed. Not on credentials (`009`'s doctor
passed all three checks and Postgres came up healthy), and not on anything the compose contract
asserts. Six of seven services reported healthy and MLflow never did.

Two separate defects were behind it, and they are the same mistake twice.

The first: MLflow's healthcheck ran `curl`, and so did Airflow's. This file already knew better.
The Spark healthcheck carries a comment recording that its image ships `wget` and no `curl` at all,
and that a healthcheck naming a binary the image lacks "never reports healthy, so a `--wait` would
sit for the full timeout and read as a broken service rather than a broken healthcheck." That
finding was written down, applied to one service, and not applied to the other two.

The second, and the one that actually killed the start: the published MLflow image installs MLflow
and nothing else. A tracking server pointed at Postgres needs a DBAPI driver and one pointed at
S3-compatible storage needs an S3 client. Neither is in the image, so `mlflow server` exits at
import before it ever binds a port:

```
ModuleNotFoundError: No module named 'psycopg2'
```

Both defects survived every guard this repository has. The image is pinned, the credential is
interpolated with no default, the healthcheck is declared, the dependency waits for health rather
than start, the volume is named, the mount is read-only. Every one of those checks passed on a
service that could not start, because all of them describe the compose file and none of them
describe what is inside the images the compose file names.

This is the same shape as the DAG import rule in `010`, a dependency that exists only in the mind
of whoever wrote the file, and it went unnoticed for the same reason: nothing had run.

## Decision

**A healthcheck may only name a binary the image is recorded as providing.** `tests/` now holds an
explicit per-image table of what was verified to be inside each pinned image, and the healthcheck
of every service is checked against its own image's entry. An image with no entry fails rather than
passing unchecked, so adding a service forces the question rather than allowing the assumption.

**Both remaining healthchecks became standard-library probes**, not `wget`:

```yaml
test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()"]
```

Swapping `curl` for `wget` would have fixed the symptom while keeping the bet. Both of these images
are Python images by construction: one is `apache/airflow:2.9.2-python3.11`, the other is built on
MLflow's own image, so the interpreter is the one dependency they cannot be missing. Nothing here
now depends on which utilities a base image happened to include, which means a base-image bump
cannot turn a healthy service into an unhealthy one.

**The spine gains exactly one built image**, in `images/mlflow/`, and it is four lines: `FROM` the
pinned upstream tag, then `pip install` two exactly-pinned packages. The service keeps an `image:`
key with a local pinned tag alongside its `build:` context, so the tag is still what `ps` reports
and still what the pin check reads, and a second new contract rule requires that any service which
builds names both a tag and a pinned `FROM`.

`up` and `up-quickstart` now pass `--build`, and so does the integration tier's single compose
invocation, so no path can start a stale image. A separate `build` target exists so the cost can be
paid outside a timed window, since the integration tier bounds every compose call it makes, and a cold
build is minutes of that budget spent on work that is identical every time.

### What this deliberately does not fix

The `mlflow` bucket still does not exist. `--default-artifact-root s3://mlflow/` names a bucket
nothing creates; the server does not touch it at start-up and the smoke DAG logs params and metrics
only, so neither the start nor the M0 gate depends on it. `boto3` now being present makes the first
artifact write possible rather than certain. Creating the bucket needs an init container running
`mc mb`, which is the same decision as scoping MLflow's MinIO credentials away from root: one
change, deliberately not made in passing.

One assumption of the same family remains unverified: Airflow is configured with
`postgresql+psycopg2://`, and whether the Airflow image ships that driver has been assumed, not
checked. It is the next thing to run on the build machine, not something to reason about here.

## Alternatives rejected

**`pip install` in the container command.** This is the third time this idea has been rejected:
`005` for the Spark image, `010` for the DAG's MLflow client, now here. It makes the first `up`
depend on PyPI resolving today, and it re-pays the cost on every restart of a service whose whole
purpose is to be boring.

**`mlflow[extras]`.** Pulls a large tree of transitive dependencies, none of them pinned by us, to
obtain two packages we can name. A wide unpinned install to avoid a narrow pinned one is the wrong
trade in a repository whose claim is reproducibility.

**`postgresql+pg8000://`, avoiding the C extension.** `pg8000` is not in the image either, so this
does not remove the build; it only changes which package the build installs, and picks the less
travelled driver while doing so.

**SQLite for MLflow's backend store.** `sqlite:///...` needs no driver at all and would have had
the stack up in one line. It also deletes half of what `010` defined the M0 crossing to be: the
same run id appearing as a Postgres row is the evidence that MLflow reaches its backend store. A
green gate that no longer proves the thing it was written to prove is worse than a red one.

**`wget` instead of `python` in the healthchecks.** Correct for these two images today, and still a
claim about base-image contents that the new contract rule would then have to keep verifying.

**Deferring the image to M1, as `images/` was planned.** The alternative to building it at M0 is
not closing M0. The plan said builds start at M1; the evidence says the spine does not stand up
without one.

## Prediction (recorded before the evidence)

I expect the build to succeed and MLflow to come up healthy, and I expect the next failure to be
Airflow, either the same driver question, or the smoke DAG's REST payload shape, which `010`
already predicted would fail once before passing. I expect `psycopg2-binary==2.9.9` and
`boto3==1.34.131` to both resolve; if either does not, the build fails loudly at a named version,
which is the behaviour a pin is for. I do not expect the bucket gap to surface at M0.

## Deciding evidence

**From a running stack, for the first time in this repository.** Every earlier record in this
directory was reasoned on a machine with no container runtime. This one was not:

```
docker logs mlops-platform-mlflow-1 --tail 80
  ModuleNotFoundError: No module named 'psycopg2'
docker exec mlops-platform-mlflow-1 python -c "import psycopg2, boto3"
  ModuleNotFoundError: No module named 'psycopg2'
```

The second command is the decisive one: it asks the interpreter inside the image directly, so the
answer is not an inference from a traceback about what the server was doing.

Both new contract guards were falsified before being trusted. Restoring `curl` to the MLflow
healthcheck produced `mlflow healthchecks with curl, which ghcr.io/mlflow/mlflow:v2.13.0 is not
known to provide (verified: python)`. Unpinning the Dockerfile's `FROM` to `:latest` produced
`builds FROM ghcr.io/mlflow/mlflow:latest, which is not a pin`. Both files were restored and the
suite confirmed green afterwards.

The healthcheck defect is fixed on evidence of the mechanism rather than evidence of the symptom:
whether `curl` is absent from the MLflow image specifically was never established, because the
driver failure killed the server before the healthcheck could matter. The rule stands on the Spark
finding, which was established, and on the fact that a stdlib probe cannot be wrong either way.

## What would change my mind

A published MLflow image that includes the drivers for the stores its own CLI flags accept, which
would make `images/mlflow/` an empty wrapper worth deleting. A second built image arriving, at
which point the per-image table of provided binaries wants to move next to the Dockerfiles rather
than living in the test tree.

## Consequences

`images/` begins at M0 rather than M1, and the M0 gate now includes a build. The suite goes from
103 tests to 105 and gains a rule that reads a Dockerfile, which is the first test in this
repository to read anything outside `compose/`, `preflight/`, `tests/` and `airflow/dags/`.

The build machine gains a step: `make build` before the timed run. A first build is a pull of the
upstream image plus two wheels, and every build after it is cached.

`COMPONENTS.md` moves `images/` from planned to built, and it becomes the first entry in the commit
order rather than an addition to the end: the compose file names the tag it builds, so the
Dockerfile has to exist before the file that references it.
