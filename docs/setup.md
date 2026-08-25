# Setup

The one document for this repository: from a bundle on a memory stick to a green integration tier, on
a machine that has never run any of it. There is no companion note and nothing to read alongside this
file. The procedure is the same everywhere; the commands are written for PowerShell on Windows,
because that is where it is executed, and every one of them has a `make` equivalent named beside it.

Read once before starting: **nothing in section 6 has ever completed anywhere.** The gate in section 5
is measured and reproducible. The integration tier has been started far enough to find three defects
and has not yet run green end to end, which is exactly the state M0 closes out of. A failure there is
information about the compose contract, not evidence of a bad clone — record it before fixing it.

1. [Get the code](#1-get-the-code)
2. [Prerequisites](#2-prerequisites)
3. [Where this lives on the build machine](#3-where-this-lives-on-the-build-machine)
4. [Credentials](#4-credentials)
5. [The gate](#5-the-gate)
6. [Build and the integration tier](#6-build-and-the-integration-tier)
7. [Expected output](#7-expected-output)
8. [Troubleshooting by symptom](#8-troubleshooting-by-symptom)
9. [After the gate is green: the deferred version bumps](#9-after-the-gate-is-green-the-deferred-version-bumps)

## 1. Get the code

Skip this section if you already have a clone and a shell in it; start at section 2.

The code travels as a git bundle — a complete history in one file, not a snapshot, so cloning from it
reproduces every commit in order with its tags. Verify the file before trusting it, against the hash
in the transfer folder's `INDEX.md`, which is generated from the bundles themselves:

```powershell
Get-FileHash mlops-platform.bundle -Algorithm SHA256 | Format-List
```

PowerShell prints uppercase; the comparison is case-insensitive.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Desktop\GitHub"
Set-Location "$env:USERPROFILE\Desktop\GitHub"
git clone <path-to>\mlops-platform.bundle mlops-platform
Set-Location mlops-platform
git remote remove origin        # so nothing tries to push to a file
git rev-list --count HEAD ; git log -1 --format='%H %s' ; git tag
```

The last line should agree with `INDEX.md`'s row for this repository. If it does not, the bundle is
older or newer than the index, and that is worth resolving before running anything.

**A clone has no virtual environment, and is not meant to.** A bundle carries commits, and `.venv/` is
ignored rather than committed: it hardcodes its own absolute path in `pyvenv.cfg` and in every
`Scripts\*.exe` shim, so it does not survive being copied anywhere, and it is Windows-specific
besides. Section 6 builds one as its first command. The same goes for `.env`, the images and the
volumes -- nothing machine-specific or generated travels in a bundle.

**If a clone already exists, bring it forward rather than re-cloning.** A bundle is fetched by *path*,
so it does not matter that `origin` was removed:

```powershell
git fetch <path-to>\mlops-platform.bundle main:refs/remotes/bundle/main
git merge --ff-only refs/remotes/bundle/main
```

A merge that is not a fast-forward means the clone has local commits: stop and report that rather than
forcing it. Re-cloning into a new folder is the fallback, but it does **not** reset the stack's state —
compose derives its project name from the directory basename, so a clone into a folder named
`mlops-platform` finds the same volumes the old one used. Section 8 has that as its own entry.

Anywhere but a local NTFS path is a mistake worth naming, because it fails in ways that look like a
broken repository rather than like a wrong location:

- **Not on an external or exFAT drive.** exFAT has no symlinks, weak file locking and no case
  sensitivity. A virtual environment also hardcodes its absolute path in `pyvenv.cfg` and in every
  `Scripts\*.exe` shim, so it does not survive a drive letter moving — repairing one is worse than
  re-cloning. pip, mypy, ruff and pytest are all small-file workloads, several times slower over USB,
  and a drive spinning down mid-`pytest` produces I/O errors that read like corruption.
- **Not inside OneDrive or any synced tree.** A virtual environment is thousands of small files, the
  `.pytest_cache` and `.mypy_cache` churn constantly, and `git gc` rewrites packs. OneDrive holds
  handles while uploading, which surfaces as intermittent permission errors. If the Desktop is ever
  redirected, move the repository out and leave a shortcut behind — OneDrive's "Choose folders" cannot
  exclude a folder inside a synced Desktop.
- **If it does land on another fixed drive:** NTFS only, a permanent letter assigned in Disk
  Management, and `git config --global --add safe.directory F:/GitHub/mlops-platform` with forward
  slashes.

## 2. Prerequisites

| Need | Version | What it is for | Check |
| --- | --- | --- | --- |
| Git | any current | the clone, and Git Bash, which the hooks run under | `git --version` |
| Python | 3.11–3.12 | `pyproject.toml` declares `>=3.11,<3.13` | `py -3 -V` |
| A container runtime | Docker Desktop with the WSL2 backend | everything in section 6 | `docker version` |
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

## 3. Where this lives on the build machine

Facts about one machine, recorded because they are the difference between a stack that runs and one
that fills a system drive. Nothing in this repository reads any of them.

| Drive | What belongs on it | What must not |
| --- | --- | --- |
| `C:` (231 GB) | OS, Git, Python, Docker's program files, the repository and its virtual environment — under 1 GB in total | Docker's disk image. The full container profile alone is roughly 20 GB of images |
| `F:` (931 GB, SSD) | Docker's disk image, configured at `F:\docker\data` — the working drive | — |
| `D:` (465 GB) | bulk storage and second copies | Docker's image; Spark scratch |
| `E:` (4.5 TB, external HDD) | cold archive only: the bundles themselves | a clone, a virtual environment, Docker's image, or anything written during a run |

Record what the disks actually are rather than trusting the letters, since a letter can move:

```powershell
Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, BusType,
  @{n='SizeGB';e={[math]::Round($_.Size/1GB)}}
Get-Partition | Where-Object { $_.DriveLetter } | Select-Object DriveLetter, DiskNumber, Size
Get-Volume | Select-Object DriveLetter, FileSystemLabel, FileSystem,
  @{n='FreeGB';e={[math]::Round($_.SizeRemaining/1GB)}}
```

Match `DiskNumber` to `DeviceId` to know which volume sits on which physical disk.

### Docker's disk, and how to check it

The quickstart profile pulls roughly 4 GB of images; the full profile is roughly 20 GB, plus one build.
On Windows the images and volumes live in a WSL2 virtual disk whose location is a Docker Desktop
setting — put it on a drive with room, and prefer an SSD, since every pull, build and Spark shuffle
spill lands there.

`docker info --format '{{.DockerRootDir}}'` is **not** the check — it prints `/var/lib/docker`, a path
inside the WSL2 VM, whichever host drive backs it. Find the backing file instead:

```powershell
Get-ChildItem <the configured location> -Recurse -Filter *.vhdx |
  Select-Object FullName, @{n='SizeGB';e={[math]::Round($_.Length/1GB, 2)}}
wsl --list -v      # docker-desktop should be Running
```

### Memory

Worth knowing before the full profile rather than during it. The quickstart override caps its services
at 3.75 GiB of ceilings in total. The full profile declares about 21 GB, of which two Spark workers at
7g each are 14. Those are ceilings and not reservations, and nothing at M0 gives Spark real work, so a
runtime with less than 21 GB is expected to be fine here — but it is over-committed, and a container
killed during section 6 is that, not a broken service. Raising the WSL2 allocation is a `.wslconfig`
change on the host.

## 4. Credentials

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
wrinkle: the virtual environment those paths refer to does not exist until section 5 runs `setup`.
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

**These values are rendered in full by `./make.ps1 config`.** That output is the interpolated compose
file, so it carries every password and the Fernet key in plaintext. It is the right thing to read while
diagnosing and the wrong thing to paste into a file, an issue, a chat or a blog post without replacing
each value with the name of the variable it came from.

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

## 5. The gate

Everything in this section runs with no container runtime at all. Network access is needed once:
`setup` installs pinned dependencies, and the first `hooks` run downloads the pinned hook revisions.

```powershell
./make.ps1 setup      # make setup
./make.ps1 check      # make check -- lint, format, types, hooks, tests
```

`check` is the whole gate, and green here is the precondition for section 6 being worth starting. It
runs `ruff check`, `ruff format --check`, `mypy`, `pre-commit run --all-files` and `pytest`. Section 7
has the output each one should produce.

`pre-commit` prints one line per hook and no summary, so there is no "8 hooks passed" line to look
for — count the lines. The eight are `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`,
`check-merge-conflict`, `detect-private-key`, `check-added-large-files`, `ruff check` and
`ruff format`.

`pytest` has three legitimate outcomes here, and which one you get says what the machine has rather
than whether anything is wrong. They are in section 7 with what separates them.

## 6. Build and the integration tier

The integration tier starts and stops the stack itself — three idempotency tests on the quickstart
profile, three smoke tests on the full one — and every compose call inside it has a 600-second
timeout. So the work in this section is doing the *pulling and building* first, by hand, outside
anything timed. Pull inside the suite and a slow network arrives as a failed assertion about
idempotency.

**Nothing else may be holding the stack's ports when the suite runs.** The tier runs under its own
compose project name, which isolates containers, networks and volumes — but not published host ports,
and the compose file publishes fixed ones: `8080`, `7077`, `9000`, `9001`, `5000` and `8082`. A stack
left up from a by-hand session takes every one of them, and the tier then fails with `Bind for
0.0.0.0:7077 failed: port is already allocated` under a test name that claims idempotency is at fault.
This is an open defect rather than a rule of nature, and section 8 has it as its own entry. Until it is
fixed, `down` first and prove it:

```powershell
./make.ps1 doctor            # the preconditions alone, starting nothing
./make.ps1 config            # renders the compose files; prints resolved mount paths
./make.ps1 build             # the MLflow image, once, outside anything timed
./make.ps1 up-quickstart     # first pull, ~4 GB
./make.ps1 ps
./make.ps1 up                # the rest of the ~20 GB: second worker and Airflow
./make.ps1 ps
./make.ps1 down              # keeps volumes; the suite expects to start from stopped
docker ps                    # must list nothing -- this is the port check, not a formality
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
is better to know that now than 300 seconds into the first full-profile `--wait`. Note which image the
answer came from: the probe is only about `apache/airflow`, and the MLflow image installs
`psycopg2-binary` itself, so a failure there would be a build failure with a `pip` line attached.

### Worth looking at once by hand

Nothing here has ever been seen running green, so look at it rather than trusting the exit codes.

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
./make.ps1 clean                                        # this project: containers and volumes
docker compose -p mlops-platform-tests down --volumes    # the suite's own set
docker volume ls                                        # nothing mlops-* should remain
```

**Two projects, so two cleanups.** The integration tier runs under its own compose project name,
`mlops-platform-tests`, because compose otherwise derives the name from the directory basename and the
tier would share the developer's — one stack wearing two names, where a stale volume decides whether
the suite passes and a `clean` in another window deletes state a test case is mid-way through
asserting. The cost of that separation is the second line above: `make clean` cannot reach volumes
belonging to a project it does not name, and the tier's `down` keeps its volumes exactly as
`make down` does.

## 7. Expected output

Measured on the authoring machine (Python 3.12.10, no container runtime) unless the row says
otherwise.

| Command | Expected output |
| --- | --- |
| `ruff check .` | `All checks passed!` — 25 paths: the 24 modules plus `pyproject.toml`, read for configuration |
| `ruff format --check .` | `41 files already formatted` — 24 Python and 17 Markdown; the formatter handles both |
| `mypy` | `Success: no issues found in 23 source files` |
| `pre-commit run --all-files` | 8 lines, each `Passed`; no summary line |
| `pytest`, no runtime | `107 passed, 11 skipped` |
| `pytest`, runtime but no credentials | `112 passed, 6 skipped` — derived, not measured |
| `pytest`, runtime and credentials | `118 passed, 0 skipped` — derived, not measured; the M0 pass condition |
| `docker images mlops-platform/mlflow` | one row, tag `2.13.0`, after `build` |
| `make doctor` | three checks — `container runtime`, `credentials`, `postgres volume` — each `OK`, except that the volume check reports it cannot verify a volume created before the fingerprint existed |

Only the first `pytest` row is measured; the other two are derived from which guard each test carries,
because the authoring machine cannot produce them. If a run disagrees with the row it should be on,
**that disagreement is the finding** — record it before fixing it.

The eleven skips divide as five image-resolution checks, one per registry reference — the four tags
the spine pulls plus the base the one built image comes from (they ask a registry whether each still
resolves, which needs a docker client); three idempotency tests; and three that run the smoke DAG.
The last six need credentials as well as a runtime, which is why the middle row drops six rather than
three.

**The best result the tier has produced so far** is `3 failed, 110 passed, 2 skipped, 3 errors in
190.24s`, on the build machine, with every one of the six failures caused by host ports already being
bound. It is recorded here because it is the current honest ceiling, not a target: the row above it is
the pass condition.

## 8. Troubleshooting by symptom

Every entry below is either something that has actually happened here or a precondition something
actually checks. Find the symptom; the command is the first line of each answer.

### `make` is not a recognised command

Use `./make.ps1 <target>`. Every target is mirrored, and a test asserts the two stay in step.

### `Bind for 0.0.0.0:<port> failed: port is already allocated`

Something already holds one of the stack's published ports — almost always a stack left up from a
by-hand session, since the tier's own project name isolates everything *except* host ports.

```powershell
docker ps --format '{{.Names}}\t{{.Ports}}'
./make.ps1 down
docker compose -p mlops-platform-tests down
```

Then re-run. This is the third defect the first tier runs found, and it is a design defect rather than
a machine one: two compose project names that publish the same fixed host ports cannot coexist, so the
isolation the second name bought is partial. Every failure in the first full tier run traced to it —
including a Spark master that then crashed with `java.net.UnknownHostException: <container id>:
Temporary failure in name resolution`, which is debris from the aborted network programming rather than
a Spark fault: a container whose endpoint never finished being created has no name to resolve.

### The doctor refuses: `container runtime`

Start Docker Desktop and wait for it to settle. If it is already running, that is worth reporting
rather than retrying — the check distinguishes "not installed" from "not running", so its message says
which it saw.

### The doctor refuses: `credentials`

Section 4. The message names every missing or still-placeholder variable rather than the first, so one
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

Read the tag it names before believing that, because the module probes two different kinds of
reference: the tags this spine pulls, and the `FROM` of the one it builds. A failure naming
`ghcr.io/mlflow/mlflow:v2.13.0`, `apache/spark:3.5.1-python3`, `apache/airflow:2.9.2-python3.11`,
`postgres:16.3-alpine` or `minio/minio:…` is the withdrawal case above. A failure naming
`mlops-platform/mlflow:2.13.0` is not — no registry has heard of a tag this repository produces, so
that is the sorting itself having regressed, and
[`decisions/012`](decisions/012-a-built-tag-is-not-a-registry-fact.md) is the entry to read.

### `config` shows a mount resolving under `compose\`

The `postgres/init` mount must resolve to an absolute path under the *repository* root. Every
invocation passes `--project-directory .` for exactly this reason
([`decisions/004`](decisions/004-anchor-the-compose-project-directory.md)); a path under `compose\`
means an invocation that did not. While reading that output, also check that no variable is reported
unset while it is present in `.env`.

### Tests skip instead of running

Read the skip reason: each one names its own precondition rather than saying "requires docker". The
three-row table in section 7 says which count belongs to which machine state. Zero skipped is the pass
condition in section 6 and only there.

### The suite runs, but the result looks like an older version of the code

The collected item count identifies the working tree faster than reading the log:

```powershell
.venv\Scripts\python.exe -m pytest --collect-only -q | Select-Object -Last 3
git rev-list --count HEAD
git log -1 --format='%h %s'
```

The tree that ships this file collects 118 items. Anything else is a working tree somewhere in the
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

That is the second cleanup line at the end of section 6, not a leak. `make clean` cannot reach volumes
belonging to a project it does not name.

### A container is killed during the full profile

Read it as the memory arithmetic in section 3 before reading it as a broken service. The full profile
declares about 21 GB of ceilings, 14 of them the two Spark workers, and those are ceilings rather than
reservations. Raising the allocation is a `.wslconfig` change on the host, not a repository change.

## 9. After the gate is green: the deferred version bumps

Held back deliberately, so that a failure on a new machine cannot be confused with a failure caused by
a bump. One tool per commit, each with `tests/test_toolchain_pins.py` extended to assert the new pin,
and the whole gate re-run between commits.

| Tool | Pinned here | Latest known |
| --- | --- | --- |
| mypy | 1.10.0 | 2.3.1 |
| pytest | 8.2.2 | 9.1.1 |
| pre-commit | 3.7.1 | 4.6.2 |
| pre-commit-hooks (rev) | v4.6.0 | latest tag |

M1 is the next milestone after that, and it is about the one image this repository builds: multi-stage,
non-root, an SBOM and a scan step in CI. `docs/decisions/` carries the reasoning for everything above,
one record per decision, and `COMPONENTS.md` maps every folder to what it is for.
