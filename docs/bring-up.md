# Bring-up

Everything needed to take this repository from a clone to a green integration tier on a machine that
has never run it. The procedure is the same everywhere; the commands are written for PowerShell on
Windows, because that is where it is executed, and every one of them has a `make` equivalent named
beside it.

Read once before starting: **nothing in section 4 has ever completed anywhere.** The gate in section
3 is measured and reproducible. The integration tier has been started by hand far enough to find two
defects and has not yet run green end to end, which is exactly the state M0 closes out of. A failure
there is information about the compose contract, not evidence of a bad clone — record it before
fixing it.

1. [Prerequisites](#1-prerequisites)
2. [Credentials](#2-credentials)
3. [The gate](#3-the-gate)
4. [Build and the integration tier](#4-build-and-the-integration-tier)
5. [Expected output](#5-expected-output)
6. [Troubleshooting by symptom](#6-troubleshooting-by-symptom)

## 1. Prerequisites

| Need | Version | What it is for | Check |
| --- | --- | --- | --- |
| Git | any current | the clone, and Git Bash, which the hooks run under | `git --version` |
| Python | 3.11–3.12 | `pyproject.toml` declares `>=3.11,<3.13` | `py -3 -V` |
| A container runtime | Docker Desktop with the WSL2 backend | everything in section 4 | `docker version` |
| GNU Make | optional | unskips one Makefile-parity test; CI runs the Makefile regardless | `make --version` |

Set `git config --global user.name` and `user.email` before the first commit, or the pre-commit hooks
run against an identity that does not exist.

### What is deliberately not installed

Each of these is a thing a Spark or MLflow tutorial would tell you to install, and each is wrong
here. The reasoning is [`decisions/005`](decisions/005-migrate-off-the-withdrawn-spark-image.md).

- **No JDK.** Spark's Java 17 is inside the image. A host JDK is only needed by a host Spark.
- **No `winutils.exe` or `hadoop.dll`.** Those are Windows shims for a *host* Spark process. There is
  no host Spark process.
- **No `pyspark` in the virtual environment.** PySpark 3.5.x supports Python 3.8–3.11, the venv is
  3.12, and the Spark image's own Python is 3.10 and stays 3.10 while that image is Ubuntu
  jammy-based. PySpark refuses a driver/executor minor mismatch, so a host driver could not talk to
  these containers even if the versions allowed it.
- **No Spark tarball.** The image *is* the distribution.
- **No `cryptography`.** The Fernet key Airflow wants is 32 random bytes, urlsafe-base64-encoded,
  which the standard library produces. A dependency added to generate one string during setup is a
  dependency to keep patched forever.

### Disk and memory

The quickstart profile pulls roughly 4 GB of images; the full profile is roughly 20 GB, plus one
build. On Windows the images and volumes live in a WSL2 virtual disk whose location is a Docker
Desktop setting — put it on a drive with room, and prefer an SSD, since every pull, build and Spark
shuffle spill lands there. That is a host setting, not a repository one; nothing here reads it.

`docker info --format '{{.DockerRootDir}}'` is **not** the check — it prints `/var/lib/docker`, a path
inside the WSL2 VM, whichever host drive backs it. Find the backing file instead:

```powershell
Get-ChildItem <the configured location> -Recurse -Filter *.vhdx |
  Select-Object FullName, @{n='SizeGB';e={[math]::Round($_.Length/1GB, 2)}}
wsl --list -v      # docker-desktop should be Running
```

Memory is worth knowing before the full profile rather than during it. The quickstart override caps
its services at 3.75 GiB of ceilings in total. The full profile declares about 21 GB, of which two
Spark workers at 7g each are 14. Those are ceilings and not reservations, and nothing at M0 gives
Spark real work, so a runtime with less than 21 GB is expected to be fine here — but it is
over-committed, and a container killed during section 4 is that, not a broken service. Raising the
WSL2 allocation is a `.wslconfig` change on the host.

## 2. Credentials

Seven variables, all of them required: the compose files interpolate every one bare, with no default,
so a missing value is a refused start rather than a placeholder that could become a committed secret.
Copy the example and fill it in.

```powershell
Copy-Item .env.example .env
```

| Variable | Where the value comes from |
| --- | --- |
| `MINIO_ROOT_USER` | your choice; MinIO wants at least three characters |
| `MINIO_ROOT_PASSWORD` | generated |
| `POSTGRES_USER` | your choice |
| `POSTGRES_PASSWORD` | generated, and not the same value as any other |
| `POSTGRES_DB` | already `platform` in the example file |
| `AIRFLOW_FERNET_KEY` | generated, by the second command below |
| `AIRFLOW_ADMIN_PASSWORD` | generated, and a third distinct value |

```powershell
# once per password -- three runs, three different values
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(24))"
# once, for AIRFLOW_FERNET_KEY
.venv\Scripts\python.exe -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Both are standard library only, on the interpreter this project already has, on every platform it
supports. They print and store nothing; nothing is saved until you paste it. There is an ordering
wrinkle: the virtual environment those paths refer to does not exist until section 3 runs `setup`.
Either run `./make.ps1 setup` first and come back, or substitute `py -3` — they import nothing outside
the standard library, so any interpreter will do.

`.env` goes at the repository root, next to `.env.example`, which is where compose reads it from now
that every invocation passes `--project-directory .`
([`decisions/004`](decisions/004-anchor-the-compose-project-directory.md)). It is gitignored. If you
would rather not have credentials in a file at all, compose reads the process environment too: set the
seven variables in the shell and skip `.env` entirely. The doctor and the test suite both count either
as satisfied, and an exported value wins over the file, because that is compose's own precedence.

There is no `AIRFLOW_ADMIN_USER`. Airflow's login is `admin` with the password above — pinned rather
than configurable, because the image reads a username variable of its own and a configurable one had
produced an account nobody could log into
([`decisions/008`](decisions/008-airflow-creates-the-admin-it-is-given.md)).

### Which of these you can still change later, and which you cannot

**Four are read once, ever.** `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` are read while
initialising an empty data volume; `AIRFLOW_ADMIN_PASSWORD` is read while the entrypoint creates an
admin account in a database that has none. All four are ignored on every start afterwards, so what you
paste in now is what that volume keeps until you `clean` it.

The other three are re-read every start, with one trap of its own: replacing `AIRFLOW_FERNET_KEY` is
accepted silently and makes every connection and variable already encrypted under the old key
unreadable. That is data loss rather than an error.

`preflight/credentials.py` states which timing applies to each variable and what changing it late
costs, and two tests fail if that table and `.env.example` ever stop describing the same set — so
copying the example file is guaranteed to give you the complete list, and the table above cannot
silently drift from it. The doctor's volume check covers the Postgres three
([`decisions/009`](decisions/009-a-volume-records-what-it-was-built-with.md)); nothing can check the
Fernet key, because a silent no-op leaves no trace to compare against.

## 3. The gate

Everything in this section runs with no container runtime at all. Network access is needed once:
`setup` installs pinned dependencies, and the first `hooks` run downloads the pinned hook revisions.

```powershell
./make.ps1 setup      # make setup
./make.ps1 check      # make check -- lint, format, types, hooks, tests
```

`check` is the whole gate, and green here is the precondition for section 4 being worth starting. It
runs `ruff check`, `ruff format --check`, `mypy`, `pre-commit run --all-files` and `pytest`. Section 5
has the output each one should produce.

`pre-commit` prints one line per hook and no summary, so there is no "8 hooks passed" line to look
for — count the lines. The eight are `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`,
`check-merge-conflict`, `detect-private-key`, `check-added-large-files`, `ruff check` and
`ruff format`.

`pytest` has three legitimate outcomes here, and which one you get says what the machine has rather
than whether anything is wrong. They are in section 5 with what separates them.

## 4. Build and the integration tier

The integration tier starts and stops the stack itself — three idempotency tests on the quickstart
profile, three smoke tests on the full one — and every compose call inside it has a 600-second
timeout. So the work in this section is doing the *pulling and building* first, by hand, outside
anything timed. Pull inside the suite and a slow network arrives as a failed assertion about
idempotency.

```powershell
./make.ps1 doctor            # the preconditions alone, starting nothing
./make.ps1 config            # renders the compose files; prints resolved mount paths
./make.ps1 build             # the MLflow image, once, outside anything timed
./make.ps1 up-quickstart     # first pull, ~4 GB
./make.ps1 ps
./make.ps1 up                # the rest of the ~20 GB: second worker and Airflow
./make.ps1 ps
./make.ps1 down              # keeps volumes; the suite expects to start from stopped
.venv\Scripts\python.exe -m pytest
```

`build` comes before either `up` for one reason: both `up` targets bound their wait, and a cold build
inside that budget is minutes spent on work whose result is identical every time. It prints two
`pip install` lines and ends in a tagged image, after which `docker images mlops-platform/mlflow`
shows `2.13.0`. If the install step fails, that is PyPI or the network rather than the stack — and it
fails here, where it is legible, instead of 300 seconds into a `--wait`.

**Zero skipped is part of the pass condition.** This is the only place the integration tier ever runs,
so a skip here is a test that has never executed anywhere. Each skip reason names the precondition it
is still waiting on ([`decisions/006`](decisions/006-preconditions-skip-by-name.md)).

### One assumption worth probing before the full profile

Airflow is configured `postgresql+psycopg2://`, and whether that image ships the driver has been
assumed here, never checked. It is the same assumption that turned out to be false for MLflow. Once
the image is local, the probe costs one command and no pull:

```powershell
docker run --rm apache/airflow:2.9.2-python3.11 python -c "import psycopg2; print(psycopg2.__version__)"
```

A version string means the assumption held. `ModuleNotFoundError` means Airflow needs the same
treatment MLflow got in [`decisions/011`](decisions/011-what-is-inside-an-image-is-a-claim.md), and it
is better to know that now than 300 seconds into the first full-profile `--wait`.

### Worth looking at once by hand

Nothing here has ever been seen running, so look at it rather than trusting the exit codes.

- **Spark master** at `http://localhost:8080` — one worker with 1 core and 1 GiB under the quickstart
  profile, two workers under the full one.
- **Airflow** at `http://localhost:8082`, as `admin` with your `AIRFLOW_ADMIN_PASSWORD`. The DAG list
  holds `m0_smoke` and nothing else. An `airflow`/`airflow` login working here would mean the admin
  fix did not take, and is worth reporting.
- **MLflow** at `http://localhost:5000` — the `m0-smoke` experiment holds one run for each time the
  suite ran, each tagged `stack=compose` and `wired=1`.

### Releasing the disk afterwards

Twenty gigabytes of images and a full set of volumes is not worth keeping between sessions.

```powershell
./make.ps1 clean                                       # this project: containers and volumes
docker compose -p mlops-platform-tests down --volumes   # the suite's own set
docker volume ls                                       # nothing mlops-* should remain
```

**Two projects, so two cleanups.** The integration tier runs under its own compose project name,
`mlops-platform-tests`, because compose otherwise derives the name from the directory basename and the
tier would share the developer's — one stack wearing two names, where a stale volume decides whether
the suite passes and a `clean` in another window deletes state a test case is mid-way through
asserting. The cost of that separation is the second line above: `make clean` cannot reach volumes
belonging to a project it does not name, and the tier's `down` keeps its volumes exactly as
`make down` does.

## 5. Expected output

Measured on the authoring machine (Python 3.12.10, no container runtime) unless the row says
otherwise.

| Command | Expected output |
| --- | --- |
| `ruff check .` | `All checks passed!` — 25 paths: the 24 modules plus `pyproject.toml`, read for configuration |
| `ruff format --check .` | `40 files already formatted` — 24 Python and 16 Markdown; the formatter handles both |
| `mypy` | `Success: no issues found in 23 source files` |
| `pre-commit run --all-files` | 8 lines, each `Passed`; no summary line |
| `pytest`, no runtime | `106 passed, 11 skipped` |
| `pytest`, runtime but no credentials | `111 passed, 6 skipped` — derived, not measured |
| `pytest`, runtime and credentials | `117 passed, 0 skipped` — derived, not measured; the M0 pass condition |
| `docker images mlops-platform/mlflow` | one row, tag `2.13.0`, after `build` |
| `make doctor` | three checks — `container runtime`, `credentials`, `postgres volume` — each `OK`, except that the volume check reports it cannot verify a volume created before the fingerprint existed |

Only the first `pytest` row is measured; the other two are derived from which guard each test carries,
because the authoring machine cannot produce them. If a run disagrees with the row it should be on,
**that disagreement is the finding** — record it before fixing it.

The eleven skips divide as five image-resolution checks, one per pinned image (they ask a registry
whether each pin still resolves, which needs a docker client); three idempotency tests; and three that
run the smoke DAG. The last six need credentials as well as a runtime, which is why the middle row
drops six rather than three.

## 6. Troubleshooting by symptom

Every entry below is either something that has actually happened here or a precondition something
actually checks. Find the symptom; the command is the first line of each answer.

### `make` is not a recognised command

Use `./make.ps1 <target>`. Every target is mirrored, and a test asserts the two stay in step.

### The doctor refuses: `container runtime`

Start Docker Desktop and wait for it to settle. If it is already running, that is worth reporting
rather than retrying — the check distinguishes "not installed" from "not running", so its message says
which it saw.

### The doctor refuses: `credentials`

Section 2. The message names every missing or still-placeholder variable rather than the first, so one
pass fills them all in.

### The doctor refuses: `postgres volume`, saying it was initialised with different credentials

`./make.ps1 reset` — which is `clean` then `up`, and destroys the volume, which is why the doctor names
it rather than doing it. Targeted, if you would rather keep the MinIO volume: `./make.ps1 down`, then
`docker volume rm mlops-platform_postgres-data`, then up again.

This is the failure that costs the most to diagnose from the outside, which is why it is now refused
before a container starts. Postgres reads `POSTGRES_USER` and `POSTGRES_PASSWORD` only while
initialising an empty volume, so a credential changed after the first `up` leaves the old role in place
([`decisions/007`](decisions/007-a-kept-volume-pins-the-first-runs-credentials.md)).

### The doctor says `postgres volume` — cannot verify

Expected, and not a bug, on any volume created before the fingerprint existed: the digest is written
when a volume is initialised, so one that predates it holds no record of what built it. It never blocks
a start, and it becomes a real answer only after a `clean` — it does not repair itself. On a volume
created from this code onwards, expect `OK`: empty before the first `up`, then matched on every start
after it.

### `FATAL: role "<the name in your .env>" does not exist`, in a container log

The same cause as the two entries above, seen from inside instead. Before the doctor existed, this
arrived as three idempotency tests claiming idempotency was broken. Both `up` targets now depend on
`doctor`, so the preflight cannot be skipped or forgotten; if you are seeing this line at all, the
volume predates the fingerprint and the doctor will have reported that it could not tell.

### A fresh clone does not clear the state

It cannot, and this is worth knowing before trying it. The compose project name comes from the
directory basename, so a new clone into a folder named `mlops-platform` reuses the very same
`mlops-platform_postgres-data`. New clone, old state. `clean` is the only thing that clears it.

### MinIO authentication failures in the tier's `mc` calls

Same cause, different symptom: MinIO re-reads its root credentials on every start, so a changed
`MINIO_ROOT_USER` shows up as an authentication failure rather than as an unhealthy container. Same
fix.

### `up --wait` times out and names a service as unhealthy

Get the probe's own output before concluding anything about the service:

```powershell
docker inspect --format '{{json .State.Health}}' mlops-platform-mlflow-1
```

An exit code of 127, or "executable file not found", is the healthcheck. Anything else is the service.
**Suspect the probe first:** three defects here so far have been the probe rather than the thing it
probes — Spark's, MLflow's and Airflow's, all the same mistake. A probe naming a binary its image lacks
can never report healthy, so `--wait` sits for its full 300 seconds and then reports a broken
*service*, which is how `mlflow is unhealthy` turned out to mean `curl is missing`. Spark's probe uses
`wget`, because that image ships no `curl`; MLflow's and Airflow's use `python`, which those two images
cannot be missing by construction.
[`decisions/005`](decisions/005-migrate-off-the-withdrawn-spark-image.md) and
[`011`](decisions/011-what-is-inside-an-image-is-a-claim.md) record all of it, and a contract test now
refuses a healthcheck naming a binary its image is not recorded as providing.

### A pinned image no longer resolves

`test_every_pinned_image_still_resolves` failing on a pin means an upstream deletion, not a bad
clone — it is the test that would have caught the Spark withdrawal that broke the first `up` on this
project. The fix is a decision record and a new publisher, not a retry, and never a switch to a
floating tag.

### `config` shows a mount resolving under `compose\`

The `postgres/init` mount must resolve to an absolute path under the *repository* root. Every
invocation passes `--project-directory .` for exactly this reason
([`decisions/004`](decisions/004-anchor-the-compose-project-directory.md)); a path under `compose\`
means an invocation that did not. While reading that output, also check that no variable is reported
unset while it is present in `.env`.

### Tests skip instead of running

Read the skip reason: each one names its own precondition rather than saying "requires docker". The
three-row table in section 5 says which count belongs to which machine state. Zero skipped is the pass
condition in section 4 and only there.

### The suite runs, but the result looks like an older version of the code

The collected item count identifies the working tree faster than reading the log:

```powershell
.venv\Scripts\python.exe -m pytest --collect-only -q | Select-Object -Last 3
git rev-list --count HEAD
git log -1 --format='%h %s'
```

The tree that ships this file collects 117 items. Anything else is a working tree somewhere in the
middle, and re-running it will keep producing whatever it produced before.

### `test_the_scheduler_registers_the_dag_without_an_import_error` fails

Airflow cannot import `airflow/dags/m0_smoke.py` at all, which would mean the DAG uses something the
pinned image does not ship. That is the one thing the contract tier already refuses — DAGs are parsed
with `ast` and may import Airflow and the standard library only — so a failure here is a genuine
surprise worth recording rather than patching
([`decisions/010`](decisions/010-a-smoke-dag-closes-m0.md)).

### The DAG runs, MLflow reports `FINISHED`, and the assertion still fails

The two ends are checked separately on purpose. A `FINISHED` run with no matching `run_uuid` row in
Postgres means the tracking server is not persisting to the backend store it was configured with,
which is a different fault from the DAG never reaching MLflow. The failure text says which of the two
it is.

### A volume with a 64-hex name appears

A hex name means the runtime created an anonymous volume because an image declares `VOLUME` at a path
the compose file does not mount — the same class as the two defects in
[`decisions/011`](decisions/011-what-is-inside-an-image-is-a-claim.md), since
`test_stateful_services_use_named_volumes` reads the compose file and an image can declare storage that
file never mentions. Attribute it before concluding anything, and do not delete it first: a deleted
volume takes the evidence with it.

```powershell
docker ps -a --filter volume=<the hex name>
docker volume inspect <the hex name>
docker image inspect ghcr.io/mlflow/mlflow:v2.13.0 --format '{{json .Config.Volumes}}'
docker image inspect apache/airflow:2.9.2-python3.11 --format '{{json .Config.Volumes}}'
```

The last two decide it: a non-`null` answer names a path the compose file should be mounting and is
not.

### `mlops-platform-tests_*` volumes are still listed after `clean`

That is the second cleanup line at the end of section 4, not a leak. `make clean` cannot reach volumes
belonging to a project it does not name.

### A container is killed during the full profile

Read it as the memory arithmetic in section 1 before reading it as a broken service. The full profile
declares about 21 GB of ceilings, 14 of them the two Spark workers, and those are ceilings rather than
reservations. Raising the allocation is a `.wslconfig` change on the host, not a repository change.
