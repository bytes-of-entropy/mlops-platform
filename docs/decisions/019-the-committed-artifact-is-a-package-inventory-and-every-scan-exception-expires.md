# 019: The committed supply-chain artifact is a sorted package inventory, and every scan exception carries a reason and an expiry

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `security/`, `sbom/`
- **Milestone:** M1

## Context

M1's last two items are an SBOM per image and a vulnerability scan whose exceptions are documented. Both
have an obvious implementation that is wrong in a way worth writing down.

The obvious SBOM implementation is to run syft and commit the SPDX JSON. Two problems. The first is
size: an SPDX document for a Python-heavy image runs to hundreds of kilobytes, and this repository's own
pre-commit hook refuses a file over 512 KiB, which is a rule it has for a reason rather than an obstacle
to route around. The second is worse. SPDX documents are not byte-reproducible — they carry a document
UUID and a creation timestamp — so a committed one produces a diff on every regeneration whether the
image changed or not. A diff that always appears is a diff nobody reads, and the review value of
committing an SBOM was the whole point of committing it.

The obvious scan implementation is to fail the build on High and Critical findings and keep a list of
accepted ones. That list is where supply-chain discipline goes to die: an exception added under
deadline pressure with the comment "false positive" outlives the person who added it, the release it
unblocked, and usually the vulnerability. This repository already refuses a TODO without an expiry.
An accepted CVE is a TODO with a CVSS score attached.

## Decision

**The committed artifact is a package inventory, not the SBOM.** `make sbom` generates the full SPDX
document into `sbom/`, which is git-ignored, and derives from it a sorted `name==version` inventory per
image, which is committed. That file is small, stable across regenerations, diffable line by line, and
answers the question an SBOM is usually committed to answer: what changed in this image. The SPDX
document remains the artifact to attach to a release, where its size and its UUID cost nothing.

**A test asserts the inventory's shape rather than its contents.** Sorted, non-empty, one
`name==version` per line, no duplicates. It cannot assert which packages should be present without
becoming a second inventory that drifts from the first, which is the failure `tests/test_layering.py`
in Repo 1 avoids by reading the tree rather than listing it.

**Every scan exception carries four fields and a test refuses one that does not.** The identifier, the
package it applies to, a reason in prose, and an `expires` date. An exception past its expiry fails the
suite rather than the scan, which is deliberate: the scan runs where Docker is, and the expiry is a fact
about a text file that every machine can check. So an exception rots loudly on a laptop with no daemon.

**The exceptions file starts empty, and that is a claim.** Nothing is accepted yet because the scan has
not run. An empty file with a documented schema is honest; a file pre-populated with plausible
exceptions would be a decision made before its evidence.

**syft and grype are pulled images and record 018 applies to them.** They are pinned by tag here and
their digests are owed, exactly as the spine's were, and this record does not pretend otherwise.

## Alternative rejected

**Commit the SPDX document.** What the checklist literally asks for. Rejected on the two grounds above,
and the size one is not a technicality: routing around a file-size hook to commit a file nobody will
read is worse than not committing it, because it also weakens the hook.

**Normalise the SPDX document — strip the UUID and the timestamp — then commit it.** This is a real
option and the closest call here. Rejected because the normaliser becomes a thing to maintain, its
output is no longer a valid SPDX document so nothing downstream can consume it, and the diff it
produces is still hundreds of lines of JSON structure per package change where the inventory's is one
line. The inventory is the normalisation, done properly.

**Fail the scan on Critical only.** Fewer exceptions, less friction. Rejected because it moves the
judgement from a reviewed file into a threshold nobody revisits, and High-severity findings in a base
image are exactly the ones that turn out to matter.

**Let exceptions expire silently — warn rather than fail.** Rejected for the reason the whole record
exists: a warning in a log is an exception that never expires.

## Prediction (recorded before the evidence)

1. The first scan of the four pulled images returns at least one High or Critical finding, and it is in
   a base image rather than in anything this repository installs. Confidence: high. `apache/spark`
   carries a JVM and a Hadoop client, `apache/airflow` carries a very large Python surface, and neither
   is rebuilt here.
2. Nothing this repository installs — `psycopg2-binary`, `boto3` — is the source of a High or Critical.
   Confidence: moderate to high; both are current pins of well-maintained packages.
3. The inventory for `mlops-platform/mlflow` differs from its base's by exactly the two packages the
   Dockerfile adds plus their transitive dependencies, and the transitive count is under twenty.
   Confidence: low. boto3 pulls botocore, s3transfer, jmespath and urllib3, and psycopg2-binary is
   self-contained, so the honest guess is under ten, but pip resolution has surprised this repository
   before and the prediction is stated at the number I would defend rather than the one I expect.
4. At least one exception will be needed to make the scan pass at first. Confidence: moderate. If none
   is, prediction 1 was wrong about severity rather than about presence.

## Deciding evidence

Empty until `make sbom` and `make scan` run on a machine with a daemon. The shape assertions run
everywhere and are in the suite from this commit.

## What would change my mind

If a scan finding lands in `psycopg2-binary` or `boto3`, prediction 2 fails and the response is a
version bump rather than an exception, because those two are the only packages here whose version this
repository controls.

If the number of exceptions needed to get a clean scan is large — more than a handful — then the base
images are the problem rather than the findings, and the right answer is to reconsider
`apache/spark:3.5.1-python3` rather than to write a page of accepted CVEs. That would be a decision for
its own record, and it would supersede the choice of base made in record 005.

## Consequences

A version bump now produces a reviewable diff: the tag changes, the digest changes, and the inventory
changes by the packages that actually changed. Those three moving together is the review, and any one of
them moving alone is a question.

The cost is two more pulled tools and a directory that is generated rather than authored. The scan
cannot run in the contract tier, so a laptop still cannot tell whether the images are currently
vulnerable — only whether the exceptions are still in date.

## Implementation, 2026-08-30

Four things the decision above did not anticipate, recorded here rather than by editing it.

**One correction to the text above.** It says the SPDX document is generated into `sbom/`, "which is
git-ignored". The directory is not; the documents in it are, by a `sbom/.gitignore` that ignores
`*.spdx.json` and nothing else. That has to be the arrangement, because the inventories live in the same
directory and are the files being committed.

**The image list is read from the compose file, not from `docker compose config --images`.** This was the
obvious implementation and it is unsafe here for a reason already recorded in `docs/setup.md`: that command
reports the services of the profiles it is given, and it omitted `apache/airflow` from this repository's
image list once already. A cataloguer fed a short list writes an inventory that is short in exactly the
same way, and the resulting file reads as a clean bill of health rather than as an error. Since the whole
argument for committing an inventory is that a reader can trust it, a source that can silently come back
short defeats the record. So `supply.images` takes the `image` keys themselves, which cannot omit a
profiled service, needs no daemon, and returns five references including the one image built here.

The cost is a second reader of the compose file beside the one in `tests/test_image_supply.py`.
`tests/test_supply_images.py` compares the two as sets so neither can drift alone, which is the same
device record 018 used to keep the pulled-versus-built split honest.

**The code lives in a new `supply/` package rather than in `preflight/`.** `preflight` answers whether this
machine can start the stack. Nothing here can be answered by looking at a machine and nothing here runs
before a start, so sharing the package would have meant one of the two names stopped describing its
contents. `pyyaml` moves from the dev extra to a real dependency as a consequence: both entrypoints now
import it outside the test suite.

**The Makefile's recipes are executed by nothing, so they are parsed instead.** CI calls the tools directly
rather than through `make`, and the build machine is Windows and uses `make.ps1`. That leaves the canonical
file authored and never run, which for two hand-written shell loops with nested quoting is the kind of gap
that surfaces in front of the first person to try the documented command. `tests/test_makefile_recipes.py`
expands make's own variables and runs `sh -n` over every recipe: it starts no container, writes no file, and
proves only that a shell would accept the text — which is precisely the difference between a recipe that has
been read and one that has been run. It carries its own positive control, because a parser that accepts
everything passes every recipe including the ones it should reject.

**CI does not scan, and that is a deferral rather than an omission.** The threshold worth gating at needs the
first result rather than a guess made before it, and a nightly job that fails on a finding nobody can accept
yet — the ignore-rule half of the exceptions mechanism is owed at the first accepted finding — would be a
gate with no way through it. What CI covers today is the code around the scan: `supply.images` and
`supply.inventory` are in the contract tier, which needs no daemon.

None of the four predictions is scored. All four need a run on a machine with a daemon, and none has had one.

## Prediction scored, 2026-08-30

The first run on a machine with a daemon. `make sbom` worked; `make scan` produced nothing, for a
reason that has its own record.

**The SBOM half worked on the first attempt.** Six lines of output, five inventories, and the shape
assertions turned from one skipped empty parameter set into five passing checks — the count went from
`7 passed, 1 skipped` to `13 passed`, which is the mechanism doing exactly what the record said it
would. Package counts: `apache/spark` 618, `apache/airflow` 578, `minio/minio` 284,
`mlops-platform/mlflow` 177, `postgres:16.3-alpine` 51.

**The scan half returned no security information at all.** Both invocations — gated and report-only —
failed identically before reading a single document:

```
db could not be loaded: the vulnerability database was built 24 weeks ago (max allowed age is 5 days)
```

The pinned `grype:v0.79.0` speaks a database schema its publisher has retired, so the newest database
that version can fetch is half a year old and grype's own five-day staleness check refuses it. The
refusal is correct behaviour. Record 020 covers the diagnosis, the version bump, and the conclusion
that a scanner pin is not like an image pin.

**Prediction 1 — at least one High or Critical, in a base image rather than in anything installed
here. NOT SCORED.** No finding was returned at any severity. Nothing about this was tested.

**Prediction 2 — nothing this repository installs is the source of a High or Critical. NOT SCORED.**
Same reason.

**Prediction 3 — the mlflow inventory exceeds its base's by boto3, psycopg2-binary and their
transitive dependencies, under twenty. NOT SCORED, and it was not measurable.** This is the one worth
recording as a defect in the record rather than in the run. The prediction compares two inventories
and only one of them existed: `supply.images` read the compose file's `image` keys, and
`ghcr.io/mlflow/mlflow:v2.13.0` is a `FROM` in a Dockerfile rather than an `image` key, so the base
was never catalogued. 177 packages was a number with nothing to compare it against.

That is the same short-list defect this record's implementation note describes for
`docker compose config --images`, one level down, and I wrote that note in the same session without
noticing the second instance. `supply.images` now includes the `FROM` of everything the spine builds,
and record 020's prediction 4 restates this one so it can be scored on the next run.

**Prediction 4 — at least one exception will be needed to make the scan pass. NOT SCORED.** The scan
did not run. `security/exceptions.toml` is still empty and still honest for the original reason.

**What the run did settle, and it was not on the prediction list.** Both cataloguer pins were roughly
two years stale, because I chose those versions from memory rather than from a registry, and nothing
in the repository could have caught it: every assertion about these references checked that the pin
was *exact*, and exactness has nothing to do with currency. That gap is what record 020's expiry is
for.

## Prediction scored, 2026-08-30 (third run, the first with findings)

The scan ran. `grype db update` fetched schema v6.1.9, built 2026-08-30T06:27:52Z, `Status: valid`,
and all six documents were scanned in 97 seconds including the download.

**5,017 findings, 1,390 unique advisory identifiers.** Counted from the pasted output by column
offset; two further rows were split by terminal wrapping and are not in the totals.

| severity | findings | unique ids | a fixed version exists |
| --- | --- | --- | --- |
| Critical | 185 | 70 | 154 |
| High | 1,197 | 485 | 1,086 |
| Medium | 2,541 | 718 | 2,288 |
| Low | 552 | 201 | 512 |
| Negligible | 453 | 91 | 80 |
| Unknown | 89 | 10 | 1 |
| **total** | **5,017** | **1,390** | **4,121** |

| image | findings | Critical | High | of Critical+High, fixable |
| --- | --- | --- | --- | --- |
| `apache/spark:3.5.1-python3` | 1,750 | 5 | 93 | 95 of 98 |
| `apache/airflow:2.9.2-python3.11` | 1,566 | 88 | 481 | 499 of 569 |
| `mlops-platform/mlflow:2.13.0` | 603 | 27 | 212 | 208 of 239 |
| `ghcr.io/mlflow/mlflow:v2.13.0` | 603 | 27 | 212 | 208 of 239 |
| `minio/minio` | 260 | 27 | 77 | 98 of 104 |
| `postgres:16.3-alpine` | 235 | 11 | 122 | 132 of 133 |

**Prediction 1 — at least one High or Critical, and in a base image rather than in anything this
repository installs. CORRECT**, by a margin that makes "at least one" read as an understatement. The
severity is concentrated in OS packages: of the 1,382 Critical and High findings, 731 are `deb`, 229
`python`, 181 `go-module`, 39 `apk`. The stated reasoning also holds — `apache/spark` carries the JVM
and Hadoop surface and `apache/airflow` the large Python one, and neither is rebuilt here.

**Prediction 2 — nothing this repository installs is the source of a High or Critical. CORRECT**, and
the evidence is stronger than the prediction asked for. `mlops-platform/mlflow` and its base
`ghcr.io/mlflow/mlflow` return *identical* counts: 603 findings each, 27 Critical each, 212 High each.
The five packages this repository adds — `boto3`, `botocore`, `jmespath`, `psycopg2-binary`,
`s3transfer` — contribute exactly zero findings at any severity. Nothing about the vulnerability
profile of the one image built here is attributable to a decision made here.

One near-miss worth naming rather than leaving to be found: `urllib3==2.2.1` carries High findings and
sits in both the base and the built image. It is a dependency of `boto3`, so it looks like this
repository's problem and is not — record 020's step-6 diff established that `urllib3` was already in
the base, which is why `pip` left it alone. It could be pinned forward here, which would be a change
this repository *chooses* to own rather than one it already owns.

**Prediction 3 — the mlflow inventory exceeds its base's by the two packages installed plus their
transitive dependencies, under twenty. CORRECT** at five, scored in full under record 020.

**Prediction 4 — at least one exception will be needed to make the scan pass at first. CORRECT**, and
this is the prediction whose being right matters least and whose margin matters most. `--fail-on high`
meets 1,382 findings. Making that gate pass by exception would take on the order of a thousand
entries, each needing a forty-character reason and an expiry date.

## What would change my mind: triggered

This record wrote down the condition and it has been met:

> If the number of exceptions needed to get a clean scan is large — more than a handful — then the
> base images are the problem rather than the findings, and the right answer is to reconsider
> `apache/spark:3.5.1-python3` rather than to write a page of accepted CVEs.

1,382 is not a handful. The exceptions mechanism is not the answer here and will not be used to make
this gate pass. Roughly 90% of the Critical and High findings name a fixed version, and the images are
old — `apache/airflow:2.9.2-python3.11` and `postgres:16.3-alpine` are mid-2024 — so the fix is
overwhelmingly a version bump rather than an accepted risk. What threshold to gate at, and which bases
to move, is a decision for its own record; this one records only that the mechanism it built is the
wrong tool for the number it found, which is what the trigger was for.
