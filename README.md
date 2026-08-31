# mlops-platform

The local-first platform the two flagship repositories deploy onto: a Spark cluster, S3-compatible
object storage, an MLflow tracking server, a scheduler and a metadata database, all reproducible on
one machine, and the Kubernetes and Terraform footprint they run on in the cloud.

**Status: M0 closed at `v0.1.0`, M1 closed at `v0.2.0`. M2's chart is written and has never been
installed.** Two claims here are demonstrated and one is not, and the difference is the point of this
paragraph.

**Demonstrated.** The compose spine, its contract suite, a preflight that refuses a start which would
come up healthy and wrong, and a smoke DAG that crosses the spine and is asserted at both ends, in
MLflow and in Postgres. The integration tier runs end to end on a real machine — `120 passed, 0 skipped`
at the commit that closed M0, `124 passed, 0 skipped` at `v0.1.2` — with the tests that start actual
stacks included. Three defects were found by running it rather than by reading it: two were claims about
what is *inside* a pinned image ([`011`](docs/decisions/011-what-is-inside-an-image-is-a-claim.md)) and
the third was in a test, where fixing the second had silently moved a supply-chain check off the pin it
existed to watch ([`012`](docs/decisions/012-a-built-tag-is-not-a-registry-fact.md)). Neither class is
catchable by a rule that only reads the compose file.

**Demonstrated, M1.** The built image runs as a named non-root account and is audited statically
([`017`](docs/decisions/017-the-image-runs-as-a-named-non-root-user-and-the-dockerfile-is-audited-statically.md)); every pulled reference carries a tag
and a digest ([`018`](docs/decisions/018-every-pulled-reference-is-pinned-by-digest-and-the-built-one-is-not.md)); each image has a
committed, reproducible package inventory ([`019`](docs/decisions/019-the-committed-artifact-is-a-package-inventory-and-every-scan-exception-expires.md));
the scanner works and carries an expiry, because its usefulness is a database that must be fresh
([`020`](docs/decisions/020-a-scanner-pin-carries-an-expiry-because-its-data-retires-before-the-tool-does.md)); bases are current within
their major lines, which cut findings by roughly a third
([`021`](docs/decisions/021-the-answer-to-five-thousand-findings-is-a-version-bump-not-a-page-of-exceptions.md)); and the gate fails on an
advisory *identity* absent from a committed baseline rather than on a severity
([`022`](docs/decisions/022-the-gate-is-on-advisory-identity-because-severity-cannot-move.md)). One item is sequenced rather
than done: the GHCR push is built and tested as far as a registry-less machine allows, and waits on the
repository it publishes alongside ([`023`](docs/decisions/023-only-the-image-this-repository-builds-is-published-and-not-before-the-repository-is.md)).

**Not demonstrated.** M2's Helm chart — MLflow, Postgres and MinIO, with probes, PVCs, an Ingress and an
HPA — is written, and its 49 contract-tier assertions pass on a machine with no cluster on it. That is
the weaker half of the claim by construction: those tests parse the chart, and whether `helm install`
works is not something parsing can settle. The cluster tier that installs it on kind
(`tests/test_kind_cluster.py`) has never run. Until it does, treat the chart as reviewed and unexercised.
Terraform (M3) has not started. Model registry, drift detection and canary rollout are deliberately
deferred; see [`docs/decisions/001`](docs/decisions/001-defer-registry-drift-canary.md).

**One honest limit, because a reviewer will otherwise ask it first.** Of the services the spine
starts, the two Spark workers are healthy and **idle**: no job has ever been submitted to this
cluster, because the smoke path deliberately uses the standard library only and M0 has no workload
to give them. Object storage was in that same category until it turned out to be worse than idle,
a configured artifact root pointing at a bucket nothing created
([`docs/decisions/015`](docs/decisions/015-a-provisioner-creates-the-bucket-the-artifact-root-names.md));
it is now provisioned and exercised by a test that round-trips a real object through it. Spark gets
the same treatment at M2, when there is a real job to submit rather than a synthetic one invented to
make a test pass.

## The decision this enables

Every later number in this portfolio (a Spark tuning figure, an evaluation metric, a cost report)
depends on the environment that produced it being the same environment twice. This repository is that
environment, and its claims about itself are asserted by tests rather than described in prose.

## Quickstart

Ten minutes, 4 GB of RAM, 2 CPUs, one command:

```bash
cp .env.example .env      # six blanks to fill: four generated, two chosen
make up-quickstart        # spark master + one worker, MinIO, Postgres, MLflow
make ps
```

| Service | URL | What it stands in for |
|---|---|---|
| Spark master UI | http://localhost:8080 | An EMR or Databricks cluster |
| MinIO console | http://localhost:9001 | S3 |
| MLflow | http://localhost:5000 | A hosted tracking server |
| Airflow (full profile) | http://localhost:8082 | A managed scheduler |

`make up` starts the full spine, two Spark workers and Airflow included, and wants roughly 20 GB.
`make down` stops everything and **keeps** your volumes; `make clean` removes them; `make reset` is
`clean` then `up`, for the one case where discarding the volume is the fix rather than an accident.

One image in the spine is built rather than pulled, so the first `up` on a machine pays for a build as
well as a pull. `make build` does that step alone, which is worth doing before anything timed: both
`up` targets bound their wait, and a cold build inside that budget is minutes spent on work whose
result is identical every time.

Both `up` targets depend on `make doctor`, which therefore runs first and cannot be skipped. It checks
three things and names what to do about each: that a container runtime answers, that the seven
credential variables are present and not still the placeholder text, and that a data volume you kept
was initialised with the credentials now in `.env`. That last one has cost more time here than the
other two together. Postgres reads `POSTGRES_USER` and `POSTGRES_PASSWORD` only while initialising an
empty volume, so a credential changed after the first `up` leaves the old role in place, and the stack
refuses with a message that appears only inside a container's log. The volume now records a salted
digest of what built it, the doctor compares that against your current values, and the answer when
they differ is `make reset`. That destroys the volume, which is why it is your decision and not the
doctor's. A volume that predates the fingerprint reports that it cannot tell, rather than guessing,
and never blocks a start:
[`docs/decisions/009`](docs/decisions/009-a-volume-records-what-it-was-built-with.md).

Airflow's login is `admin` with the `AIRFLOW_ADMIN_PASSWORD` you generated. The username is pinned
rather than chosen; [`docs/decisions/008`](docs/decisions/008-airflow-creates-the-admin-it-is-given.md)
explains why a configurable one produced an account nobody could log into.

**On the pinned tags.** They are exact by policy, and the first `make up` on a machine that has
never pulled them is also the first verification that each tag exists. If one does not resolve, the
fix is a deliberate bump with the new tag committed, not a switch to a floating tag.

This section is the ten-minute path. [`docs/setup.md`](docs/setup.md) is the long form, and the only
other document needed: how the code arrives and where it should live, prerequisites and the five
things deliberately not installed, which credentials can still be changed later and which cannot, the
build-before-anything-timed order the integration tier needs, the output each command should produce,
and a troubleshooting section keyed by the symptom rather than by the subsystem, because the
recurring lesson here is that the subsystem a failure names is often not the one at fault.

## Architecture

[`docs/architecture.md`](docs/architecture.md), drawn before the code it describes.

## Results: what the tests actually assert

The contract suite runs with no container runtime installed, which is what makes it useful in CI.

| Claim | Asserted by |
|---|---|
| Every image is pinned to an exact tag | `test_every_image_is_pinned` |
| No image comes from a namespace published as a frozen archive | `test_no_image_comes_from_an_archived_namespace` |
| Every pinned image still resolves in a registry: the tags this spine pulls, plus the base of the one it builds | `test_every_pinned_image_still_resolves` (needs a runtime) |
| Every image is either pulled from a registry or built here, and none is treated as both | `test_every_service_image_is_either_pulled_or_built` |
| Every service has a healthcheck, and dependencies wait for health rather than start | `test_every_service_declares_a_healthcheck`, `test_dependencies_wait_for_health_not_start` |
| A healthcheck only names a binary its own image is known to provide | `test_a_healthcheck_only_names_a_binary_its_image_provides` |
| A service that is built still declares a pinned tag, and its Dockerfile a pinned base | `test_a_built_image_still_declares_a_pinned_tag_and_a_pinned_base` |
| No credential is a literal, anywhere in the file, including `command:` strings | `test_no_credential_is_a_literal`, `test_no_literal_secret_anywhere_in_the_file` |
| All state lives in named volumes; host mounts are read-only | `test_stateful_services_use_named_volumes`, `test_host_bind_mounts_are_read_only` |
| The quickstart fits in 4 GiB and 2.0 CPUs | `test_quickstart_fits_in_four_gigabytes`, `test_quickstart_fits_in_two_cpus` |
| The Spark worker's heap fits inside its container limit | `test_spark_worker_heap_fits_its_container` |
| The Makefile and its Windows mirror have not drifted | `test_no_target_exists_in_only_one_entrypoint` |
| A pinned tool is the same version everywhere it is named | `test_every_hook_that_mirrors_a_pinned_tool_runs_the_pinned_version`, `test_the_interpreter_running_this_suite_has_the_pinned_ruff` |
| The committed hook config is something that actually runs | `test_both_entrypoints_install_the_git_hooks_during_setup`, `test_the_gate_runs_the_hooks_in_both_entrypoints_and_in_ci` |
| `down` keeps volumes and only `clean` removes them | `test_down_keeps_volumes_and_clean_removes_them` |
| Every place that invokes compose (both entrypoints, the integration tier and the preflight) resolves `.env` and bind mounts against the repository root | `test_the_makefile_anchors_the_project_directory_in_every_invocation`, `test_the_powershell_mirror_anchors_it_too`, `test_the_integration_suite_invokes_compose_the_way_the_entrypoints_do`, `test_the_doctor_invokes_compose_the_way_the_entrypoints_do` |
| Every relative bind mount names a path that exists, and one that `compose/` cannot also satisfy | `test_every_relative_bind_mount_exists_under_the_repository_root`, `test_no_relative_bind_mount_would_also_resolve_under_the_compose_directory` |
| `down` then `up` reaches the same healthy set, twice, with state intact | `tests/test_idempotency.py` (needs a runtime and the local credentials) |
| A missing precondition is named in the skip rather than reported as a failure of what it blocks | `tests/test_docker_probe.py`, `test_the_reason_names_each_missing_variable_and_what_to_do_about_it` |
| An integration failure reports the command, the exit code, both output streams, and the container state and service logs gathered afterwards | `tests/test_failure_reports.py` |
| Every variable the compose files interpolate is named in `.env.example`, and nothing else is | `test_every_variable_the_compose_files_interpolate_is_in_the_example`, `test_the_example_names_nothing_the_compose_files_do_not_use` |
| A credential passed to an image that has not been told to read it is not accepted as configuration | `test_a_credential_the_image_was_never_told_to_use_is_not_configuration` |
| The CI credential step writes exactly the variables `.env.example` declares | `test_the_ci_credential_step_writes_exactly_what_the_example_declares` |
| Neither entrypoint can start the stack without the preflight running first | `test_both_entrypoints_run_the_doctor_before_starting_the_stack` |
| Every variable is classified by when its image reads it, and the table covers exactly what `.env.example` declares | `test_every_variable_the_example_declares_is_classified`, `test_the_table_classifies_nothing_the_example_does_not_declare` |
| A kept volume built with different credentials is refused, with the recovery named | `test_a_volume_built_with_a_different_password_fails_and_says_how_to_recover` |
| The fingerprint the init script writes is the one the checker computes, holds no credential in it, and is salted per volume | `test_the_init_script_and_the_python_digest_agree`, `test_the_recorded_file_does_not_contain_the_credentials`, `test_two_initialisations_of_the_same_credentials_record_different_digests` |
| A volume that predates the fingerprint says it cannot tell, rather than passing or failing | `test_a_volume_that_predates_the_fingerprint_reports_that_it_cannot_tell` |
| The DAG imports nothing the pinned Airflow image does not ship | `test_the_dag_imports_nothing_the_image_does_not_ship` |
| The DAG reads the tracking address compose sets, and has no default for it | `test_the_dag_reads_the_tracking_variable_that_compose_sets`, `test_the_dag_has_no_default_tracking_address` |
| One DAG run reaches MLflow and the same run id lands in Postgres | `tests/test_m0_smoke.py` (needs a runtime and the local credentials) |
| The integration tier starts its own compose project rather than the developer's | `test_the_integration_suite_starts_its_own_project_not_the_developers` |

## The hard problem

Idempotency is the one property a local stack quietly lacks. `make up` twice, or `make down && make
up`, has to land in the same place; otherwise every downstream measurement is conditional on how many
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

One was not designed out. It was found by reading, before the first `up` on any machine. Compose
resolves the default `.env` and every relative bind mount against the project directory, which
defaults to the folder holding the first `-f` file rather than the working directory, so
`./postgres/init` pointed inside `compose/`. Docker creates a missing host path as an empty directory
instead of refusing, which means Postgres would have started, reported healthy, and never run its
init SQL, a failure the entire M0 gate would have passed over in silence. Every invocation now
passes `--project-directory .`, and the reasoning is in
[`docs/decisions/004`](docs/decisions/004-anchor-the-compose-project-directory.md).

The next one came from outside the repository entirely. The first `up` on the build machine failed
with `failed to resolve reference "docker.io/bitnami/spark:3.5.1": not found`: an exact pin, on an
unchanged file, that no longer resolved because its publisher had deleted the whole namespace and
moved versioned tags to an explicitly unmaintained archive. The pin had done its job: it made the
build reproducible. It had never been able to make the image *available*, and a digest pin would have
died with the repository just the same, because a digest names content inside a repository and the
repository is what was withdrawn. Reproducibility and availability are separate properties needing
separate defences, and the only defence against withdrawal is a different publisher or a registry you
control. Spark now runs on the ASF's own `apache/spark:3.5.1-python3`, two tests were added (one
refusing any archived namespace, one asking a registry whether every pin still resolves), and the
reasoning, including why the frozen copy of the working tag was the wrong fix, is in
[`docs/decisions/005`](docs/decisions/005-migrate-off-the-withdrawn-spark-image.md).

The one after that came from the order someone did things in. Install Docker, then run the gate, and
the three idempotency tests failed, not because the cycle is broken, but because `.env` did not
exist yet, so compose refused to render the file and the assertion that reported it says `compose up
failed` under a test name that claims idempotency is the thing at fault. The pattern to copy was
already one layer down: the Docker probe exists because installed is not the same as usable, and
credentials are the same shape one step along. Those tests now gate on both preconditions and skip
naming the variables that are unset, read out of `.env.example` rather than restated in test code.
See [`docs/decisions/006`](docs/decisions/006-preconditions-skip-by-name.md), including why fixing the
documented step order instead would have left a test lying about its own subject.

And the one after that was hiding in the design rather than in the order. With `.env` filled in, the
stack still refused, and the reason was not in compose's output: it was a line in the Postgres
container's log saying the role named in `.env` does not exist. The `postgres` image reads
`POSTGRES_USER` only while initialising an empty data directory, so the credentials in the volume are
the ones the *first* `up` on that machine created, and `make down` keeps that volume on purpose,
because a `down` that removed it would make idempotency indistinguishable from starting over. The
same property, read from two sides. Re-cloning does not help either: the project name comes from the
directory basename, so a new clone reuses the same volume. The fix for the state is `make clean`; the
fix for the *repository* is that a failed compose call now gathers `compose ps` and the service logs
into the assertion, because a report built from the failing command's own streams cannot contain a
diagnosis that only ever appears in a container's log:
[`docs/decisions/007`](docs/decisions/007-a-kept-volume-pins-the-first-runs-credentials.md).

The next one was not a failure at all, which is why it took so long to be seen. Everything above
asserts one service at a time, and a healthcheck is a service answering its own port, so a stack of
them passing is a stack of services each alive, saying nothing about whether any two of them can reach
each other. `airflow/dags/m0_smoke.py` is the smallest thing that does: one task creates an MLflow
run, logs a param and a metric, and marks it finished, which crosses four boundaries in one artefact:
Airflow parsing the file, Airflow executing it, MLflow accepting the writes, and Postgres holding the
row. It is asserted at the far end as well as the near one, because MLflow's own API reporting a
finished run proves only the half that was cheap to prove; the same run id turning up as a row in
Postgres is what proves MLflow reached its backend store rather than answering from memory until the
next restart. It does not touch MinIO: an artefact write goes through the artifact store and needs an
S3 client the pinned image does not ship. Stating that is the point, because a smoke test that
overstates its reach turns an unknown into a false assurance:
[`docs/decisions/010`](docs/decisions/010-a-smoke-dag-closes-m0.md).

The last two came from the first `up` that got far enough to have a running stack to look at, and they
are the same mistake twice. The doctor passed all three checks, six of seven services reported healthy,
and MLflow never did. Two defects were behind it, and both are claims about what is inside a pinned
image. Its healthcheck ran `curl`, which the compose file elsewhere already notes an image does not owe
you: naming a binary the image lacks costs the whole `--wait` timeout and then reports a broken
*service*, so the failure names the wrong thing. Underneath that, `mlflow server` with a Postgres
backend and an S3 artifact root needs a DBAPI driver and an S3 client, and the published MLflow image
ships neither, so the process exited at import. Every rule in the contract suite passed on a container
that could not start, because every one of them describes the compose *file*: image pinned, credential
interpolated, healthcheck declared, dependency gated on health, volume named, mount read-only. None
of them describes image *contents*. The healthchecks now run the interpreter, which both images are
guaranteed to have by construction rather than by hope; MLflow is built from a two-line Dockerfile that
adds the two packages, which is the first built image here and keeps its pin in the `FROM`; and two new
rules make the class hard to reintroduce: a healthcheck may only name a binary its image is recorded as
providing, and a built service still declares a pinned tag with a pinned base behind it:
[`docs/decisions/011`](docs/decisions/011-what-is-inside-an-image-is-a-claim.md).

The one after those was mine rather than an image's, and it arrived from the only place that could
find it: the tier itself, on the first run that reached that far. `test_every_pinned_image_still_resolves`
asks a registry about every `image` key in the compose file, which was exactly right until the fix
above added a service that is *built* here and (deliberately, because that is the tag `ps` reports)
kept an `image` key beside its `build`. So the suite asked a registry about a tag this repository
produces, got exit code 1, and reported a withdrawn pin that nobody had withdrawn. The false alarm was
the visible half. The invisible half is worse: the pin that genuinely could be withdrawn,
`ghcr.io/mlflow/mlflow:v2.13.0`, stopped being probed the moment that `image` key changed, and nothing
said so. A test whose input set is derived from configuration can have its premise revoked by an edit
to that configuration, and it will keep passing (or fail for the wrong reason) with no edit to the
test. The module now sorts each `image` key by whether its service declares a `build` and probes the
pulled tags plus the `FROM` of the built one, and a third test asserts the two sets account for every
key between them, so a tag can move from one to the other but cannot fall out of both:
[`docs/decisions/012`](docs/decisions/012-a-built-tag-is-not-a-registry-fact.md).

Whether any of it actually holds is a separate question from whether it is designed to, and it is
answered by two files that need a container runtime: `tests/test_idempotency.py` brings the stack up,
tears it down, brings it up again, and asserts the same healthy set plus a MinIO object written before
the teardown and read after it; `tests/test_m0_smoke.py` runs the smoke DAG and checks both ends of
its write path. **Neither has been run green yet.** Authoring happened on a machine with no container
runtime, and the M0 gate does not pass until both files are green on the build machine. Two of the
defects above were found by starting the stack by hand, one step short of that tier running; the third
was found by the tier running and failing, which is the first thing it has ever reported and is already
one more than reading could have produced. The
contract suite below them is what runs everywhere, and it is green, including the rule that a DAG may
import Airflow and the standard library and nothing else, because `import mlflow` in a DAG passes the
formatter, the linter and review, and then fails at task-run time inside an image that has no install
step. That rule and the two new ones are the same rule aimed at different files: what a pinned image
contains is a claim, and a claim is worth exactly as much as the thing that checks it.

## Reproduce

```bash
make setup    # creates .venv from the pinned dev dependencies
make check    # the gate: formatting, ruff, mypy, the pre-commit hooks, then the suite
```

`make check` is `make lint`, `make hooks` and `make test`, and each runs on its own. On Windows, `./make.ps1
<target>` takes the same names; a test fails if a target exists in one entrypoint and not the other.

Current output on the authoring machine, which has no container runtime:

```
ruff format --check .   43 files already formatted
ruff check .            All checks passed!
mypy                    Success: no issues found in 23 source files
pre-commit --all-files  8 hooks, all Passed
pytest                  109 passed, 11 skipped in 1.63s
```

The three tools report different file counts because they are looking at different things, and none of
them is wrong. `mypy` checks the Python modules it is configured to check. `ruff format` reads those
and the Markdown files as well, where it formats `python`-fenced code blocks and leaves prose alone, so
a code sample in this repository's documentation is held to the same style as the code, which is
intended rather than a side effect worth suppressing. `ruff check` lints Python only, plus
`pyproject.toml`, which it reads for its own configuration. Those totals move with every file added, so
they are not also written out in prose here: the block above is what the current tree prints, and it is
the only place in this README that carries a count.

The one Python file mypy does not check is the DAG. It imports Airflow, which lives in a pinned image
rather than in these dev dependencies, so a type check here would report the framework as missing
rather than report anything about the module, and installing a scheduler in order to check a file is a
worse trade than reading it. What can be established without the framework is established by reading:
the suite parses the DAG with `ast` and asserts what it declares.

The eleven skips are the integration tier: three idempotency tests, five image-resolution checks
(one per registry reference, meaning the four tags the spine pulls plus the base the one built image
comes from), and three that need the full profile running to exercise the smoke DAG. Every skip
names the precondition that is missing rather than the test that could not run, and the reasons
distinguish cases a coarser check would merge: Docker not installed from Docker installed but not
running, and either of those from a machine whose `.env` has not been filled in yet. "Install Docker",
"start Docker" and "write your credentials" are three different instructions, and a probe that only
checks whether the binary exists gives the wrong one.

## What I would do differently

The credential handling is the weakest part. Compose's `${VAR:?message}` form fails loudly when a
variable is missing, which is right, but it still means seven variables in a `.env` to fill in by
hand before anything starts. A generated `.env` on first `make up` would be friendlier and would make the
quickstart genuinely one command; it would also make it easier to forget that these are credentials.
Chose the friction.

## Cost

Nothing. Everything here runs locally. The cloud footprint in `infra/` arrives at M3, is destroyed in
the same session it is created, and its spend is reported in the run log rather than estimated.

## Confidentiality

Everything in this repository was built fresh on public and generated data. No employer material,
no employer architecture, no configuration derived from a confidential system.
