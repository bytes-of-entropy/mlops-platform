# 023: Only the image this repository builds is published, and not before the repository is

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `images/mlflow/`, `Makefile`, `make.ps1`
- **Milestone:** M1

## Context

M1's last unmet item is "images in GHCR at pinned digests". Everything else it asked for is done and
measured: a non-root image audited statically (017), every pulled reference digest-pinned (018), an
SBOM per image with a committed inventory (019), a scanner that works and expires (020), bases current
within their major lines (021), and a gate on advisory identity that has passed (022).

Writing the push turned up two things the checklist did not anticipate.

**The plural is wrong.** The spine names six images and five of them belong to other people. Pushing
copies of `apache/spark`, `apache/airflow`, `postgres`, `minio/minio` and `ghcr.io/mlflow/mlflow` under
this account would republish artifacts this project did not make and cannot vouch for, under a name
that implies otherwise. It would also make the spine depend on a mirror of a mirror, which is the
failure record 012 is about, one indirection worse. Exactly one image here is this repository's to
publish.

**The ordering is wrong.** No git remote exists in any of the three repositories and nothing has been
pushed anywhere. `REPO_ROADMAPS.md` publishes R3 after **M2**, not after M1, so the milestone that asks
for published images comes before the milestone that publishes the repository. Pushing now would create
a package under an account with no repository to attach to — `org.opencontainers.image.source` would
name a URL that 404s, the package would land private and unlinked, and the visibility and permissions
that should follow the repository would have to be set by hand and then redone once the repository
exists.

## Decision

**One image is published: `mlops-platform/mlflow`, as `ghcr.io/<owner>/mlops-platform/mlflow`.** The
path is nested under the repository name so a reader of the reference can tell which repository
produced it. `GHCR_OWNER` is a variable because it is the one value here that belongs to a person
rather than to the project.

A test asserts the push target mentions no upstream image and does name the built one, because
"republish everything" is the natural reading of the checklist and would be wrong.

**`make push` depends on `build` rather than hoping for it.** Pushing a tag no build produced is the
one way this target can publish something other than what it claims: a stale tag from an earlier
Dockerfile would push happily and be undetectable afterwards, since a digest is only ever compared
against itself.

**The push handles no credential, and a test enforces that.** A login belongs in the operator's
session. `docker login` inside a target needs a token from somewhere, and the somewhere is a file this
repository could read — which is the one rule this project treats as absolute. `docker push` failing on
an anonymous session is a clear enough message.

**The image carries `org.opencontainers.image.source`.** That label is what a registry reads to attach
a published package to the repository it came from. Without it the package is an artifact under an
account with nothing tying it to its source. Static rather than a build argument, and the labels
deliberately stop short of `revision`: a commit label would be more precise, since this tag is MLflow's
version and two different commits both produce `2.22.4`, but getting a commit into it means plumbing a
build argument through compose and making `make build` read git state, which an extracted tarball does
not have. The digest of each pushed image is recorded in this file against its commit instead, which
ties the two together without making the build depend on the repository.

**The push runs when the repository is published, not before.** The mechanism is committed and tested
now; the act waits for R3's publish gate at M2. So M1 closes with this item **sequenced rather than
unmet**, which is a different claim and the honest one: nothing is missing except an ordering that was
wrong in the checklist.

## Alternative rejected

**Push now anyway, to satisfy the checklist as written.** The letter of it, and it produces a private
unlinked package that has to be pushed again and relinked once the repository exists. It would let M1
report complete while leaving something to redo, which is the kind of green this repository has already
corrected once.

**Mirror the five upstream images too, so the spine pulls only from one registry.** A real pattern with
real benefits in an environment that needs an air gap or a pull-through cache. Rejected because it
makes this project the publisher of artifacts it did not build, and because record 018's digest pins
already give the property that matters — the same bytes everywhere — without asking anyone to trust a
copy. `docs/OFFLINE_FIRST.md` is where that argument would belong if the need ever appears.

**Switch compose to pull the built image from GHCR instead of building it.** Tempting once the image is
published: a reviewer would need no build at all. Rejected for now because it inverts records 012 and
018 — the built tag is deliberately local, and a spine that pulls its own image from a registry depends
on that registry being up and on the pusher's credentials having worked. It also removes the one place
this repository demonstrates it can build an image. Worth revisiting after publishing, as its own
record, with the reviewer's experience as the argument rather than tidiness.

**A `revision` label from a build argument.** Discussed above. The cost is `make build` reading git
state; the benefit is duplicated by recording digests here.

## Prediction (recorded before the evidence)

1. `make push` fails on a clean session with an authentication error naming `ghcr.io`, rather than with
   anything about tags or digests. Confidence: high. This is worth predicting because it is the failure
   an operator will see first and it should be self-explanatory.
2. The push, when it runs, needs a token with `write:packages` and nothing more. Confidence: moderate.
   `read:packages` and `repo` are commonly cargo-culted into these tokens and I expect neither to be
   required for pushing to a package under one's own account.
3. The package lands **private** and needs one deliberate action to become public. Confidence:
   moderate to high. GHCR defaults a new package to private, and inheriting the repository's visibility
   depends on the source label linking it — which cannot happen before the repository exists, so on a
   pre-publish push it will certainly be private.
4. The digest `make push` prints for `ghcr.io/<owner>/mlops-platform/mlflow:2.22.4` differs from the
   local `docker images` digest for `mlops-platform/mlflow:2.22.4`. Confidence: moderate. A local build
   has no registry digest until it is pushed, which is precisely record 018's argument for leaving the
   built tag unpinned, and I expect the first to exist only after the push and the second not to exist
   at all.

## Deciding evidence

Empty by design. The mechanism is tested to the extent it can be without a credential — parity between
entrypoints, that it pushes only the built image, that it depends on `build`, that it handles no token,
and that the image declares its source. What is untested is every part that needs a registry, and that
stays untested until the repository publishes.

**Digests of published images, recorded as they are pushed:**

| commit | tag | digest |
| --- | --- | --- |
| _(none yet)_ | | |

## What would change my mind

If GHCR turns out to require the repository to exist before a package can be pushed at all, then the
sequencing above is not a choice but a constraint, and this record should say so plainly rather than
taking credit for a decision the registry made.

If prediction 2 is wrong and a broader token is genuinely required, that is worth knowing before anyone
creates one: a token with `repo` scope on an account holding three repositories is a much larger thing
to keep safe than one that can only write packages.

## Consequences

M1 closes with every item either done and measured or sequenced with a reason. The push is one command
whenever the repository goes public, and the digest table above is where its result gets recorded.

The repository now has a target nobody has run. That is the same position `make up` was in before the
first build machine existed, and the same answer applies: the tests assert what can be asserted without
the thing being present, and the record says which parts are claims rather than measurements.

## Correction, 2026-08-30

**The argument above against mirroring the five upstream images is wrong in its main claim, and this
record should not have carried it.** Two sentences were doing work they cannot support: that copying
those images "makes this project the publisher of artifacts it did not build", and that digest pins
give the same property "without asking anyone to trust a copy".

`apache/spark`, `apache/airflow` and `ghcr.io/mlflow/mlflow` are Apache-2.0; `postgres` carries the
PostgreSQL licence. Redistribution is explicitly permitted, and mirroring public images is ordinary
practice rather than a liberty — pull-through caches, Harbor, Artifactory and ECR all exist to do it. A
mirror at `ghcr.io/<owner>/…` claims authorship no more than a Debian mirror does. The framing was
about propriety, and propriety was never the issue.

**What survives is narrower and technical.** `docker pull` then `docker tag` then `docker push`
re-compresses layers and produces a *different digest*. A mirror built that way silently breaks record
018's invariant: the digest pinned in compose is not the digest the mirror serves, so the property that
record exists to guarantee — the same bytes everywhere — would be quietly lost by the act meant to
protect it. Preserving a digest means copying the manifest, with `crane copy` or `skopeo copy`, not
re-pushing an image. That is an argument about *how* to mirror, and the original text did not make it.

**And the case for mirroring was under-weighted.** Record 012 exists because an upstream publisher
moved its whole catalogue and deleted the originals. Deletion insurance is precisely what a mirror
buys, and dismissing it in one sentence ignored the failure this repository already has scar tissue
from. Registry rate limits are a second real reason. Neither is hypothetical.

**One image would need its own licence analysis rather than a blanket answer.** MinIO's server is
AGPL-3.0. Redistribution is permitted, but the AGPL attaches source-provision obligations on
distribution that Apache-2.0 does not, so "it is open source" is not sufficient reasoning for that one.

**The decision does not change, and its grounds do.** Only `mlops-platform/mlflow` is pushed, because
that is the image this repository builds and the one M1 asked about. Mirroring the other five is a
legitimate and possibly valuable *separate* capability, whose cost is a digest-preserving copy tool,
a per-image licence pass, and a decision about whether a reviewer should pull the spine from this
account or from upstream. It belongs in its own record, argued on availability, with
`docs/OFFLINE_FIRST.md` as the place the requirement would come from — not dismissed here on grounds
that do not hold.
