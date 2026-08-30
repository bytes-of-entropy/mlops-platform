# 021: The answer to five thousand findings is a version bump, not a page of exceptions

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `compose/`, `images/mlflow/`
- **Milestone:** M1
- **Extends:** record 005 (choice of base images), record 018 (digest pinning)

## Context

The first scan that produced findings returned **5,017 of them across six images: 185 Critical and
1,197 High, 1,390 unique advisory identifiers**. Record 019 built the exceptions mechanism for exactly
this moment and wrote down the condition under which the mechanism would be the wrong tool:

> If the number of exceptions needed to get a clean scan is large — more than a handful — then the base
> images are the problem rather than the findings, and the right answer is to reconsider
> `apache/spark:3.5.1-python3` rather than to write a page of accepted CVEs.

1,382 Critical and High findings is not a handful. Two further facts settle which way this goes.

**Roughly 90% of the serious findings name a fixed version.** 154 of 185 Critical and 1,086 of 1,197
High carry a `FIXED IN` column. These are not accepted risks awaiting judgement; they are updates
nobody has applied.

**The images were between one and two years old.** `apache/airflow:2.9.2-python3.11` was published in
June 2024, `postgres:16.3-alpine` in May 2024, `apache/spark:3.5.1-python3` in February 2024,
`minio/minio:RELEASE.2024-06-04`, and the MLflow base `v2.13.0` in mid-2024. The severity is
concentrated where age shows: of the 1,382 Critical and High, 731 are `deb` packages and 39 `apk` —
the operating system underneath, not the application on top.

So the finding count is a measurement of staleness rather than of risk accepted with open eyes, and the
instrument that produced it was itself a version bump away from working at all (record 020). This
record decides what to do with the number.

## Decision

**Every pulled reference moves to the newest release in its current major line, and crossing a major
line is a migration rather than a bump.** That rule is the whole of it, and it draws the line where the
work changes character: a newer patch of the same major is a security update whose blast radius is the
operating system inside the image, and a new major changes an API, a topology or an on-disk format,
which is a different kind of change with a different kind of risk and deserves its own record.

| reference | was | now | major line held at | why not the newest major |
| --- | --- | --- | --- | --- |
| `postgres` | `16.3-alpine` | `16.15-alpine` | 16 | 17 and 18 exist. A major upgrade will not start against a `PGDATA` initialised by 16; it needs `pg_upgrade` or a volume reset, and a volume reset destroys the MLflow history this spine exists to keep. Hard constraint, not caution. |
| `apache/airflow` | `2.9.2-python3.11` | `2.11.2-python3.11` | 2 | 3.3.1 is current. Airflow 3 replaces the webserver with an api-server, changes what `standalone` does, and changes DAG serialisation — it is a change to the compose topology and the smoke DAG, not to a base image. 2.11.2 is the last 2.x release. |
| `apache/spark` | `3.5.1-python3` | `3.5.9-python3` | 3.5 | 4.2.0 is current and the 3.5 line is still receiving updates. No Spark job exists here yet, so crossing to 4.x is cheaper now than it will ever be again — and it is a decision about what Repo 1's M2 Spark work targets, which is not this milestone's to make. |
| `minio/minio` | `RELEASE.2024-06-04` | `RELEASE.2025-09-07` | n/a | The newest published release. |
| `ghcr.io/mlflow/mlflow` | `v2.13.0` | `v2.22.4` | 2 | 3.15.2 is current. MLflow 3 changes tracking and registry semantics, and the smoke path logs a run through the REST API; 2.22.4 is the last 2.x release. |

Every digest was re-resolved and every reference keeps the `name:tag@sha256:…` shape record 018
requires. `mlops-platform/mlflow` moves from `2.13.0` to `2.22.4` because the built tag tracks its
base's version — that is why record 018 left it a bare tag rather than pinning it.

**The gate threshold is deliberately still unset, and that is the point of doing this first.** Choosing
`--fail-on` before the bump would have meant picking a number to fit 5,017 findings produced by images
nobody had updated. The bump is the change that makes a threshold meaningful, so the threshold is
chosen from the numbers the bump produces. `SCAN_FAIL_ON` defaults to `high` today and will fail; that
is a known state with a date on it, not a gate anyone is claiming to pass.

**The two packages this repository installs do not move.** `psycopg2-binary==2.9.9` and
`boto3==1.34.131` stay. The scan is unambiguous about them: `mlops-platform/mlflow` and its base
returned *identical* counts — 603 findings, 27 Critical, 212 High each — so the five packages this
repository adds contribute exactly zero findings at any severity. A bump with no security argument
behind it can only add risk.

**One finding is left deliberately unowned, and named so it is not mistaken for an oversight.**
`urllib3==2.2.1` carries High findings and is a `boto3` dependency, which makes it look like this
repository's problem. It is not: the step-6 inventory diff showed `urllib3` already present in the
base, which is why `pip` left it alone. Pinning it forward here would mean this repository taking
ownership of a transitive dependency's version against the base's own constraint solving. Whether the
new base resolves it is a question the next scan answers, and if it does not, owning it becomes a real
option rather than a speculative one.

## Alternative rejected

**Write the exceptions.** What record 019's mechanism was built for, and the reason that record wrote
down a trigger. On the order of a thousand entries, each needing a forty-character reason and an expiry
date, to make a gate pass while changing nothing about the images. It would also destroy the mechanism
it used: an exceptions file with a thousand entries is not reviewable, so the property that makes an
accepted finding meaningful — that somebody read it and argued for it — would be gone on the first use.

**Gate on Critical only, or on Critical-with-a-fix.** 185 and 154 respectively. Still two orders of
magnitude more than a reviewable exceptions file, so it does not avoid the bump; it only lowers the bar
until the bump looks optional. Record 019 already rejected a Critical-only threshold on the ground that
High findings in a base image are exactly the ones that turn out to matter, and nothing here changes
that.

**Ratchet on a committed baseline: fail if the count rises.** Genuinely attractive, and the standard
answer for inherited debt. Rejected as the *first* move because it accepts 5,017 findings as the
starting position and never asks for one of them back, and because the number is not inherited debt —
it is a year of updates nobody applied, which is a different thing with a cheaper fix. A ratchet
remains a good candidate for the threshold *after* the bump, when what remains really is the residue.

**Cross every major line now — Airflow 3, Spark 4, Postgres 18, MLflow 3.** The most thorough option
and the one that confuses two changes. Each of those is a migration with its own failure modes, and
three of the four would land on an integration tier that took weeks to get green; the Postgres one
would destroy a volume. Doing them under the heading "fix the CVEs" would mean that when the tier
broke, the cause could be the security update or the major migration, and the run would not say which.

## Prediction (recorded before the evidence)

1. The integration tier stays green on the first run after the bump — `226 passed, 0 skipped` with
   credentials and a runtime. Confidence: moderate. The two changes most able to break it are Airflow
   2.9→2.11 and MLflow 2.13→2.22, and the reasons to think they will not are specific: the smoke DAG
   already uses the TaskFlow API with `schedule=` rather than `schedule_interval`, and it talks to
   MLflow over `/api/2.0/mlflow` rather than importing the client, so neither the Airflow deprecations
   of 2.10 nor any MLflow Python API change reaches it.
2. Total findings fall by more than half, to under 2,500. Confidence: moderate. 90% of the serious
   findings name a fix and the OS layers are 12–21 months newer, but a newer base also carries more
   *packages*, and every package is a chance for a new advisory.
3. Critical falls furthest in proportion — under 40, from 185. Confidence: low to moderate. Critical
   findings in OS packages get backported fastest, so they should be the most responsive to age; this
   is the prediction I would defend least.
4. `apache/airflow` remains the worst image by absolute count. Confidence: high. It was 1,566 with 88
   Critical, it carries the largest Python surface in the spine, and 2.11.2 is itself five months old.
5. The five packages this repository installs still contribute zero findings, so
   `mlops-platform/mlflow` and its base still return identical counts. Confidence: high. It was true at
   `v2.13.0` and nothing about those two packages changed.
6. `urllib3` is no longer High in the new base — that is, the base ships a fixed version. Confidence:
   low. This is the one I most want to be wrong about in an interesting way, because if the base still
   ships a vulnerable `urllib3` then owning the pin here becomes the right call and the record above
   becomes a decision rather than an observation.

## Deciding evidence

A rebuild, a re-catalogue and a re-scan on a machine with a daemon, and the integration tier green.
Until then this record has changed five strings and nothing about the world.

## What would change my mind

If the tier breaks on Airflow 2.11 or MLflow 2.22, the within-major rule was wrong for those two and
the honest response is to say so and pin back, not to fight the migration under a security heading.

If findings do *not* fall substantially, then age was not the cause and the diagnosis in this record is
wrong. The next place to look would be whether the bulk of the count is in packages that no base
update reaches — a vendored JVM, a Go binary with no module metadata — in which case the answer is
reconsidering the base *image* rather than its version, which is record 005's territory.

## Consequences

The spine is on current-within-major everywhere for the first time, and the pins now have a reason to
move on a schedule rather than only when something breaks. That is a maintenance obligation this
repository did not have yesterday: five references that are correct today and will be a year old in a
year. The supply-tool expiry from record 020 covers the two cataloguers and not these; whether the same
device should cover the spine is a question worth asking once the threshold exists, because an expiry
on five images with no gate behind it would be a reminder rather than a check.

**A gap this record exposes rather than fixes.** Record 019's argument for committing an inventory is
that a version bump produces a readable diff — the tag changes, the digest changes, and the inventory
changes by the packages that actually changed. This is the first version bump since that mechanism
landed, and **no inventory has ever been committed**: they are generated on the machine with a daemon
and have never travelled back, so the property the format exists for has not once been exercised. The
diff that would have made this record's case in five lines does not exist. Getting the post-bump
inventories committed is what turns that mechanism from a claim into a working loop, and it is owed
before the next bump rather than after it.
