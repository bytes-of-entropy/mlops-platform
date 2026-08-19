# mlops-platform

The local-first platform the two flagship repositories deploy onto: a Spark cluster, S3-compatible
object storage, an MLflow tracking server, a scheduler and a metadata database, all reproducible on
one machine, and the Kubernetes and Terraform footprint they run on in the cloud.

**Status: M0.** The compose spine and its contract tests are in. Images (M1), Helm charts and
Terraform (M2) are next. Model registry, drift detection and canary rollout are deliberately
deferred — see [`docs/decisions/001`](docs/decisions/001-defer-registry-drift-canary.md).

## The decision this enables

Every later number in this portfolio — a Spark tuning figure, an evaluation metric, a cost report —
depends on the environment that produced it being the same environment twice. This repository is that
environment, and its claims about itself are asserted by tests rather than described in prose.

## Quickstart

Ten minutes, 4 GB of RAM, 2 CPUs, one command:

```bash
cp .env.example .env      # then fill in the four generated values it asks for
make up-quickstart        # spark master + one worker, MinIO, Postgres, MLflow
make ps
```

| Service | URL | What it stands in for |
|---|---|---|
| Spark master UI | http://localhost:8080 | An EMR or Databricks cluster |
| MinIO console | http://localhost:9001 | S3 |
| MLflow | http://localhost:5000 | A hosted tracking server |
| Airflow (full profile) | http://localhost:8082 | A managed scheduler |

`make up` starts the full spine — two Spark workers and Airflow — and wants roughly 20 GB.
`make down` stops everything and **keeps** your volumes; `make clean` removes them.

**On the pinned tags.** They are exact by policy, and the first `make up` on a machine that has
never pulled them is also the first verification that each tag exists. If one does not resolve, the
fix is a deliberate bump with the new tag committed — not a switch to a floating tag.

## Architecture

[`docs/architecture.md`](docs/architecture.md) — drawn before the code it describes.

## Results: what the tests actually assert

The contract suite runs with no container runtime installed, which is what makes it useful in CI.

| Claim | Asserted by |
|---|---|
| Every image is pinned to an exact tag | `test_every_image_is_pinned` |
| Every service has a healthcheck, and dependencies wait for health rather than start | `test_every_service_declares_a_healthcheck`, `test_dependencies_wait_for_health_not_start` |
| No credential is a literal, anywhere in the file, including `command:` strings | `test_no_credential_is_a_literal`, `test_no_literal_secret_anywhere_in_the_file` |
| All state lives in named volumes; host mounts are read-only | `test_stateful_services_use_named_volumes`, `test_host_bind_mounts_are_read_only` |
| The quickstart fits in 4 GiB and 2.0 CPUs | `test_quickstart_fits_in_four_gigabytes`, `test_quickstart_fits_in_two_cpus` |
| The Spark worker's heap fits inside its container limit | `test_spark_worker_heap_fits_its_container` |
| The Makefile and its Windows mirror have not drifted | `test_no_target_exists_in_only_one_entrypoint` |
| `down` keeps volumes and only `clean` removes them | `test_down_keeps_volumes_and_clean_removes_them` |
| `down` then `up` reaches the same healthy set, twice, with state intact | `tests/test_idempotency.py` (needs a runtime) |

## The hard problem

Idempotency is the one property a local stack quietly lacks. `make up` twice, or `make down && make
up`, has to land in the same place — otherwise every downstream measurement is conditional on how many
times the author happened to restart something.

Three specific ways it fails are designed out here rather than discovered later:

- **`depends_on` in list form waits for a container to start, not to be usable.** MLflow opening a
  connection to a Postgres that is up but not yet accepting connections is a race, and a race that
  passes most of the time is worse than one that fails every time. Every dependency in the spine is
  gated on `service_healthy`, and a test fails if the list form ever reappears.
- **A writable host mount lets a container change the working tree.** The second `up` then starts from
  a different filesystem than the first. Host mounts here are read-only, asserted.
- **`down --volumes` makes idempotency indistinguishable from starting over.** It "works" by
  destroying the evidence. `make down` keeps volumes and `make clean` removes them, and a test fails
  if the two are ever collapsed into one.

Whether the cycle actually holds is a separate question from whether it is designed to, and it is
answered by `tests/test_idempotency.py` — which brings the stack up, tears it down, brings it up
again, and asserts the same healthy set plus a MinIO object written before the teardown and read after
it. That test needs a container runtime. **It has not been run yet**: this repository was authored on a
machine without Docker installed, and the M0 gate does not pass until it is green on the build
machine. The contract suite below it is what runs everywhere, and it is green.

## Reproduce

```bash
make setup    # creates .venv from the pinned dev dependencies
make check    # everything the gate requires: formatting, ruff, mypy, then the suite
```

`make check` is `make lint` then `make test`, and either runs on its own. On Windows, `./make.ps1
<target>` takes the same names; a test fails if a target exists in one entrypoint and not the other.

Current output on the authoring machine, which has no container runtime:

```
ruff format --check .   7 files already formatted
ruff check .            All checks passed!
mypy                    Success: no issues found in 7 source files
pytest                  25 passed, 3 skipped in 0.05s
```

The three skips are the integration tests, and the skip reason distinguishes Docker not being
installed from Docker being installed but not running — because "install Docker" and "start Docker"
are different instructions, and a probe that only checks whether the binary exists gives the wrong one.

## What I would do differently

The credential handling is the weakest part. Compose's `${VAR:?message}` form fails loudly when a
variable is missing, which is right, but it still means an eight-line `.env` to fill in by hand
before anything starts. A generated `.env` on first `make up` would be friendlier and would make the
quickstart genuinely one command; it would also make it easier to forget that these are credentials.
Chose the friction.

## Cost

Nothing. Everything here runs locally. The cloud footprint in `infra/` arrives at M2, is destroyed in
the same session it is created, and its spend is reported in the run log rather than estimated.

## Confidentiality

Everything in this repository was built fresh on public and generated data. No employer material,
no employer architecture, no configuration derived from a confidential system.
