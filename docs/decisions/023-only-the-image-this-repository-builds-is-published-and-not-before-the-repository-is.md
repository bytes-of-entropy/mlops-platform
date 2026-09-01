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
| `4f5f850` | `2.22.4` | `sha256:7d41f0696592d57e118e75cc21d55c4949c32f2a5ff64f1155bd672cd7c2bdde` |

That digest is `ghcr.io/bytes-of-entropy/mlops-platform/mlflow@sha256:7d41f069...`, and it identifies
**one build rather than a commit**. The distinction is not pedantry and the section below explains it:
rebuilding `4f5f850` produces a different digest, so this row records what was published, not something a
reader could regenerate and compare against.

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

## Prediction scored, 2026-08-31: the push works, 4 is false, and the target misreported its own result

The first and so far only run of `make push`, from the build machine against a public repository, after
`docker login ghcr.io` with a classic token. It succeeded: ten layers pushed, the tag resolved, and the
digest above is what the registry reported.

**Prediction 1 is untested and stays that way.** It predicted the failure an operator sees on a clean
session -- an authentication error naming `ghcr.io` rather than anything about tags. The operator logged in
first, as instructed, so the unauthenticated path was never taken. Recording it as untested rather than
quietly dropping it, because the next person to run this on a fresh machine gets the free observation.

**Prediction 2 is consistent with the run, with one honest gap.** The token was created with
`write:packages` and nothing else, and the push needed no more than that -- so `repo` and an explicit
`read:packages` are indeed cargo-cult. The gap: the login is not in the captured output, which starts at
the `make push` invocation, so the scope is what was instructed rather than what is evidenced. A push that
needed more would have failed, which is most of the way there.

**Prediction 3 is not yet answerable.** The package's visibility has not been read. Note also that the
conditions changed underneath the prediction: it reasoned from a *pre-publish* push, where no source label
could link the package to a repository that did not exist. This push happened after publication, so the
link was available and the prediction's mechanism does not apply even if its conclusion does.

**Prediction 4 is false, in the more interesting direction.** It said the digest printed for the GHCR
reference would differ from any local digest for `mlops-platform/mlflow:2.22.4`, and that the local one
would not exist at all, on the reasoning that a local build has no registry digest until it is pushed.
Both halves are wrong. The local name carried a digest, and it was the *same* digest. The build output
shows why: `exporting manifest list sha256:7d41f069...` is printed during the **build**, before any push.
Under buildx with the containerd image store the manifest digest is computed from content at build time,
so it is not conferred by a registry at all -- the push confirmed a digest that already existed.

That does not overturn record 018's conclusion, which was to leave the built tag unpinned in compose, but
it does retire the premise this record gave for it. The correct reason is the one below.

### The target reported a real digest under the wrong image

`make push` printed:

```
mlops-platform/mlflow@sha256:7d41f0696592d57e118e75cc21d55c4949c32f2a5ff64f1155bd672cd7c2bdde
```

The digest is right. The reference is not: it names `mlops-platform/mlflow`, which docker normalises to
`docker.io/mlops-platform/mlflow`, where no such image exists. Both entrypoints read
`--format '{{index .RepoDigests 0}}'`, and a locally built image that has been pushed carries a digest for
its local name as well as for the pushed one. The order is not defined and index 0 was the local one.

**The failure shape is why this is now a test.** Nothing exited non-zero, no step failed, and the value
beside the wrong name was correct, so the only casualty was a line transcribed by hand into the table
above -- it would have named an image on Docker Hub. Both entrypoints now enumerate `RepoDigests` and
filter for the reference they pushed, refusing rather than guessing if it is absent, and
`test_push_reports_the_digest_of_the_reference_it_pushed` holds that in both files.

Worth noting where the same expression is still correct: `docs/setup.md` and record 018 use
`index .RepoDigests 0` to resolve the digests of *pulled* images, and a pulled reference carries exactly
one. The expression is not wrong; the assumption that a built-and-pushed image has only one name is.

### The same output shows the built tag being produced twice, which is a separate finding

`compose/docker-compose.yml` gives both `minio-init` and `mlflow` the same `image:` and the same `build:`
context, with a comment stating that "compose builds the shared tag once, so naming it twice costs
nothing". The build output contradicts the first half:

```
#11 [minio-init] exporting to image ... exporting manifest list sha256:8c561d3e...
#11 naming to docker.io/mlops-platform/mlflow:2.22.4 done
#12 [mlflow]     exporting to image ... exporting manifest list sha256:7d41f069...
#12 naming to docker.io/mlops-platform/mlflow:2.22.4 done
```

Two exports, two different manifest lists, both claiming the same tag, and the later one wins. Compose
reports `1/1` built, which is why this went unnoticed through every previous run. The layers themselves
were `CACHED`, so the images differ only in metadata.

**The mechanism is an inference and marked as one.** Both exports emitted an attestation manifest, and
provenance attestations record build timestamps, which would give identical layers two different configs
and therefore two different manifest digests. That is consistent with everything in the output and is not
proven by it.

Two consequences, and only the first is settled:

1. **Which image gets the tag depends on export order**, which nothing guarantees. Here `mlflow` exported
   second and won, and its digest is the one in the table. The layers are identical either way, so nothing
   runs differently -- but the digest recorded above is order-dependent, and a digest is supposed to be the
   thing that is not.
2. **The built image's digest is therefore not reproducible from a commit.** This is the real reason record
   018 is right to leave the built tag unpinned, replacing the premise scored false above. It also sits
   exactly beside record 019's opposite result: the *package inventories* reproduced byte-identically on a
   second host, because syft catalogues packages rather than manifests. Reproducible contents,
   irreproducible identity, and both statements are true at once.

What to do about the duplicate build is a decision this record does not take, because the options trade
against each other rather than one being right: drop `minio-init`'s `build:` and lose its independence
from an earlier `up`; disable provenance and get deterministic digests at the cost of an attestation this
repository's supply-chain story arguably wants; or accept it and say so here. The comment in compose is
corrected to describe what actually happens either way, since it currently asserts something false.

## Prediction scored, 2026-08-31 (the package page): 3 holds, and its diagnostic does not

The package landed **private**, so prediction 3 is confirmed on its conclusion. Its mechanism is a
different story, and so is the sentence this record wrote for whoever hit the problem.

**The prediction reasoned from a pre-publish push and this was a post-publish one.** It expected private
because no `source` label could link a package to a repository that did not yet exist. By the time the push
happened the repository was public and the label named it correctly. The package was still private.

**`Inherit access from repository` was already on, and inheriting still did not happen.** That is the
finding, because it explains the private badge better than "GHCR defaults to private" does: the package was
not linked to any repository, so there was nothing for it to inherit from. The setting was on and idle.
Linkage is upstream of inheritance, and this record treated them as one thing.

### The diagnostic this record gave is false and has been removed

It said that a package which is not linked "has the wrong `source` label or the repository name changed".
Both were checked and both were right. `images/mlflow/Dockerfile` carries
`org.opencontainers.image.source="https://github.com/bytes-of-entropy/mlops-platform"`, and that is the
repository, spelled correctly. So the sentence would have sent a reader to audit a label that was already
correct, which is worse than saying nothing: a confident wrong diagnostic costs more than an absent one.
The repository was connected by hand instead, from the package's settings page, and that worked.

### Why the label did not do it: two live explanations, neither excluded

**Nothing in this repository verifies that the label reaches the image.** A mirror test asserts the
Dockerfile contains it, and that is the whole chain: Dockerfile has the label, asserted; image carries the
label, *unverified*; registry reads it and links, failed. The middle link has never been checked, so:

1. **The label is not in the pushed image's config.** Cheap to exclude and not yet excluded.
2. **The label is present and GHCR did not read it, because the pushed artifact is an index rather than an
   image.** This push exported a manifest list plus an attestation manifest, and an index has no single
   config for a label to live in.

Hypothesis 2 is the more interesting one because it makes the attestation behaviour recorded above the
cause of *two* separate problems rather than one -- the irreproducible digest and the failed link -- and
because it would mean the fix for the first also fixes the second. That is exactly the reasoning that
should not be trusted before it is tested. Two hypotheses about a syft failure earlier the same day were
both wrong, and the appeal of a single explanation for two symptoms is not evidence for it.

**The discriminator is one command** on a machine that has built the image:

```
docker image inspect --format '{{json .Config.Labels}}' mlops-platform/mlflow:2.22.4
```

If the label is absent, hypothesis 1 is the answer and the Dockerfile or the build is at fault. If it is
present, hypothesis 1 is excluded and 2 becomes worth testing.

**Testing 2 is harder than it looks, and that is worth writing down now.** The package is manually linked,
so it cannot be used to observe an automatic link again. Confirming it would need a push of a
single-manifest image to a package name that has never existed, and then reading whether *that* one links
itself. That is a deliberate experiment against a throwaway package rather than something the next push
answers for free, and it is optional: the repository is linked, the visibility is correct, and the cost of
being wrong about the mechanism is a paragraph in a record rather than a broken artifact.

**What is not in doubt** is that the manual connect is a step, not a workaround for a defect. `PUBLISH.md`
now says so, because the alternative is a runbook that describes a normal outcome as a fault.

## Claim tested, 2026-08-31 (the batched run): hypothesis 1 is dead, and the digest is worse than feared

Four builds and one label read, on the build machine.

### The label is present, so the first explanation is excluded

```
org.opencontainers.image.source: https://github.com/bytes-of-entropy/mlops-platform
```

Read straight off `docker image inspect --format '{{json .Config.Labels}}'`. The label reaches the image,
spelled correctly, naming the right repository. So the possibility that it never got there -- the one this
record could not exclude and nothing in the repository had ever checked -- is now excluded, and the middle
link of that chain has finally been measured once.

Hypothesis 2 is what remains: GHCR did not read the label because the pushed artifact is an index with no
single config for a label to sit in. It is now the only explanation standing, which is a weaker position
than it sounds -- it survived by elimination among two guesses, and a third nobody has thought of would
also survive that.

### The built image's digest is not reproducible, and the duplicate build is worse than described

With attestations on, two builds with no source change between them:

```
pass 1:  3c0400b1...   and   293d7a77...
pass 2:  367e708b...   and   7660142d...
```

**Four exports, four different digests.** Two conclusions, both now measured rather than inferred:

1. **A rebuild of the same commit produces a different image digest.** The section above suspected this;
   it is now observed twice. So the digest in this record's table identifies one build and nothing more,
   and no reader can regenerate it for comparison. That is the real reason record 018 is right to leave
   the built tag unpinned.
2. **The two exports inside a single build produce different digests from each other**, not merely from
   the previous build. The earlier run showed this once and it could have been coincidence of timing; it
   is now four for four. So `mlops-platform/mlflow:2.22.4` genuinely names two different images during
   every `make build`, and which one keeps the tag is decided by export order.

### With attestations off, the build stops producing an index at all

This is the result worth the run, and it arrived by accident. With `BUILDX_NO_DEFAULT_ATTESTATIONS=1`,
**no `exporting manifest list` line appears at all** -- in either pass. The export still happens, since the
`naming to` lines are there and the cache state is the same as the passes above. Buildx is producing a
single manifest instead of an index.

That is precisely the shape hypothesis 2 says GHCR needs. A single-manifest image has a config, and a
config is where a label lives. So disabling attestations is not only the candidate fix for the digest
problem, it is also the candidate fix for the linking problem, from a run that was not testing linking.

**Marked as support, not proof.** Nothing here observed GHCR reading anything. The chain is: attestations
off produces a single manifest (observed), a single manifest has a config carrying the label (true by
construction), GHCR reads the label from the config (still assumed). Testing the last step needs a push to
a package name that has never existed, for the reason already recorded -- a manually linked package cannot
demonstrate an automatic link.

### And the measurement this run was built to take, it did not take

Whether attestations-off digests are *reproducible* is still unknown, and the fault is in the instrument.
The filter watched for `exporting manifest list`, and with attestations off the line reads `exporting
manifest` with no `list`, so the digests were printed by the build and discarded by the grep. The pair that
would have confirmed or refuted the provenance-timestamp explanation was thrown away between the build and
the log.

So that explanation stands exactly where it did before the run: plausible, consistent with everything, and
unconfirmed. The filter also dropped the `[minio-init]` and `[mlflow]` prefixes, so the four digests above
cannot be attributed to targets either -- both are fixed, and re-running costs about a minute.

A filter written to observe one shape, applied to the shape it was meant to detect a change in. Worth
naming rather than quietly fixing: the same run that excluded hypothesis 1 for good failed to answer the
question it was designed around, because the instrument encoded the assumption under test.

## Claim tested, 2026-08-31 (fixed instrument): provenance confirmed, and the layers were always fine

The filter from the previous section, corrected to match `exporting manifest` rather than `exporting
manifest list` and to keep the `[target]` prefixes. The same four builds, now legible.

**With attestations on, across two builds:**

```
pass 1   [minio-init]  manifest 0c27cd2d   index c60082ec
         [mlflow]      manifest 45e78a9d   index 98b874b9
pass 2   [minio-init]  manifest 0c27cd2d   index 110aec95
         [mlflow]      manifest 45e78a9d   index 4f7fe211
```

**With attestations off, across two builds:** `0c27cd2d` and `45e78a9d`, no index at all, both passes.

**The image manifests never moved and every index digest did.** They also match the manifests from the
original push run hours earlier -- `0c27cd2d` and `45e78a9d` there too. So the provenance-timestamp
explanation is confirmed, and the more useful way to state the result is the inverse of how this record
kept framing it: **the layers were always reproducible.** What was never reproducible was the index
wrapping them, because a provenance attestation records when the build ran. Three runs, six exports per
state, no exceptions.

That retires "the built image's digest is not reproducible" as stated twice above. The image's digest is
reproducible and always was. The *published* digest was not, because what got published was an index.

**So both entrypoints now build with `BUILDX_NO_DEFAULT_ATTESTATIONS=1`**, overridable, with a mirror test
holding the parity -- a setting honoured on one platform and ignored on the other would have two machines
publish two digests for identical layers, each looking like the other had changed something.

### Prediction (recorded before the next push)

1. A `make push` from either entrypoint now reports a digest equal to the manifest the build exported,
   stable across rebuilds of the same commit. Confidence: high, and the specific value is predicted below.
2. The committed inventories under `sbom/` do not change. Confidence: high. The layers are identical, and
   record 019 commits package lists rather than digests precisely so that image identity churn cannot move
   them. CI's `git diff --exit-code -- sbom/` is the check and it costs nothing to watch.
3. The published digest is `sha256:45e78a9d...` **if mlflow exported last, and `sha256:0c27cd2d...` if
   minio-init did.** Confidence: high that it is one of the two, low on which. That is not a hedge; it is
   the next finding.

### The duplicate build survives the fix, and removing it is not safe

Turning off attestations does not make the two exports agree. `0c27cd2d` and `45e78a9d` are stable but
**different from each other**, and both name `mlops-platform/mlflow:2.22.4`. The reason is now visible in
the labels read in the same run: compose stamps `com.docker.compose.service` into each image it builds, so
minio-init's copy says `minio-init` and mlflow's says `mlflow`. Identical layers, one differing label, two
digests.

**Export order is not fixed, and this run observed it flip.** With attestations off, pass 1 exported mlflow
as `#10` and minio-init as `#11`; pass 2 reversed them. The later export wins the tag. So which of the two
images `docker compose up` runs, and which one `make push` publishes, varies between builds on one machine
with no source change. Nothing behaves differently -- the entrypoint is overridden per service at run time
-- but the published digest is decided by a race.

**And the obvious fix is unsafe, which is why it is not being applied.** Dropping `minio-init`'s `build:`
key would leave one export and one digest. But `_build_context` in `tests/test_image_supply.py` and
`_context` in `supply/images.py` both classify a service with no `build` key as **pulled**, and record 018
requires every pulled reference to be digest-pinned -- which a locally built image cannot be. It would also
move `mlops-platform/mlflow:2.22.4` into the SBOM's pulled list and change the committed inventories.

So that duplicate `build:` key is load-bearing in a way its own comment never claimed: it is what keeps the
shared tag classified as built. Two contract properties depend on it, and the comment beside it talked
about `run minio-init` instead. Recorded here because the next person to see two builds of one tag will
reach for exactly that deletion.

**What remains open**, deliberately, as a smaller and better-understood question than when this section
started: making `push` publish a known one of the two rather than whichever won the race. The cheap version
is a guard -- `push` refuses unless the image it is about to publish carries
`com.docker.compose.service=mlflow` -- which costs one assertion and no restructuring. Not applied in the
same commit as the attestation change, because a fix and a guard against a different defect do not belong
together, and because prediction 3 above is worth observing before it is prevented.
