# Setup

The one document for this repository: from a bundle on a memory stick to a green integration tier, on
a machine that has never run any of it. There is no companion note and nothing to read alongside this
file. The procedure is the same everywhere; the commands are written for PowerShell on Windows,
because that is where it is executed, and every one of them has a `make` equivalent named beside it.

Read once before starting: **every step below has now completed on a real machine**, and the whole
procedure is measured rather than derived. Getting there found four defects, three of them in healthchecks
rather than in the services they probed and one in the tier's own host ports, and each is a troubleshooting
entry in section 8. A failure here is still information about the compose contract rather than evidence of a
bad clone, so record it before fixing it.

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

The code travels as a git bundle: a complete history in one file, not a snapshot, so cloning from it
reproduces every commit in order with its tags. Verify the file before trusting it, against the hash
in the **bundle facts** block that the transfer folder's copy of this guide carries at its top,
generated from the bundle itself:

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

The last line should agree with the **bundle facts** rows. If it does not, the bundle is
older or newer than those facts, and that is worth resolving before running anything.

**A clone has no virtual environment, and is not meant to.** A bundle carries commits, and `.venv/` is
ignored rather than committed: it hardcodes its own absolute path in `pyvenv.cfg` and in every
`Scripts\*.exe` shim, so it does not survive being copied anywhere, and it is Windows-specific
besides. Section 6 builds one as its first command. The same goes for `.env`, the images and the
volumes. Nothing machine-specific or generated travels in a bundle.

**A clone made before 2026-08-25 cannot be brought forward and has to be replaced.** This
repository's history was rewritten on that date. Every file in the tree is identical, but no commit id
is, so an older clone shares no ancestor with this bundle: the `git fetch` below will succeed and the
`git merge --ff-only` will then refuse, for want of a common ancestor. That refusal is not the
"clone has local commits" case in the next paragraph and forcing it is not the fix. Delete the old
working copy and clone the bundle fresh. Comparing `git rev-parse HEAD` in the old clone against the
HEAD row in the bundle facts block is how to tell which side you are on before you start.

**Otherwise, if a clone already exists, bring it forward rather than re-cloning.** A bundle is fetched
by *path*, so it does not matter that `origin` was removed:

```powershell
git fetch <path-to>\mlops-platform.bundle main:refs/remotes/bundle/main
git merge --ff-only refs/remotes/bundle/main
```

A merge that is not a fast-forward means the clone has local commits: stop and report that rather than
forcing it. Re-cloning into a new folder is the fallback, but it does **not** reset the stack's state:
compose derives its project name from the directory basename, so a clone into a folder named
`mlops-platform` finds the same volumes the old one used. Section 8 has that as its own entry.

Anywhere but a local NTFS path is a mistake worth naming, because it fails in ways that look like a
broken repository rather than like a wrong location:

- **Not on an external or exFAT drive.** exFAT has no symlinks, weak file locking and no case
  sensitivity. A virtual environment also hardcodes its absolute path in `pyvenv.cfg` and in every
  `Scripts\*.exe` shim, so it does not survive a drive letter moving, and repairing one is worse than
  re-cloning. pip, mypy, ruff and pytest are all small-file workloads, several times slower over USB,
  and a drive spinning down mid-`pytest` produces I/O errors that read like corruption.
- **Not inside OneDrive or any synced tree.** A virtual environment is thousands of small files, the
  `.pytest_cache` and `.mypy_cache` churn constantly, and `git gc` rewrites packs. OneDrive holds
  handles while uploading, which surfaces as intermittent permission errors. If the Desktop is ever
  redirected, move the repository out and leave a shortcut behind; OneDrive's "Choose folders" cannot
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
| GNU Make | optional, and unused by the suite | no test invokes `make`, and CI does not either: it calls the same tools in the same order so a runner needs no `make`. The Makefile stays canonical for a person reading it, and `tests/test_makefile_recipes.py` checks every recipe with `sh -n` rather than by running one | `make --version` |
| `sh`, `sha256sum`, `od` | **required for a zero-skip run** | two preflight tests execute the Postgres init script and compare its digest against the Python one, and eighteen more parse the Makefile's recipes with `sh -n`; without a POSIX shell all twenty skip by name | `sh --version` |

**On that last row, because it costs a confusing half hour otherwise.** Git for Windows already ships all
three, in `usr\bin` beside the installation, but PowerShell does not have that directory on `PATH`, so a run
from PowerShell skips those twenty tests and reports `203 passed, 33 skipped` with everything else green. Add it
for the session and they run:

```powershell
$gitUsrBin = Join-Path (Split-Path (Split-Path (Get-Command git).Source)) 'usr\bin'
$env:PATH = "$gitUsrBin;$env:PATH"
```

The skip is correct behaviour on a host that genuinely lacks a shell; it is only misleading on a host that
has one and cannot see it.

Set the commit identity **per repository rather than globally**, before the first commit:

```powershell
git config user.name  "bytes-of-entropy"
git config user.email "204384232+bytes-of-entropy@users.noreply.github.com"
```

Every commit already in this history carries that identity. Setting it locally keeps this repository
right without disturbing whatever global identity the machine uses for unrelated work, which is the
case worth guarding: a machine whose global identity belongs to an employer will otherwise sign these
commits with it. The address is GitHub's no-reply form for the account, so commits attribute to the
profile without publishing a mailbox. Skip this and the history acquires a second author.

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
| `C:` (231 GB) | OS, Git, Python, Docker's program files, the repository and its virtual environment, under 1 GB in total | Docker's disk image. The full container profile alone is roughly 20 GB of images |
| `F:` (931 GB, SSD) | Docker's disk image, configured at `F:\docker\data` , the working drive | none |
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
setting: put it on a drive with room, and prefer an SSD, since every pull, build and Spark shuffle
spill lands there.

`docker info --format '{{.DockerRootDir}}'` is **not** the check. It prints `/var/lib/docker`, a path
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
runtime with less than 21 GB is expected to be fine here, but it is over-committed, and a container
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
# once per password: three runs, three different values
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(24))"
# once, for AIRFLOW_FERNET_KEY
.venv\Scripts\python.exe -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Both are standard library only, on the interpreter this project already has, on every platform it
supports. They print and store nothing; nothing is saved until you paste it. There is an ordering
wrinkle: the virtual environment those paths refer to does not exist until section 5 runs `setup`.
Either run `./make.ps1 setup` first and come back, or substitute `py -3`; they import nothing outside
the standard library, so any interpreter will do.

`.env` goes at the repository root, next to `.env.example`, which is where compose reads it from now
that every invocation passes `--project-directory .`
([`decisions/004`](decisions/004-anchor-the-compose-project-directory.md)). It is gitignored. If you
would rather not have credentials in a file at all, compose reads the process environment too: set the
seven variables in the shell and skip `.env` entirely. The doctor and the test suite both count either
as satisfied, and an exported value wins over the file, because that is compose's own precedence.

There is no `AIRFLOW_ADMIN_USER`. Airflow's login is `admin` with the password above, pinned rather
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
costs, and two tests fail if that table and `.env.example` ever stop describing the same set, so
copying the example file is guaranteed to give you the complete list, and the table above cannot
silently drift from it. The doctor's volume check covers the Postgres three
([`decisions/009`](decisions/009-a-volume-records-what-it-was-built-with.md)); nothing can check the
Fernet key, because a silent no-op leaves no trace to compare against.

## 5. The gate

Everything in this section runs with no container runtime at all. Network access is needed once:
`setup` installs pinned dependencies, and the first `hooks` run downloads the pinned hook revisions.

```powershell
./make.ps1 setup      # make setup
./make.ps1 check      # make check: lint, format, types, hooks, tests
```

`check` is the whole gate, and green here is the precondition for section 6 being worth starting. It
runs `ruff check`, `ruff format --check`, `mypy`, `pre-commit run --all-files` and `pytest`. Section 7
has the output each one should produce.

`pre-commit` prints one line per hook and no summary, so there is no "8 hooks passed" line to look
for; count the lines. The eight are `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`,
`check-merge-conflict`, `detect-private-key`, `check-added-large-files`, `ruff check` and
`ruff format`.

`pytest` has three legitimate outcomes here, and which one you get says what the machine has rather
than whether anything is wrong. They are in section 7 with what separates them.

## 6. Build and the integration tier

The integration tier starts and stops the stack itself (three idempotency tests on the quickstart
profile, three smoke tests on the full one), and every compose call inside it has a 600-second
timeout. So the work in this section is doing the *pulling and building* first, by hand, outside
anything timed. Pull inside the suite and a slow network arrives as a failed assertion about
idempotency.

**The tier no longer needs the machine's ports to itself.** It runs under its own compose project
name, which isolates containers, networks and volumes but not published host ports. So the compose
file names no fixed host port of its own: the host half of each mapping is a variable whose default is
the number `make up` has always published, and the tier sets each one to `0`, which asks Docker for a
free port at bind time
([`decisions/013`](decisions/013-the-kernel-chooses-the-tiers-host-ports.md)). A stack left up from
a by-hand session is no longer a reason for the suite to fail. Bring it down first anyway if you
want a clean read of the timings, since two stacks on one machine share its CPU and its disk:

```powershell
./make.ps1 doctor            # the preconditions alone, starting nothing
./make.ps1 config            # renders the compose files; prints resolved mount paths
./make.ps1 build             # the MLflow image, once, outside anything timed
./make.ps1 up-quickstart     # first pull, ~4 GB
./make.ps1 ps
./make.ps1 up                # the rest of the ~20 GB: second worker and Airflow
./make.ps1 ps
./make.ps1 down              # keeps volumes; the suite expects to start from stopped
docker ps                    # what is still up, if anything
.venv\Scripts\python.exe -m pytest
```

`build` comes before either `up` for one reason: both `up` targets bound their wait, and a cold build
inside that budget is minutes spent on work whose result is identical every time. It prints two
`pip install` lines and ends in a tagged image, after which `docker images mlops-platform/mlflow`
shows `2.22.4`. If the install step fails, that is PyPI or the network rather than the stack, and it
fails here, where it is legible, instead of 300 seconds into a `--wait`.

**Zero skipped is part of the pass condition.** This is the only place the integration tier ever runs,
so a skip here is a test that has never executed anywhere. Each skip reason names the precondition it
is still waiting on ([`decisions/006`](decisions/006-preconditions-skip-by-name.md)).

### One assumption worth probing before the full profile

Airflow is configured `postgresql+psycopg2://`, and whether that image ships the driver has been
assumed here, never checked. It is the same assumption that turned out to be false for MLflow. Once
the image is local, the probe costs one command and no pull:

```powershell
docker run --rm apache/airflow:2.11.2-python3.11 python -c "import psycopg2; print(psycopg2.__version__)"
```

A version string means the assumption held. `ModuleNotFoundError` means Airflow needs the same
treatment MLflow got in [`decisions/011`](decisions/011-what-is-inside-an-image-is-a-claim.md), and it
is better to know that now than 300 seconds into the first full-profile `--wait`. Note which image the
answer came from: the probe is only about `apache/airflow`, and the MLflow image installs
`psycopg2-binary` itself, so a failure there would be a build failure with a `pip` line attached.

### Worth looking at once by hand

Nothing here has ever been seen running green, so look at it rather than trusting the exit codes.

- **Spark master** at `http://localhost:8080`: one worker with 1 core and 1 GiB under the quickstart
  profile, two workers under the full one.
- **Airflow** at `http://localhost:8082`, as `admin` with your `AIRFLOW_ADMIN_PASSWORD`. The DAG list
  holds `m0_smoke` and nothing else. An `airflow`/`airflow` login working here would mean the admin
  fix did not take, and is worth reporting.
- **MLflow** at `http://localhost:5000`: the `m0-smoke` experiment holds one run for each time the
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
tier would share the developer's: one stack wearing two names, where a stale volume decides whether
the suite passes and a `clean` in another window deletes state a test case is mid-way through
asserting. The cost of that separation is the second line above: `make clean` cannot reach volumes
belonging to a project it does not name, and the tier's `down` keeps its volumes exactly as
`make down` does.

## 7. Expected output

Measured on the authoring machine (Python 3.12.10, no container runtime) unless the row says
otherwise.

| Command | Expected output |
| --- | --- |
| `ruff check .` | `All checks passed!` for 36 paths: the 35 modules plus `pyproject.toml`, read for configuration |
| `ruff format --check .` | `61 files already formatted`: 35 Python and 27 Markdown, less `.pytest_cache/README.md`, which is ignored by git and therefore by the formatter. The six committed inventories are neither, so the formatter never reads them |
| `mypy` | `Success: no issues found in 33 source files` |
| `pre-commit run --all-files` | 8 lines, each `Passed`; no summary line |
| `pytest`, no runtime | `223 passed, 13 skipped` |
| `pytest`, runtime but no credentials | `228 passed, 8 skipped`, derived rather than measured |
| `pytest`, runtime and credentials | `236 passed, 0 skipped`, derived. The six inventories are committed as of this commit, so the parameterised shape check has real files in any clone and there is no longer a before-and-after-`make sbom` distinction to draw |
| `docker images mlops-platform/mlflow` | one row, tag `2.22.4`, after `build` |
| `make doctor` | three checks (`container runtime`, `credentials`, `postgres volume`), each `OK`, except that the volume check reports it cannot verify a volume created before the fingerprint existed |

Only the first `pytest` row is measured. The other three are derived from which guard each test carries,
because the authoring machine has no container runtime and cannot produce any of them. If a run disagrees
with the row it should be on, **that disagreement is the finding**. Record it before fixing it.

The derivation is a method rather than a guess: each row is the first row plus the tests whose guards a
run would clear. It has matched three times — `140 passed, 0 skipped`, then `220 passed, 1 skipped`, then
`220 passed, 0 skipped`, each derived on a machine with no container runtime and then measured exactly.

The fourth time is worth reading precisely, because it is the one that shows what the method does and does
not buy. `226 passed, 0 skipped` was derived; the run collected 226 tests and reported `225 passed, 1
failed`. The arithmetic was right and the claim was wrong. A derived row predicts *which tests will run*,
which is a fact about guards and can be reasoned out here; it cannot predict whether they pass, which is a
fact about the world and is the entire reason the run happens.

The thirteen skips divide as five image-resolution checks, one per registry reference: the five images the
spine pulls, including the base the one built image comes from (they ask a registry whether each still
resolves, which needs a docker client); two artifact-store checks; three idempotency tests; and three that
run the smoke DAG. Eight of them need credentials as well as a runtime -- the two artifact-store checks
reach into MinIO and the six DAG and idempotency tests start real stacks -- which is why the middle row
clears five rather than thirteen. There used to be a fourteenth, an empty parameter set where the
committed-inventory check had no files to run against; committing the inventories turned it into six real
assertions.

**Every row above assumes `sh`, `sha256sum` and `od` are reachable.** Without them, subtract twenty from
the passed count and add twenty to the skipped count in each row: two preflight tests execute the Postgres
init script, and eighteen parse the Makefile's recipes, and all twenty are gated on a POSIX shell rather
than on a runtime, so no amount of Docker unskips them. Measured, not derived: `203 passed, 33 skipped`
on the authoring machine with `sh`, `sha256sum` and `od` taken off `PATH`.

**The tier reached the pass condition on the build machine twice**: `120 passed, 0 skipped` at the commit tagged `v0.1.0`, and `124 passed, 0 skipped` at `v0.1.2`, after `docs/decisions/015` added two artifact-store tests and two compose-contract tests. The second run is the stronger evidence: the first passed while a configured artifact root pointed at a bucket nothing created, because no test then walked that path. Two earlier runs are
worth keeping beside it, because both were misread at the time. `3 failed, 110 passed, 2 skipped, 3 errors in
190.24s` was the first, and all six of those failures traced to host ports already being bound rather than to
six separate defects. Then `118 passed, 2 skipped in 267.77s`, which was a fully green tier whose two
remaining skips looked like a tier problem and were the `PATH` gap described in section 3.

## 7b. M1: what the image guarantees, and the one step that needs a registry

The built image runs as a named non-root account, `mlflow` at uid 10001, created in the Dockerfile with
no login shell. Seven tests in `tests/test_image_contract.py` assert that and three other properties by
**reading** the Dockerfile rather than by building it, so they run on any machine: the final `USER` is
not root and is an account the image creates, no base names a moving tag, every `pip install` pins with
`==` and leaves no wheel cache, and a copied script is not writable by the user that executes it.
Record 017 argues each, and records why this image is not rebuilt multi-stage from a slim base.

**Digest pinning is done, and one reference is deliberately exempt.** Every pulled `image` key and
every `FROM` now carries both a tag and a digest, as `name:tag@sha256:...`: the tag because it is what a
reader recognises and what a version bump edits, the digest because it is what the build resolves.
`mlops-platform/mlflow:2.22.4` stays a bare tag, because it is built here and a local digest is a fact
about one machine's image store rather than a registry fact — pinning it would tie the spine to an
artifact nobody else can pull, which is precisely the mistake record 012's title names. Five assertions
enforce all of that with no daemon, reusing record 012's own pulled-versus-built split so a service
gaining a `build` key moves between the rules rather than escaping both. Record 018 argues it.

Re-resolving the digests, when a version is bumped, takes one command on a host that has pulled them:

```powershell
Select-String -Path compose/*.yml -Pattern 'image:\s*(\S+)' |
  ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique |
  ForEach-Object { "$_  $(docker image inspect --format '{{index .RepoDigests 0}}' $_)" }
```

Use that rather than `config --images`, which reports only the default profile and silently omitted
`apache/airflow` the first time.

### The SBOM and the scan

`make sbom` catalogues every image the spine names and writes two files per image into `sbom/`: the SPDX
document, which is generated and **not** committed, and a sorted `name==version` inventory, which is. The
split is the whole decision. SPDX carries a document UUID and a creation timestamp, so a committed one
produces a diff on every regeneration whether the image changed or not, and a file that always diffs is a
file nobody reads. The inventory changes only when the image does, which makes a one-line diff mean
something. Record 019 argues it, and `sbom/.gitignore` enforces the half a convention would not.

The image list comes from `supply.images`, which reads the `image` keys out of the compose file, and
deliberately **not** from `docker compose config --images`. That is the obvious tool and it is the wrong
one: it reports the services of the profiles it was given, and it has already left `apache/airflow` out of
this repository's list once — the same omission is recorded three paragraphs up, where it cost a
re-resolution. A cataloguer fed a short list writes an inventory short in exactly the same way, and an
inventory nobody can tell is incomplete reads as a clean bill of health. Reading the `image` keys is
exhaustive by construction: five references come back, one of them the image built here, which is the only
one whose contents are a decision made in this repository and so the one least defensible to omit.

`make scan` reads those SPDX documents rather than the images, so what is scanned is what was inventoried
and a finding can be traced to a committed line. It fails on `high` or above.

All four supply settings take a value from the environment — `SYFT`, `GRYPE`, `SBOM_DIR`, `SCAN_FAIL_ON` —
and the one that earns its keep is `SCAN_FAIL_ON=none`, which reports every finding and gates on nothing.
That is what a first scan wants: an image nobody has scanned yet should produce a whole finding table rather
than stopping at the first High, and getting there should not require editing a tracked file. `none` is this
repository's spelling, not grype's; grype omits the flag, and both entrypoints translate.

```powershell
$env:SCAN_FAIL_ON = 'none'; .\make.ps1 scan   # report everything, fail on nothing
Remove-Item Env:\SCAN_FAIL_ON                  # back to gating on high
```

```bash
SCAN_FAIL_ON=none make scan
```

A mirror test asserts both entrypoints honour all four and spell the report-only case the same way, because
an override that works on Linux and silently does nothing on Windows is worse than no override: the person
who needed it edits the file instead, and what they ran is not what is committed.

Both targets run their tool as a container — `anchore/syft:v1.51.1` and `anchore/grype:v0.118.0`, both
pinned by tag *and* digest — so reproducing a scan installs nothing on the host and gets the same bytes.
Those digests were owed when the mechanism landed and record 020 pays them. A test asserts the shape for
both, separate from the compose assertion in `tests/test_image_supply.py`, which reads `image` keys and
would never see a reference living in a Makefile.

**These two pins expire, and no other pin in this repository does.** One line in each entrypoint:

```
# SUPPLY_TOOLS_EXPIRE: 2027-02-28
```

Past that date the suite fails, on any machine, with no daemon. The reason is not tidiness. An image pinned
to old bytes is merely old and still works; a scanner pinned to old bytes stops working, because the thing
that makes it useful is a vulnerability database that must be fresh by definition and whose schema its
publisher retires. That is not hypothetical here: the first pin was `grype:v0.79.0`, chosen from memory
rather than from a registry, and the first real scan failed with `db could not be loaded: the vulnerability
database was built 24 weeks ago (max allowed age is 5 days)` before reading a single document. Record 020
argues it, and section 8 has the symptom. Renewing means the version, the digest and the date, edited
together.

`make scan` fetches the database with `grype db update`, then prints `grype db status` before any finding,
so the build date and schema sit above the results. Both, in that order, because `db status` reports on a
database and does not fetch one: with only the report, a fresh cache produced `database does not exist` and
the check written to observe the database was what stopped it existing. A mirror assertion now refuses a
scan target that reports without fetching. A scan result is a function of three things — the scanner, the database, the SBOM — and only
the third was visible in the output. The database is cached in a named volume, `mlops-platform-grype-db`,
because `--rm` discards the container filesystem and an uncached run downloads it once per document.

Run `build` first. The one image built here has to exist locally before there is anything to catalogue.

**Where this stands: the scan ran, the bases moved, and a third of the findings went with them.**

The first scan that worked returned **5,017 findings — 185 Critical, 1,197 High**, with 4,121 of them
naming a fixed version. Every image was 12–21 months old and 731 of the 1,382 Critical-and-High were
`deb` packages, so the number measured staleness rather than risk accepted with open eyes. Record 019 had
written down in advance that if a clean scan would need more than a handful of exceptions then the bases
are the problem; 1,382 is not a handful, so record 021 bumped every pulled reference to the newest release
in its current major line rather than writing a page of accepted CVEs.

| image | was → now | findings | Critical | High |
| --- | --- | --- | --- | --- |
| `apache/airflow` | `2.9.2` → `2.11.2-python3.11` | 1,566 → 1,193 | 88 → 68 | 481 → 320 |
| `apache/spark` | `3.5.1` → `3.5.9-python3` | 1,750 → 952 | 5 → **9** | 93 → **121** |
| `ghcr.io/mlflow/mlflow` | `v2.13.0` → `v2.22.4` | 603 → 468 | 27 → 18 | 212 → 163 |
| `mlops-platform/mlflow` | `2.13.0` → `2.22.4` | 603 → 468 | 27 → 18 | 212 → 163 |
| `minio/minio` | `2024-06-04` → `2025-09-07` | 260 → 222 | 27 → 24 | 77 → 66 |
| `postgres` | `16.3` → `16.15-alpine` | 235 → **69** | 11 → **1** | 122 → **37** |
| **total** | | **5,017 → 3,372** | **185 → 138** | **1,197 → 870** |

A third fewer findings, and four of record 021's six predictions refuted. Three results are worth more
than the total.

**`apache/spark` got safer and more severe at the same time.** Findings fell 46% while Critical rose from
5 to 9 and High from 93 to 121. A threshold set from a total would have read that image as improving while
the count that would actually gate it nearly doubled — which is an argument for the gate that comes next
to be per-severity rather than on a total.

**`apache/airflow` doubled its package count and lowered its risk.** 586 packages to 1,215, findings 1,566
to 1,193. Airflow 2.11 bundles far more providers than 2.9 and still carries less. A package count is not
a risk measure, which is worth knowing next to six committed inventories whose whole purpose is to be
counted.

**Nothing this repository installs contributes a finding, still.** `mlops-platform/mlflow` and its base
return identical counts at every severity — 468, 18, 163 — and the inventory diff is `added: 5   removed:
0`, exactly the five packages the Dockerfile installs. That held before the bump and after it.

`urllib3` is still High, in both `apache/airflow` and the MLflow base, which record 021 predicted would be
fixed and was not. Pinning it forward here is now a real option: it would be this repository's first
deliberate override of a base image's own dependency resolution, so it gets its own record rather than a
line in an existing one.

**The inventories are committed as of this milestone**, and that is what makes the table above checkable
rather than quoted. Record 019's argument for committing them is that a bump produces a readable diff, and
until now none had ever travelled back from the machine that writes them, so the property had never been
exercised. The six in `sbom/` are the baseline; the next bump diffs against them.

**The threshold is still unset, and the cheap lever is now spent.** 3,372 findings and 138 Critical is what
current-within-major looks like. The remaining levers are crossing major lines — Airflow 3, Spark 4,
Postgres 18, MLflow 3, each a migration with its own failure modes — or accepting the residue and gating
against regression. Record 021 anticipated the second: a ratchet "remains a good candidate for the
threshold *after* the bump, when what remains really is the residue". It is now the residue.

**Two things are still not done, and a green suite hides neither.**

1. **`security/exceptions.toml` is empty and not wired into the scanner.** The half that runs today is
   the half that rots: every entry needs a reason of at least forty characters and an unquoted expiry
   date, and an expired entry fails the *suite*, on any machine, with no daemon. After record 021 this is
   less urgent than it looked — the answer to a thousand findings was never a thousand exceptions.
2. **CI does not scan.** It needs the threshold, and the threshold is the next decision.

**What M1 still owes:** a threshold chosen from the numbers above, and the images in GHCR at their
digests. The second needs a credential and a decision about publishing, so it is not merely unrun work.

## 8. Troubleshooting by symptom

Every entry below is either something that has actually happened here or a precondition something
actually checks. Find the symptom; the command is the first line of each answer.

### `make` is not a recognised command

Use `./make.ps1 <target>`. Every target is mirrored, and a test asserts the two stay in step.

### `Bind for 0.0.0.0:<port> failed: port is already allocated`

Something on this machine holds a port `make up` wants. The integration tier cannot produce this any
more, since it publishes nothing at a fixed number, so the holder is another program or an earlier
stack, and the port is one of `8080`, `7077`, `9000`, `9001`, `5000` or `8082`.

```powershell
docker ps --format '{{.Names}}\t{{.Ports}}'
Get-NetTCPConnection -State Listen -LocalPort 5000 | Select-Object OwningProcess
./make.ps1 down
```

If the holder is not one of Docker's, either stop it or publish somewhere else for this session. The
host half of every mapping is a variable, so nothing needs editing to do that:

```powershell
$env:MLFLOW_HOST_PORT = '5001'   # this shell only; the compose default is still 5000
./make.ps1 up
```

This was the third defect the first tier runs found, and every failure in that run traced to it,
including a Spark master that crashed afterwards with `java.net.UnknownHostException: <container id>:
Temporary failure in name resolution`. That was debris from the aborted network programming rather
than a Spark fault: a container whose endpoint never finished being created has no name to resolve.
The fix was to stop the compose file naming host ports at all, so the tier and a by-hand stack can
hold their own, recorded in
[`decisions/013`](decisions/013-the-kernel-chooses-the-tiers-host-ports.md).
`docker compose -p mlops-platform-tests port mlflow 5000` reports what a running tier
was given, when you want to reach it.

### The doctor refuses: `container runtime`

Start Docker Desktop and wait for it to settle. If it is already running, that is worth reporting
rather than retrying. The check distinguishes "not installed" from "not running", so its message says
which it saw.

### `Error response from daemon: Docker Desktop is unable to start`

Docker Desktop is part-way up: far enough to answer the client, not far enough to run a container. On
Windows that is usually the WSL 2 backend rather than Docker itself, and the same broken WSL shows up
elsewhere as `execvpe(/bin/bash) failed: No such file or directory` from a bare `bash`, which is WSL's
`bash.exe` finding no distribution to run. Check that side first:

```powershell
wsl --status
wsl --list --verbose      # docker-desktop should be listed and Running once Desktop is up
wsl --update
```

Docker Desktop ships its own `docker-desktop` distribution, so a working WSL kernel is needed but a
Linux distribution of your own is not. `wsl --install --no-distribution` installs the kernel alone.

**This state used to produce eight failures rather than eight skips.** `docker info` answered, exited
zero and printed an empty server version, so the runtime probe called it ready and the whole
integration tier ran against a daemon that could not start anything. The probe now requires a server
version and not merely a zero exit, because only a running daemon can supply one, so this machine
state skips with a reason naming it. If you see the tier fail rather than skip on a Desktop that will
not start, that is a finding and the probe is wrong again.

### The doctor refuses: `credentials`

Section 4. The message names every missing or still-placeholder variable rather than the first, so one
pass fills them all in.

### The doctor refuses: `postgres volume`, saying it was initialised with different credentials

`./make.ps1 reset`, which is `clean` then `up`, and destroys the volume, which is why the doctor names
it rather than doing it. Targeted, if you would rather keep the MinIO volume: `./make.ps1 down`, then
`docker volume rm mlops-platform_postgres-data`, then up again.

This is the failure that costs the most to diagnose from the outside, which is why it is now refused
before a container starts. Postgres reads `POSTGRES_USER` and `POSTGRES_PASSWORD` only while
initialising an empty volume, so a credential changed after the first `up` leaves the old role in place
([`decisions/007`](decisions/007-a-kept-volume-pins-the-first-runs-credentials.md)).

### The doctor says `postgres volume`: cannot verify

Expected, and not a bug, on any volume created before the fingerprint existed: the digest is written
when a volume is initialised, so one that predates it holds no record of what built it. It never blocks
a start, and it becomes a real answer only after a `clean`; it does not repair itself. On a volume
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
probes: Spark's, MLflow's and Airflow's, all the same mistake. A probe naming a binary its image lacks
can never report healthy, so `--wait` sits for its full 300 seconds and then reports a broken
*service*, which is how `mlflow is unhealthy` turned out to mean `curl is missing`. Spark's probe uses
`wget`, because that image ships no `curl`; MLflow's and Airflow's use `python`, which those two images
cannot be missing by construction.
[`decisions/005`](decisions/005-migrate-off-the-withdrawn-spark-image.md) and
[`011`](decisions/011-what-is-inside-an-image-is-a-claim.md) record all of it, and a contract test now
refuses a healthcheck naming a binary its image is not recorded as providing.

### `database does not exist`, with `Status: invalid` and a zero build date

`make scan`, on a machine that has never run it. `grype db status` reports on a database and does not fetch
one, so on an empty cache volume there is nothing to report and the command exits non-zero. The target runs
`grype db update` first for exactly this reason; if that line is missing, the check written to observe the
database is what prevents it existing. Record 020 scores it as a defect of this repository rather than of
the pin.

`docker volume rm mlops-platform-grype-db` forces a fresh download on the next run, which is the thing to
try if the cache is suspected of holding a partial database.

### `db could not be loaded: the vulnerability database was built N weeks ago`

`make scan`, and it fails before reading a single SBOM. The scanner is too old for the database its
publisher currently serves: schema versions get retired, an old grype asks for a retired one, the newest
answer it can get is months stale, and its own five-day freshness check refuses it. The refusal is correct
and the fix is never to suppress it.

Bump the pin. Both entrypoints name `anchore/grype:` with a tag and a digest; re-resolve the digest for the
current release and move `SUPPLY_TOOLS_EXPIRE` at the same time. `GRYPE_DB_VALIDATE_AGE=false` would make
the message disappear and leave the scan reporting against a stale feed with nothing in the output saying
so, which is strictly worse than a failure. Record 020 argues all of that; the expiry test exists so this
is caught on a laptop instead of on the one machine with a daemon.

### A pinned image no longer resolves

`test_every_pinned_image_still_resolves` failing on a pin means an upstream deletion, not a bad
clone. It is the test that would have caught the Spark withdrawal that broke the first `up` on this
project. The fix is a decision record and a new publisher, not a retry, and never a switch to a
floating tag.

Read the tag it names before believing that, because the module probes two different kinds of
reference: the tags this spine pulls, and the `FROM` of the one it builds. A failure naming
`ghcr.io/mlflow/mlflow:v2.22.4`, `apache/spark:3.5.9-python3`, `apache/airflow:2.11.2-python3.11`,
`postgres:16.15-alpine` or `minio/minio:…` is the withdrawal case above. A failure naming
`mlops-platform/mlflow:2.22.4` is not, because no registry has heard of a tag this repository produces, so
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
.venv\Scripts\python.exe -m pytest --collect-only | Select-Object -Last 1
git rev-list --count HEAD
git log -1 --format='%h %s'
```

The tree that ships this file collects 124 items. Anything else is a working tree somewhere in the
middle, and re-running it will keep producing whatever it produced before.

The `-q` flag is deliberately absent from that first command. With it, `--collect-only` prints one line
per test file and no total, so the number this section asks you to compare against is not in the output
at all; without it, the last line is the total.

### `test_the_scheduler_registers_the_dag_without_an_import_error` fails

Airflow cannot import `airflow/dags/m0_smoke.py` at all, which would mean the DAG uses something the
pinned image does not ship. That is the one thing the contract tier already refuses: DAGs are parsed
with `ast` and may import Airflow and the standard library only, so a failure here is a genuine
surprise worth recording rather than patching
([`decisions/010`](decisions/010-a-smoke-dag-closes-m0.md)).

### The DAG runs, MLflow reports `FINISHED`, and the assertion still fails

The two ends are checked separately on purpose. A `FINISHED` run with no matching `run_uuid` row in
Postgres means the tracking server is not persisting to the backend store it was configured with,
which is a different fault from the DAG never reaching MLflow. The failure text says which of the two
it is.

### A volume with a 64-hex name appears

A hex name means the runtime created an anonymous volume because an image declares `VOLUME` at a path
the compose file does not mount, the same class as the two defects in
[`decisions/011`](decisions/011-what-is-inside-an-image-is-a-claim.md), since
`test_stateful_services_use_named_volumes` reads the compose file and an image can declare storage that
file never mentions. Attribute it before concluding anything, and do not delete it first: a deleted
volume takes the evidence with it.

```powershell
docker ps -a --filter volume=<the hex name>
docker volume inspect <the hex name>
docker image inspect ghcr.io/mlflow/mlflow:v2.22.4 --format '{{json .Config.Volumes}}'
docker image inspect apache/airflow:2.11.2-python3.11 --format '{{json .Config.Volumes}}'
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
