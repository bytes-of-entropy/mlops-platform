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
`make down` stops everything and **keeps** your volumes; `make clean` removes them. Change a
credential in `.env` after the first `up` and you want `make clean`: Postgres only reads those
variables while initialising an empty volume, and the kept volume still holds the old role.

Airflow's login is `admin` with the `AIRFLOW_ADMIN_PASSWORD` you generated. The username is pinned
rather than chosen — [`docs/decisions/008`](docs/decisions/008-airflow-creates-the-admin-it-is-given.md)
explains why a configurable one produced an account nobody could log into.

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
| No image comes from a namespace published as a frozen archive | `test_no_image_comes_from_an_archived_namespace` |
| Every pinned image still resolves in a registry | `test_every_pinned_image_still_resolves` (needs a runtime) |
| Every service has a healthcheck, and dependencies wait for health rather than start | `test_every_service_declares_a_healthcheck`, `test_dependencies_wait_for_health_not_start` |
| No credential is a literal, anywhere in the file, including `command:` strings | `test_no_credential_is_a_literal`, `test_no_literal_secret_anywhere_in_the_file` |
| All state lives in named volumes; host mounts are read-only | `test_stateful_services_use_named_volumes`, `test_host_bind_mounts_are_read_only` |
| The quickstart fits in 4 GiB and 2.0 CPUs | `test_quickstart_fits_in_four_gigabytes`, `test_quickstart_fits_in_two_cpus` |
| The Spark worker's heap fits inside its container limit | `test_spark_worker_heap_fits_its_container` |
| The Makefile and its Windows mirror have not drifted | `test_no_target_exists_in_only_one_entrypoint` |
| A pinned tool is the same version everywhere it is named | `test_every_hook_that_mirrors_a_pinned_tool_runs_the_pinned_version`, `test_the_interpreter_running_this_suite_has_the_pinned_ruff` |
| The committed hook config is something that actually runs | `test_both_entrypoints_install_the_git_hooks_during_setup`, `test_the_gate_runs_the_hooks_in_both_entrypoints_and_in_ci` |
| `down` keeps volumes and only `clean` removes them | `test_down_keeps_volumes_and_clean_removes_them` |
| Both entrypoints and the integration suite resolve `.env` and bind mounts against the repository root | `test_the_makefile_anchors_the_project_directory_in_every_invocation`, `test_the_powershell_mirror_anchors_it_too`, `test_the_integration_suite_invokes_compose_the_way_the_entrypoints_do` |
| Every relative bind mount names a path that exists, and one that `compose/` cannot also satisfy | `test_every_relative_bind_mount_exists_under_the_repository_root`, `test_no_relative_bind_mount_would_also_resolve_under_the_compose_directory` |
| `down` then `up` reaches the same healthy set, twice, with state intact | `tests/test_idempotency.py` (needs a runtime and the local credentials) |
| A missing precondition is named in the skip rather than reported as a failure of what it blocks | `tests/test_docker_probe.py`, `test_the_reason_names_each_missing_variable_and_what_to_do_about_it` |
| An integration failure reports the command, the exit code, both output streams, and the container state and service logs gathered afterwards | `tests/test_failure_reports.py` |
| Every variable the compose files interpolate is named in `.env.example`, and nothing else is | `test_every_variable_the_compose_files_interpolate_is_in_the_example`, `test_the_example_names_nothing_the_compose_files_do_not_use` |
| A credential passed to an image that has not been told to read it is not accepted as configuration | `test_a_credential_the_image_was_never_told_to_use_is_not_configuration` |
| The CI credential step writes exactly the variables `.env.example` declares | `test_the_ci_credential_step_writes_exactly_what_the_example_declares` |

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

One was not designed out — it was found by reading, before the first `up` on any machine. Compose
resolves the default `.env` and every relative bind mount against the project directory, which
defaults to the folder holding the first `-f` file rather than the working directory, so
`./postgres/init` pointed inside `compose/`. Docker creates a missing host path as an empty directory
instead of refusing, which means Postgres would have started, reported healthy, and never run its
init SQL — a failure the entire M0 gate would have passed over in silence. Every invocation now
passes `--project-directory .`, and the reasoning is in
[`docs/decisions/004`](docs/decisions/004-anchor-the-compose-project-directory.md).

The next one came from outside the repository entirely. The first `up` on the build machine failed
with `failed to resolve reference "docker.io/bitnami/spark:3.5.1": not found` — an exact pin, on an
unchanged file, that no longer resolved because its publisher had deleted the whole namespace and
moved versioned tags to an explicitly unmaintained archive. The pin had done its job: it made the
build reproducible. It had never been able to make the image *available*, and a digest pin would have
died with the repository just the same, because a digest names content inside a repository and the
repository is what was withdrawn. Reproducibility and availability are separate properties needing
separate defences, and the only defence against withdrawal is a different publisher or a registry you
control. Spark now runs on the ASF's own `apache/spark:3.5.1-python3`, two tests were added — one
refusing any archived namespace, one asking a registry whether every pin still resolves — and the
reasoning, including why the frozen copy of the working tag was the wrong fix, is in
[`docs/decisions/005`](docs/decisions/005-migrate-off-the-withdrawn-spark-image.md).

The one after that came from the order someone did things in. Install Docker, then run the gate, and
the three idempotency tests failed — not because the cycle is broken, but because `.env` did not
exist yet, so compose refused to render the file and the assertion that reported it says `compose up
failed` under a test name that claims idempotency is the thing at fault. The pattern to copy was
already one layer down: the Docker probe exists because installed is not the same as usable, and
credentials are the same shape one step along. Those tests now gate on both preconditions and skip
naming the variables that are unset, read out of `.env.example` rather than restated in test code —
[`docs/decisions/006`](docs/decisions/006-preconditions-skip-by-name.md), including why fixing the
documented step order instead would have left a test lying about its own subject.

And the one after that was hiding in the design rather than in the order. With `.env` filled in, the
stack still refused, and the reason was not in compose's output: it was a line in the Postgres
container's log saying the role named in `.env` does not exist. The `postgres` image reads
`POSTGRES_USER` only while initialising an empty data directory, so the credentials in the volume are
the ones the *first* `up` on that machine created, and `make down` keeps that volume on purpose —
because a `down` that removed it would make idempotency indistinguishable from starting over. The
same property, read from two sides. Re-cloning does not help either: the project name comes from the
directory basename, so a new clone reuses the same volume. The fix for the state is `make clean`; the
fix for the *repository* is that a failed compose call now gathers `compose ps` and the service logs
into the assertion, because a report built from the failing command's own streams cannot contain a
diagnosis that only ever appears in a container's log —
[`docs/decisions/007`](docs/decisions/007-a-kept-volume-pins-the-first-runs-credentials.md).

Whether the cycle actually holds is a separate question from whether it is designed to, and it is
answered by `tests/test_idempotency.py` — which brings the stack up, tears it down, brings it up
again, and asserts the same healthy set plus a MinIO object written before the teardown and read after
it. That test needs a container runtime. **It has not been run yet**: this repository was authored on a
machine without Docker installed, and the M0 gate does not pass until it is green on the build
machine. The contract suite below it is what runs everywhere, and it is green.

## Reproduce

```bash
make setup    # creates .venv from the pinned dev dependencies
make check    # the gate: formatting, ruff, mypy, the pre-commit hooks, then the suite
```

`make check` is `make lint`, `make hooks` and `make test`, and each runs on its own. On Windows, `./make.ps1
<target>` takes the same names; a test fails if a target exists in one entrypoint and not the other.

Current output on the authoring machine, which has no container runtime:

```
ruff format --check .   23 files already formatted
ruff check .            All checks passed!
mypy                    Success: no issues found in 12 source files
pre-commit --all-files  8 hooks, all Passed
pytest                  65 passed, 8 skipped in 0.32s
```

The formatter counts twenty-three files and mypy counts twelve because they are looking at different
things. There are twelve Python files; the formatter also reads the eleven Markdown files, where it formats
`python`-fenced code blocks and leaves prose alone. A code sample in this repository's documentation is
therefore held to the same style as the code, which is the intended behaviour rather than a side effect
worth suppressing.

The eight skips are the integration tier: three idempotency tests and five image-resolution checks,
one per pinned image. Every skip names the precondition that is missing rather than the test that
could not run, and the reasons distinguish cases a coarser check would merge — Docker not installed
from Docker installed but not running, and either of those from a machine whose `.env` has not been
filled in yet. "Install Docker", "start Docker" and "write your credentials" are three different
instructions, and a probe that only checks whether the binary exists gives the wrong one.

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
