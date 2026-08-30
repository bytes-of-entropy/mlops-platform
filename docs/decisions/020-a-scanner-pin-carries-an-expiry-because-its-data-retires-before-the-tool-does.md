# 020: A scanner pin carries an expiry, because its data retires before the tool does

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `Makefile`, `make.ps1`, `sbom/`
- **Milestone:** M1

## Context

Record 019 landed the SBOM and scan mechanism with two pulled tools pinned by tag, `anchore/syft:v1.9.0`
and `anchore/grype:v0.79.0`, and recorded their digests as owed. The first run on a machine with a daemon
produced this:

```
scanning apache_airflow_2.9.2-python3.11.spdx.json
db could not be loaded: the vulnerability database was built 24 weeks ago (max allowed age is 5 days)
```

Both runs failed the same way, the gated one and the report-only one. **The scan produced no security
information at all.** Not one finding, at any severity, for any of the five images. Record 019's
predictions 1, 2 and 4 are all about findings, so none of them can be scored, and the exceptions file is
still empty for the same reason it was before: nothing has been scanned.

The cause is not the tool. `anchore/grype:v0.79.0` pulled cleanly and ran; syft, pinned equally old,
catalogued all five images without complaint. The cause is that grype is only as useful as a vulnerability
database, its publisher moved that database to a new schema, and the endpoint an old grype speaks to stopped
being updated. So the newest database that version *can* load is 24 weeks old, and grype's own staleness
check — five days — refuses it. The refusal is correct. A scanner silently reporting against a half-year-old
feed is the worse outcome by a wide margin.

Two facts make this worth a record rather than a version bump.

**Both pins were roughly two years stale, and they were stale because I chose the versions from memory
rather than from a registry.** `syft:v1.9.0` and `grype:v0.79.0` were current in mid-2024. The current
releases when this was written are `syft:v1.51.1` and `grype:v0.118.0`, both published 2026-08-27. Nothing
in the repository would have caught that: every assertion about these two references checked that the pin
was *exact*, which it was, and exactness is orthogonal to currency.

**A scanner pin is not like an image pin, and this repository had been treating them alike.** Record 018's
argument for digest pinning is that an image should be identical everywhere. That argument works because an
old image is merely old: `postgres:16.3-alpine` pinned to bytes from 2024 still starts a database in 2026.
A scanner pinned to bytes from 2024 does not still scan, because the artefact that makes it useful is not in
those bytes. Freshness and reproducibility are in direct conflict for this one class of tool, and no pin
resolves that conflict — it can only decide which side fails loudly.

## Decision

**Both cataloguers move to current versions and are pinned by tag and digest.** `anchore/syft:v1.51.1` at
`sha256:95fe0835…` and `anchore/grype:v0.118.0` at `sha256:8a93fc48…`, which pays the debt record 019
recorded as owed. A test asserts the `name:tag@sha256:<64 hex>` shape for both, separate from the compose
assertion in `tests/test_image_supply.py`, which reads `image` keys and would never see a reference living
in a Makefile.

**The pins carry an expiry, and a test fails when it passes.** One line, the same token in both
entrypoints:

```
# SUPPLY_TOOLS_EXPIRE: 2027-02-28
```

Six months, chosen against the observed failure rather than by feel: the pin that broke was about two years
old, so a six-month cadence has substantial margin, and a schema retirement is roughly an annual event
rather than a monthly one. Past the date, `tests/test_makefile_mirror.py` fails on any machine with no
daemon and no network. This is the same device record 019 applies to accepted findings and the repository
already applies to TODOs, for the same stated reason: a warning in a log is an expiry that never arrives.

Renewing means the version, the digest and the date, edited together. A date moved alone is the thing the
check exists to prevent.

**The scan reports the database before it reports a finding.** `grype db status` runs first, so the build
date and schema version sit above the findings. A scan result is a function of three things — the scanner,
the database, the SBOM — and only the third was visible in the output. A pasted result with no database date
cannot be interpreted six months later, and the failure this record is about is precisely a database date
nobody was looking at.

**The database is cached in a named volume.** `--rm` discards the container filesystem, so an uncached scan
downloads the whole database once per document: six documents, six downloads of a few hundred megabytes.
`GRYPE_DB_CACHE_DIR` is set explicitly rather than left to the image's default, so a change of base image
cannot move it silently.

**The base of the built image joins the cataloguer's list.** Unrelated to the scanner failure and found
while reading the same output: 177 packages for `mlops-platform/mlflow` is a number that cannot be checked
against anything, because `ghcr.io/mlflow/mlflow:v2.13.0` was not in the list. That is the same short-list
defect record 019's implementation note describes for `config --images`, one level down, and it is what made
prediction 3 unscorable. The base is not needed for the *scan* — the built image contains it, so scanning
one covers both — but the diff is the entire argument for committing an inventory.

## Alternative rejected

**Relax grype's staleness check — `GRYPE_DB_VALIDATE_AGE=false` or a longer
`GRYPE_DB_MAX_ALLOWED_BUILT_AGE`.** This makes the failure go away and is the worst option on the list. The
scan would then run, print findings, exit zero, and be a report against a half-year-old feed with nothing in
the output saying so. Every downstream claim — the exceptions file, the CI gate, the milestone — would rest
on it. The refusal is the tool working correctly; suppressing it converts a loud failure into a quiet false
assurance, which is the failure mode this repository has already published once and corrected.

**Track a moving tag — `anchore/grype:latest`.** Always current, never stale, and it discards the property
that a committed inventory is attributable. `syft:latest` would mean the inventory diff after a rebuild
answers "what changed in this image, or in the cataloguer, and there is no way to tell". It also fails the
existing assertion against moving tags, which exists for that reason. The expiry keeps currency a decision
someone makes and records, rather than one that happens silently between two runs.

**Dependabot or Renovate.** The right answer in general and it does not reach here: these two references
live in a `Makefile` and a `.ps1`, which neither tool parses. Moving them into a Dockerfile or a compose
file to make them machine-updatable would mean inventing a container whose only purpose is to be a place
where a bot can see a version string. The expiry is the enforceable mechanism actually available, and
`CLAUDE.md`'s preference for deterministic enforcement is satisfied by a test rather than by prose.

**Pin only syft and let grype float.** Tempting, since the two really do have different lifetimes: syft
carries no external state, so an old syft is merely old. Rejected because it puts the *asymmetry* in the
pins rather than in the record, and the next reader would see one pinned tool and one floating one with
nothing saying why. The asymmetry is real and belongs here, in prose, where it can be read.

## Prediction (recorded before the evidence)

1. `grype:v0.118.0` loads a database and the scan completes on all six documents. Confidence: high. The
   version is three days old at the time of writing, so it speaks the current schema by construction.
2. The scan returns at least one High or Critical, and record 019's prediction 1 scores correct. Confidence:
   high, and unchanged — the earlier run tested nothing about it.
3. `syft:v1.51.1` finds **more** packages than v1.9.0 did in at least four of the five images, because two
   years of cataloguer development is mostly new ecosystem coverage and better detection. Confidence:
   moderate to high. The counts to beat are airflow 578, spark 618, minio 284, mlflow 177, postgres 51.
4. The `mlops-platform/mlflow` inventory exceeds `ghcr.io/mlflow/mlflow:v2.13.0`'s by fewer than ten lines,
   which is record 019's prediction 3 restated now that it is measurable. Confidence: moderate. boto3 pulls
   botocore, s3transfer, jmespath and urllib3; psycopg2-binary is self-contained. Under ten is the
   expectation and under twenty is the number I would defend.
5. The database cache turns five downloads into one and the wall-clock of `make scan` drops by more than
   half. Confidence: high, but worth stating because it is the one change here justified by speed rather
   than by correctness, and CLAUDE.md requires a measurement for those. If the run does not show it, the
   cache mount is wrong and should come out.

## Deciding evidence

Empty until `make sbom` and `make scan` run again on a machine with a daemon. What is settled already: the
old pin does not work, which is a measurement rather than a prediction, and the tests for pin shape, expiry
and cache configuration run everywhere from this commit.

## What would change my mind

If `grype:v0.118.0` also refuses a database, the problem is not the pin's age and the diagnosis in this
record is wrong. The next place to look would be the container's cache directory and whether
`GRYPE_DB_CACHE_DIR` is being honoured at all.

If the expiry test turns out to fire before anyone has cause to bump — that is, if six months passes and the
pinned versions still work — then the date is too aggressive and the honest response is to lengthen it in a
new record, with the observation that nothing broke as the evidence. Lengthening it quietly to stop a red
suite would be the failure this whole record is about.

## Consequences

This repository now has one pin that expires and several that do not, and the difference is a claim about
the tool rather than about the schedule: a tool carrying state that must be fresh cannot be pinned the way
a tool that does not is. That generalises past this repository, which is most of why it is written down.

The cost is a test that will go red on 2027-03-01 if nobody touches it. On a published portfolio repository
that is a visible failure with no maintainer on hand. That is accepted, and on reflection it is not
obviously a cost: a reviewer reading a red build that says *the security tooling in this repository is six
months stale and here is the line that says so* learns more about the repository than a green one does.

## Prediction scored, 2026-08-30 (second run)

The bump worked and the scan still returned nothing, this time because of a defect in this
repository rather than in the pin.

```
Path:      /db/6/vulnerability.db
Schema:
Built:     0001-01-01T00:00:00Z
Status:    invalid
[0000] ERROR database does not exist
```

`/db/6/` is the point: `grype:v0.118.0` asked for schema 6, the current one, so the diagnosis in this
record was right about the retirement. What was wrong was the precondition added in the same commit.
**`grype db status` reports on a database; it does not fetch one.** On a fresh cache volume there was
nothing to report on, so the check written to *observe* the database was the thing preventing it from
existing, and the scan was never reached. Without that check, the scan's own auto-update would have
fetched the database and probably succeeded. `db update` now runs first — it is a no-op when the cache
is current — and a mirror assertion refuses a scan target that reports without fetching.

**Prediction 1 — v0.118.0 loads a database and the scan completes on all six documents. REFUTED**,
and by my own hand rather than by the pin. Recorded as refuted anyway: the prediction was about the
outcome, the outcome did not happen, and a prediction that only counts when the cause is external is
not a prediction.

**Prediction 2 — at least one High or Critical. NOT SCORED.** Still no finding, at any severity, for
any image. Two runs in, what these six images contain remains unknown, which is worth stating plainly
rather than letting the surrounding progress imply otherwise.

**Prediction 3 — syft v1.51.1 finds more packages than v1.9.0 in at least four of the five images.
REFUTED.** More in three of five:

| image | v1.9.0 | v1.51.1 | delta |
| --- | --- | --- | --- |
| `apache/airflow` | 578 | 587 | +9 |
| `apache/spark` | 618 | 618 | 0 |
| `minio/minio` | 284 | 285 | +1 |
| `mlops-platform/mlflow` | 177 | 185 | +8 |
| `postgres:16.3-alpine` | 51 | 51 | 0 |

The pattern is more interesting than the miss. Every gain is in a Python-heavy image and the two
unchanged ones are the images whose contents are almost entirely OS packages. Two years of cataloguer
development went into language ecosystems; `dpkg` and `apk` parsing was already complete and had
nothing to gain. "At least four of five" was a number picked to sound defensible rather than derived
from that distinction, and the distinction was available before the run.

**Prediction 4 — the mlflow inventory exceeds its base's by fewer than ten lines. CORRECT.** Six
added, one removed, net five:

```
boto3==1.34.131
botocore==1.34.162
jmespath==1.1.0
mlops-platform/mlflow==2.13.0     <- not a package; see below
psycopg2-binary==2.9.9
s3transfer==0.10.4
```

Five real packages. This also settles record 019's prediction 3 at the same number. Worth noting where
the reasoning was loose: that prediction listed urllib3 among boto3's transitive dependencies, which
is true of boto3 and false of the delta — urllib3 was already in the base. The estimate was right and
one of its four named reasons was not.

**Prediction 5 — the database cache turns five downloads into one and halves the wall clock. NOT
SCORED.** No database was ever fetched, so nothing was cached and there is no timing to compare. The
cache mount is still unproven and stays flagged as the one change here justified by speed.

## What the run found that no prediction covered

**syft catalogues the image as a package inside its own inventory.** `mlops-platform/mlflow==2.13.0`
was a line in `mlops-platform/mlflow`'s inventory and `ghcr.io/mlflow/mlflow==v2.13.0` a line in its
base's. Diffing one against the other therefore reported a spurious added line and a spurious removed
line on top of the five real ones — noise in precisely the diff the inventory format exists to make
readable, and an image tag bump would produce that pair every time while changing no package at all.

`supply.inventory` now drops the entry the SPDX document declares itself to be *about*, read from the
document's `DESCRIBES` relationship or `documentDescribes` rather than by matching the image's name. A
name match would have worked today and silently dropped a real package the day one is named after an
image. The count of dropped entries is printed per image rather than asserted, because that number is
the evidence the structural read found what it expected: one per image confirms it, zero says the
assumption is wrong and nothing was removed. All six inventories will be one line shorter, which is a
one-time diff with a reason.

**`docker run name:tag@sha256:X` creates no local tag.** The pull is recorded under the digest, so
`docker image inspect name:tag` reports `No such image` for a reference that ran seconds earlier —
which is what the digest-confirmation step actually discovered about itself. It was also asking the
wrong question: the pull lines already prove each pinned digest is fetchable, and what no local
command can show is whether the *tag* half of the pin still points there, since docker ignores the tag
once a digest is present. That step now asks a registry, and reads the pins out of the Makefile so it
cannot drift from them.

**The suite matched its derived row exactly for the second consecutive time**: `220 passed, 0 skipped`
after `make sbom`, derived on a machine with no container runtime. The `pytest` rows in
`docs/setup.md` are worth more than they were two runs ago.

## Prediction scored, 2026-08-30 (third run)

**Prediction 1 — v0.118.0 loads a database and the scan completes on all six documents.** Scored
REFUTED above, for the run where my own precondition prevented it. With `db update` in front of
`db status` the same pin did exactly what the prediction said: `Schema: v6.1.9`, `Built:
2026-08-30T06:27:52Z`, `Status: valid`, six documents scanned. The refuted score stands, because the
prediction was about a run and that run failed; the claim underneath it was sound.

**Prediction 2 — at least one High or Critical. CORRECT.** 185 Critical and 1,197 High. Scored in full
under record 019.

**Prediction 3 — syft finds more packages in at least four of five images.** Scored REFUTED above, at
three of five. Unchanged.

**Prediction 4 — the mlflow inventory exceeds its base's by fewer than ten lines. CORRECT** at five,
and now cleanly: with the document-subject entry dropped, the diff reads `added: 5   removed: 0`
rather than the earlier `added: 6   removed: 1`.

**Prediction 5 — the cache turns five downloads into one, and the wall clock drops by more than half.
HALF SCORED, and the half that is measured is not the half that was claimed.** One fetch happened
across six documents, and the next invocation fetched nothing at all — the cache works, and "five
downloads become one" is confirmed. The wall-clock claim is not: there is no uncached baseline to
compare against, because the uncached configuration never completed a scan. 97 seconds for six
documents including the download is the only number, and it is not evidence for a halving. Recorded as
unmeasured rather than quietly counted as correct, since CLAUDE.md requires before and after numbers
for a change justified by speed and this has only an after.

## Two mechanisms confirmed working

**The document-subject drop fired on all six images**, one entry each, exactly as the structural read
predicted. Every inventory is one line shorter and step 6's diff is now five lines with no spurious
pair. Reporting the count rather than asserting it was the right call: it turned an assumption into an
observation at no cost.

**Both cataloguer tags still point at their pinned digests.** `AGREE` twice, which retroactively
validates resolving those digests from Docker Hub's API rather than from the build machine's image
store — the method used for `apache/airflow` in record 018 and flagged then as worth watching. It has
now been checked twice and been right twice.
