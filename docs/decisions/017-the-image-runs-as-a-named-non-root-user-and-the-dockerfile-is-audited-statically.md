# 017: The built image runs as a named non-root user, and the Dockerfile's properties are asserted by reading it

- **Date:** 2026-08-27
- **Status:** accepted
- **Component:** `images/`
- **Milestone:** M1

## Context

M1 is image hardening, and the roadmap names four things: multi-stage, non-root, pinned digests, and a
vulnerability scan with an SBOM. Three of those cannot be checked without a daemon and a registry. One
can be checked by reading a text file, and it is the one that is wrong today.

`images/mlflow/Dockerfile` inherits `ghcr.io/mlflow/mlflow:v2.13.0`, which runs as root, and adds
nothing to change that. So the tracking server, the bucket provisioner that shares the image, and
anything either of them executes all run as uid 0 inside the container. On this compose spine that is
not an exploit; it is the default that turns one container escape into a host compromise, and the
reason every hardening checklist starts there.

There is a second thing this milestone can settle cheaply, and record 012 already established the
pattern for it. That record sorts every `image` key by whether its service builds, and asks a registry
about the tags. It proves the references resolve. It says nothing about what the built image *is*, and
the properties that matter for hardening are properties of the Dockerfile's text: which user it ends
as, whether its base is pinned by digest, whether its `pip install` names versions. Those are
assertable without Docker, in the same way `tests/test_layering.py` in Repo 1 asserts the dependency
direction by parsing an AST rather than by importing anything.

## Decision

**The built image ends with a `USER` directive naming a non-root account that the Dockerfile creates.**
`mlflow` with a fixed uid and gid, created with no login shell and no password, owning only what it has
to. The provisioner script it copies is read-only to that user, because a one-shot that can rewrite
itself is a one-shot with more privilege than its job needs.

**The Dockerfile's hardening properties are asserted by a test that parses it**, not by a comment
claiming them. Four properties, each of which has failed silently in a real project: the final `USER`
is not root and not numeric zero; no `FROM` names `latest`; every `pip install` pins with `==`; and
`--no-cache-dir` is present so a layer does not carry a wheel cache nobody will use.

**Digest pinning is deliberately not in this record's scope, and a fifth test is owed.** A digest
cannot be invented from a laptop with no registry access, and a test that accepted a tag would be a
gate that passes without looking. The digests get resolved on the machine that pulls the images, the
`FROM` lines and the compose `image` keys are rewritten to `name:tag@sha256:...`, and the test that
requires them lands in that same commit. Until then this record claims non-root and a static audit and
nothing about digests.

**Multi-stage is rejected for this image, with a reason rather than by omission.** See below.

## Alternative rejected

**Rebuild MLflow from `python:3.11-slim` in a multi-stage build.** This is what the checklist means by
multi-stage, and it would let a builder stage compile wheels and a runtime stage carry none of the
toolchain. Rejected because the delta this repository adds to the published image is two pip packages
(record 011), and rebuilding the server itself to save a layer means owning MLflow's own dependency
resolution, its entrypoint, and its version compatibility with the tracking schema. That is a large
surface taken on for a smaller image, in a repository whose subject is the platform rather than the
image. Multi-stage stays available and unused, and the checklist item is answered as "considered and
declined for this image", which is a different thing from "not done".

**A numeric `USER 1000` with no account behind it.** Shorter, and it works: the process runs unprivileged.
Rejected because a uid with no passwd entry produces confusing failures in anything that looks up its own
identity, and because `USER mlflow` says what it is while `USER 1000` says what it happens to be.

**Trusting a comment.** The Dockerfile could simply say it runs as non-root. Every claim in this
repository that was only a comment has eventually been wrong, and the two that were tested were not.

## Prediction (recorded before the evidence)

1. The MLflow server starts and reports healthy as a non-root user with **no other change**: no chown of
   a data directory, no permission fix. Confidence: moderate. The tracking server writes to Postgres
   and to S3 rather than to local disk here, so it should need nothing on the filesystem it does not
   already have, and if that is wrong the failure will be a write to a path the image created as root.
2. The bucket provisioner, which shares the image and runs as a one-shot with a different entrypoint,
   also needs no change. Confidence: moderate to high; it makes one boto3 call and writes nothing.
3. The static audit finds at least one thing wrong beyond the missing `USER` when it first runs.
   Confidence: low, and stated because a check written to confirm what its author expects is a check
   that will pass. The Dockerfile already pins its pip installs and uses `--no-cache-dir`, so the
   honest expectation is that this prediction fails and the audit only catches the user.
4. Adding the digest pins later changes no test in the suite except the one written for them.
   Confidence: high. Nothing in the suite reads a tag's text except record 012's inventory, which sorts
   on the presence of a `build` key rather than on the tag's shape.

## Deciding evidence

Empty until the image is built on a machine with a daemon. The static audit runs everywhere and its
result is in the suite from this commit; the runtime half of prediction 1 needs `make up`.

## What would change my mind

If the server or the provisioner needs a chown, a writable volume, or a capability to run as non-root,
predictions 1 or 2 fail and the record gains a section describing exactly what the image needed, because
"runs as non-root" with an undocumented permission fix underneath it is the kind of half-truth this
repository exists to avoid.

If the digest pins turn out to break record 012's registry probe — if a digest-pinned reference cannot
be asked about the way a tag can — then prediction 4 fails and that probe is rewritten before the pins
land, not after.

## Consequences

The image is one directive harder to misuse and the Dockerfile now has four properties that cannot
regress silently. What it does not have is a digest, so the supply-chain claim is still the one record
012 makes and no stronger; anyone reading this milestone as "images are pinned" would be reading ahead
of the evidence, which is why the scope boundary is in the Decision rather than in a footnote.
