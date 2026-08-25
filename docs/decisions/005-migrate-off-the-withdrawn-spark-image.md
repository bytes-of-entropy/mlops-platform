# 005: Spark runs on the Apache image, and only inside a container

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `compose/`
- **Milestone:** r3-m0

## Context

`./make.ps1 up-quickstart` failed on the build machine with
`failed to resolve reference "docker.io/bitnami/spark:3.5.1": not found`. Nothing in the
repository had changed and no step had been skipped. The image was withdrawn by its publisher:
Bitnami stopped publishing community Debian images on 28 August 2025 and deleted the public
`docker.io/bitnami` catalogue on 29 September 2025, moving versioned tags to a `bitnamilegacy`
namespace that its own notice describes as receiving no further updates or support and as
suitable only for temporary migration.

The interesting part is what the pin did and did not buy. This repository pins every tag
deliberately, and the pin worked exactly as designed: it made the build reproducible. It did
not make the image *available*, and a digest pin would have been no better: a digest names
content inside a repository, and the repository is what was deleted. Reproducibility and
availability are separate properties with separate defences. Pinning defends against drift; the
only defence against withdrawal is a different publisher or a registry you control.

The failure also reopened a question the repository had been carrying implicitly: which Python
runs Spark. There are three, and they are not interchangeable.

| Where | Version | Set by | Can it move? |
|---|---|---|---|
| The venvs on both machines | 3.12.10 | `requires-python = ">=3.11,<3.13"` | Yes, but 3.12 is the current choice |
| A host `pyspark` install, if there were one | 3.8–3.11 | PySpark 3.5.x metadata; 3.5.8 and 3.5.9 did not widen it, and the 3.5 line never will | No |
| Python *inside* the Spark image | 3.10 | every `spark-docker` tag through 4.2.0 is `FROM eclipse-temurin:17-jammy`, and jammy's `python3` is 3.10 | No |

PySpark refuses a driver/executor minor-version mismatch outright, so a host driver on 3.12
talking to a 3.10 executor is not a warning, it is a hard failure. That rules out the shape
where the host venv runs PySpark against these containers, not because of a tooling gap, but
because two of the three rows above cannot move at all.

## Decision

All three Spark services move to `apache/spark:3.5.1-python3`, the ASF-published image, the
same build as the Docker Official `spark:*` tags. Spark stays entirely inside containers: no
host `pyspark`, no host JDK, no `winutils.exe`/`hadoop.dll`, and the venvs stay on 3.12.10.

Three details of that image are load-bearing and are commented where they appear:

- Its entrypoint interprets `driver` and `executor` for Kubernetes and otherwise execs its
  arguments, so the standalone daemons are named explicitly with `spark-class`.
  `sbin/start-master.sh` daemonises and would leave the container with nothing in the foreground.
- It ships `wget` and no `curl`. A healthcheck naming a binary the image lacks never reports
  healthy, so `--wait` would sit out its whole timeout and read as a broken service rather than
  a broken healthcheck.
- The master gets `--host spark-master`, because it advertises the address it binds to and would
  otherwise bind to a container ID that changes on every `up`.

Worker sizing stays in `environment:` as `SPARK_WORKER_MEMORY` and `SPARK_WORKER_CORES`, which
`org.apache.spark.deploy.worker.Worker` reads when no flag overrides them. That is not
decoration either: `test_spark_worker_heap_fits_its_container` reads `SPARK_WORKER_MEMORY` out of
the quickstart overlay, so an otherwise tidier command-line-only sizing would have silently
removed the assertion rather than satisfying it. The test constrained the design, which is the
direction that dependency is supposed to run.

Everything else the old image needed is gone: `SPARK_MODE` (the command carries the role now),
`SPARK_MASTER_URL` (likewise), and the three `SPARK_RPC_*`/`SPARK_SSL_*` keys, which restated
upstream defaults and so read as though something were being switched off.

`tests/test_image_supply.py` adds the guard the withdrawal itself needed. Contract tier: no
image comes from an archived namespace, `bitnamilegacy/` included, so the frozen copy of the
exact tag that broke cannot come back wearing a working URL. Integration tier:
`docker manifest inspect` over every pinned image, which turns "this pin no longer resolves"
into a named test failure instead of an `up` that dies partway through.

## Alternative rejected

**Repoint at `bitnamilegacy/spark:3.5.1`.** A one-word diff that restores a green build in
seconds, and the tag genuinely exists. Rejected because it is a pin to an image that will never
be patched again, in a repository whose entire claim is that its supply chain is deliberate. It
also chooses the same failure a second time: a namespace published as a migration courtesy is a
namespace that can be withdrawn on the same notice as the last one.

**`apache/spark-py:3.5.1`.** No such tag. That variant was retired at `v3.4.0` and folded into
the `-python3` suffix, which is why the chosen tag looks unusual.

**Move the venvs to Python 3.10 and repackage the transfer bundles.** This was the tempting one,
because it appears to make a host `pyspark` install possible and to align the venv with the
container in one move. It fails on three counts. `datetime.UTC` is 3.11+ and is used across five
files; `tomllib` is 3.11+ and a test reads it; and 3.10 reaches upstream end-of-life on
31 October 2026, nine weeks after this record. Adopting an interpreter that near EOL to chase an
alignment the container does not require is a downgrade dressed as a fix. The container's own
3.10 is a different matter: Ubuntu patches jammy's `python3.10` until April 2027, so it is not
shipping an unpatched interpreter.

**Build a local Spark image with Python 3.12 in it.** Technically available, and it would let a
host driver match. Rejected for this milestone: it makes the repository the publisher of a Spark
image, which is a maintenance obligation with a CVE feed attached, and it is unnecessary for as
long as PySpark only ever runs inside the container that ships it.

## Prediction (recorded before the evidence)

I expect the suite to go from 36 passed / 3 skipped to 42 passed / 8 skipped with no existing
assertion edited: six new contract tests (one inventory check plus one per image), and five new
skips from the parametrized manifest check.

I expect `./make.ps1 up-quickstart` on the build machine to reach healthy on all four quickstart
services, and I expect the worker to report 1 core and 1 GiB in the master UI at
`http://localhost:8080`, the same numbers the old overlay produced, from the same two variables.

I expect the healthcheck to be the thing most likely to be wrong, because it is the only part of
this change whose correctness depends on the image's *contents* rather than on documented Spark
behaviour. If `wget` turns out to be absent too, the symptom will be a full 300-second `--wait`
timeout with the services otherwise running.

## Deciding evidence

Measured on the authoring machine, which has no container runtime:

- Both compose files parse, and the merged quickstart still satisfies the 4 GiB / 2.0 CPU
  envelope: **42 passed, 8 skipped**, matching the prediction exactly.
- Zero assertions changed in `test_compose_contract.py` or `test_quickstart_envelope.py`. All
  nine contract assertions hold against the new image: it is pinned, it declares a healthcheck,
  its dependents wait on health, it holds no state, it names no credential.
- The four non-Spark pins were checked against the registry API and all still resolve, so the
  blast radius of the withdrawal was one line in one file.

What is *not* settled here: whether the daemon agrees. The image's command, its entrypoint
behaviour and the presence of `wget` are established from the published Dockerfile and image
config, not from a container that started. The integration tier settles that, and it runs on the
build machine.

## What would change my mind

If the ASF namespace turns out to lag Spark releases badly enough that a security fix is
unavailable as an image for weeks, then publishing a thin local image on top of a maintained JDK
base becomes the honest answer, and the maintenance obligation is the price.

If `spark-class` proves to need a wrapper the old image's entrypoint was providing (signal
handling, log routing, a writable log directory), then the command grows a small committed
entrypoint script rather than more inline arguments.

## Consequences

The spine now depends on the project's own upstream rather than on a repackager, which removes a
layer of publisher risk and costs the convenience of that repackager's environment-variable
configuration surface. Anyone reading the compose file has to know that `spark-class` names a
daemon, which is why the comment says so.

The image's Python is fixed at 3.10 for as long as its base is jammy, so any Spark job in this
repository executes on 3.10 no matter what the venvs run. That is fine while every Spark
entrypoint is a container, and it is precisely what stops being fine the moment something tries
to submit from the host, a constraint worth stating out loud before the ETL component arrives.

The new supply test is the first in this repository that can fail because of something nobody
working in it did. That is deliberate: an unavailable dependency is a real defect in a repository
that claims a reproducible local stack, and it should have a name and a line number.
