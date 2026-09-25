# 027: The baselines catch up to the database, and no image moves this turn

- **Date:** 2026-09-25
- **Status:** accepted
- **Component:** `sbom/`
- **Milestone:** M0, maintenance
- **Extends:** record 019 (the committed artifact is a package inventory), record 020 (a scanner pin
  carries an expiry because its data retires before the tool does), record 021 (the answer to a page
  of findings is a version bump, not a page of exceptions), record 022 (the gate is on advisory
  identity because severity cannot move)

## Context

The baselines in `sbom/` are 36 advisories behind the database the scanner now carries, and the gap
is fixed rather than growing. Two consecutive build-machine runs on 2026-09-25 each scanned, wrote
baselines from what they measured, and diffed them against the committed ones. Both produced the same
diff to the line: 45 insertions and 3 deletions across the same five files. `chrislusf/seaweedfs` is
absent from it because its baseline was taken during the first of those runs, against the same data.

An identical diff twice is not drift in progress. It is one database move, already complete, sitting
between what is committed and what any scan today produces, and it costs two things while it sits
there. `make scan` on a machine with today's data and these baselines fails on all 36, so the gate
passes on the build machine only because the run rewrites baselines before it gates. And the step
whose whole job is to notice a change reports the same change every time, which is the state in which
a signal stops being read.

What the 36 are, per image, counting each advisory once where it appears in more than one:

| image | added | of which Critical |
| --- | --- | --- |
| `apache/airflow:2.11.2-python3.11` | 26 | `curl` twice, `apache-airflow`, `litellm`, `anyio` |
| `ghcr.io/mlflow/mlflow:v2.22.4` | 6 | `gitpython`, `anyio` |
| `mlops-platform/mlflow:2.22.4` | 6, the same 6 | the same 2 |
| `postgres:16.15-alpine` | 5 | none |
| `apache/spark:3.5.9-python3` | 2 | `netty-handler` |

Seven distinct Criticals and 29 Highs, and for each Critical whether a fix exists to take:

| advisory | package | installed | fixed in |
| --- | --- | --- | --- |
| CVE-2026-18924 | `curl` | 7.88.1-10+deb12u14 | won't fix |
| CVE-2026-19931 | `curl` | 7.88.1-10+deb12u14 | won't fix |
| GHSA-2943-9672-r45w | `apache-airflow` | 2.11.2 | 3.3.0 |
| GHSA-6wvf-77m9-58rm | `litellm` | 1.82.0 | 1.83.7 |
| GHSA-82r6-8w77-94w6 | `anyio` | 4.12.1, 4.12.0 | 4.14.2 |
| GHSA-284h-m62q-gf8w | `gitpython` | 3.1.45 | 3.1.59 |
| GHSA-c4c3-7fpv-j4q5 | `netty-handler` | 4.1.96.Final | 4.1.137.Final |

Every one of them lives in an image this spine pulls rather than builds. The two mlflow rows are the
same six advisories twice over: the layer this repository adds to that image contributes none of its
own, which is what record 019 argued the second inventory would show, and this is the first turn that
has measured it against a database that moved.

Three of the five files also lose an advisory, CVE-2026-3298, which the database no longer reports
against those images. Record 022 holds that an advisory appearing must fail the gate and an advisory
disappearing must not, and until now that asymmetry has only been exercised against hand-built
reports in the contract tier.

## Decision

**The five baselines are refreshed to what the 2026-09-25 scans measured, and no image moves this
turn.**

The bytes come from the build machine, which is the only place a scan runs, and they arrive as the
diff that run printed rather than as files copied across by hand. Applying that diff with `git apply`
is what makes the provenance checkable: the patch carries a pre-image hash for every file it touches,
so it either reproduces exactly the bytes the scan wrote or it refuses outright. A baseline that
quietly absorbed an edit in transit would be worth nothing, and a hash is cheaper than trusting that
it did not.

**No entry is added to `security/exceptions.toml`.** A baseline entry claims only that an advisory
was present when the baseline was taken. An exception claims that someone read it, accepted the risk,
and set a date to look again. Thirty-six advisories nobody has assessed are the first thing, not the
second, and record 022 keeps them in separate files for precisely this reason.

**The image bumps stay unmade, and are named here instead.** Two of the Criticals are marked as not
being fixed in Debian 12, and resolve only when that base moves to a newer distribution, which is not
a bump anyone can take. Three more sit inside pinned images this repository does not install into:
`litellm` and `anyio` ship in `apache/airflow`, `gitpython` in the mlflow image, `netty-handler` in
`apache/spark`, and none of them can move independently of the image tag. The one that is this
repository's to take, `apache-airflow` 2.11.2 to 3.3.0, crosses a major version in the component
whose DAG contract, provider set, and admin-user creation the spine depends on. Record 021 is right
that a bump is the answer to a page of findings; it follows that a major bump is a milestone's work
with its own run and its own rollback, and not a line inside a maintenance commit.

## Alternatives rejected

**Take the bumps that have a fix.** Four of the five are not this repository's to take, and the fifth
changes Airflow's major version. A commit that refreshed baselines and bumped Airflow would be two
changes wearing one message, and the second is the kind that fails loudly a week later in a place the
first one gets blamed for.

**Leave the baselines stale and mark the step as expected to fail.** Cheapest today, worst in a
month. It keeps `make scan` failing anywhere the committed baselines are the thing being trusted, and
it teaches a reader to skip a non-zero step, which is the habit record 022's gate exists to prevent.

**Write the 36 into `security/exceptions.toml` with an expiry.** That would put an assessment on the
record that nobody performed. The file means something today; filling it to quiet a gate would empty
it.

## Prediction (recorded before the evidence)

1. The next build-machine run reports that `sbom/` is unchanged at both comparison steps, and both
   exit 0.
2. `make scan` passes on that machine against the committed baselines, before anything rewrites them.
3. If either comparison comes back non-empty, the database moved again after 2026-09-25, and the
   additions will be ones neither 2026-09-25 run saw. A repeat of any of these 36 would instead mean
   the patch did not carry what the scan measured, and the pre-image hashes make that the less likely
   of the two.

## Deciding evidence

The two runs at 00:16 and 01:20 on 2026-09-25 printed the same diff, byte for byte, across the same
five files: 27, 2, 7, 7, and 5 added lines, for 45 insertions and 3 deletions in total. That is what
makes this a fixed gap rather than a moving one, and a fixed gap is refreshable. A moving one would
want the scanner pin examined first, which is record 020's question rather than this record's.

## What would change my mind

A Critical arriving in a package this repository itself installs, rather than one inherited from a
pinned image. That is a bump this repository can take alone, and none of the reasoning above for
recording rather than acting would apply to it.

## Consequences

- Thirty-six advisories, seven of them Critical, are now recorded as present, and the gate cannot be
  what surfaces them: a baselined advisory is exactly what the gate stays quiet about. This record is
  where they are visible, and record 020's scanner expiry is the mechanism that forces the next look.
- The Airflow major becomes an owed decision with a name and a reason, rather than an item that fell
  off the end of a diff.
- CVE-2026-82049 reports its fix as Python `3.14.0b1` against interpreters at 3.11.15 and 3.10.18. A
  beta of an unreleased version is not a fix available to a pinned image, and it is a standing
  reminder that a fixed-in column is a claim about a package index rather than about this spine.
- The removal of CVE-2026-3298 exercises record 022's asymmetry against real data for the first time.
  The refresh drops it from three baselines and nothing fails, which is the designed direction.

## Prediction scored, 2026-09-25 (the 11:45 run): 1 and 2 confirmed, 3 not triggered

**Prediction 1 holds.** Both comparison steps reported `sbom/ is unchanged.` and exited 0, the first
run in which either did. Step 11 compares before anything is written and step 13 after the accept, so
the pair says two separate things: the committed inventories still describe these six images, and a
scan taken today produces the baselines the repository carries rather than 36 more.

**Prediction 2 holds, by way of step 13 rather than directly.** The run writes baselines before it
gates, so the gate at step 14 is nominally against files that step 12 has just rewritten, and on its
own it proves nothing about the committed ones. Step 13 closes that gap: it found the rewritten files
byte-identical to what is committed, so `all baselined` for all six images is a statement about the
repository and not only about the scratch copy. That the two steps are needed together to answer one
question is worth keeping in mind the next time either is read alone.

**Prediction 3 was not triggered.** Neither comparison came back non-empty, so the database has not
moved since 2026-09-25, and the question of whether an addition would be a new advisory or one of
these 36 stays open until it does.

The run had one failing step and it was not a supply step: the Ingress probe answered 503 once and
asserted on a single unretried request, against a cluster seconds old. The cluster tier passed the
same assertion seven ways minutes later on its own cluster, so the probe was measuring how fast the
controller reloaded. That is a defect in the runner and has nothing to do with anything this record
decided, which is the reason it is one line here rather than a section.
