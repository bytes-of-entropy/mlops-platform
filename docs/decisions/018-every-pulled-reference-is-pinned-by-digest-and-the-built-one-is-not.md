# 018: Every reference a registry hands over is pinned by digest, and the one built here deliberately is not

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `compose/`, `images/`
- **Milestone:** M1

## Context

Record 012 established that a tag is not a registry fact, and answered it by *probing*: it sorts every
`image` key by whether its service declares a `build`, asks a registry about the pulled tags and about
the `FROM` of everything built here, and asserts the two sets account for every key. That proves the
references resolve today. It does not stop them resolving to something else tomorrow.

`apache/spark:3.5.1-python3` is a tag. Its publisher can move it, and if they do, the next `make up`
builds a different platform than the one the suite passed on, with nothing in the repository changed and
no test able to notice. That is the gap this record closes, and it is the last of M1's hardening items
that can be closed by editing text.

There is one reference in the spine that must **not** be pinned this way, and identifying it is most of
the value here. `mlops-platform/mlflow:2.13.0` is built locally. `docker image inspect` will happily
report a `RepoDigests` entry for it, and pinning the compose key to that digest would look like the same
discipline while being its opposite: a local digest is a fact about one machine's image store, not about
a registry, so it would pin the spine to an artifact no other machine can obtain. It is exactly the
mistake record 012's title names, arrived at by trying to be more rigorous.

## Decision

**Every pulled reference carries both a tag and a digest**, as `name:tag@sha256:...`. The tag stays
because it is what a reader recognises and what a version bump edits; the digest is what the build
resolves. A digest with no tag beside it is unreadable, and a tag with no digest is a pointer.

**The one built reference stays a bare tag, and a test asserts that it does.** The supply-chain claim
for `mlops-platform/mlflow:2.13.0` is made where it can be made: on its base, in the Dockerfile, which
is now `ghcr.io/mlflow/mlflow:v2.13.0@sha256:47c5c26d...`. Pinning the built tag as well would assert a
registry fact that does not exist.

**The split reuses record 012's, rather than declaring a second one.** `pulled_images()` and
`built_bases()` already sort every reference by whether its service builds. The new assertions read the
same functions, so a service gaining or losing a `build` key moves its reference between the two rules
automatically and cannot fall outside both.

**Where the digests came from is recorded, because one of them has a different provenance.** Four were
read from `docker image inspect --format '{{index .RepoDigests 0}}'` on the build machine after a
successful `make build` and a green suite, so they are the digests that actually passed. The fifth,
`apache/airflow:2.9.2-python3.11`, was not: `docker compose config --images` omits it because that
service sits in the `full` profile, so it was resolved from Docker Hub's public tag API instead. That is
a manifest-list digest for the tag as it stood at query time rather than a digest observed locally, and
if the tag has moved since the build machine pulled it, the two differ.

## Alternative rejected

**Digests only, no tags.** Unambiguous and what a strict supply-chain policy asks for. Rejected on
readability: `postgres@sha256:36ed7122...` tells a reader nothing about which Postgres, so every version
question becomes a registry lookup, and the version bumps this repository schedules in its own guide
would become edits nobody can review. The tag is documentation and the digest is the constraint.

**Keep probing and do not pin.** Record 012's position, and it has a real argument: a probe catches a
withdrawn image, which a pin converts into a build failure with a less helpful message. Rejected
because they answer different questions. The probe asks "does this still exist"; the pin asks "is this
the same bytes". Both are kept, and the probe now runs against pinned references, which is strictly more
informative than before.

**Pin the built image to its local digest.** Covered above. It is the trap this record exists to name.

## Prediction (recorded before the evidence)

1. The next `make build` and `make up` on the build machine succeed with no change other than these
   pins, because four of the five digests are the ones that machine already has. Confidence: high for
   those four.
2. `apache/airflow:2.9.2-python3.11@sha256:fcffeccf...` resolves to the image that machine already
   pulled, so nothing re-downloads. Confidence: moderate, and this is the one worth watching. If the
   digest is wrong the failure is loud and immediate: a manifest-not-found on pull, not a subtly
   different platform. A pinned digest that is wrong is safer than a tag that moved, which is the whole
   argument for pinning.
3. Record 012's registry probe passes unchanged against digest-pinned references. Confidence: moderate.
   It parses `image` keys and asks a registry about them, and a reference carrying both a tag and a
   digest is still a valid reference, but nothing has tested that path.
4. No other test in the suite reads the text of an image tag. Confidence: high; the compose-contract
   tests sort on the presence of a `build` key and the port tests on the ports.

## Deciding evidence

Empty until the build machine runs `make build` and the integration tier again against these pins. The
static half is in the suite from this commit and runs anywhere: nine assertions over the pulled set, the
built set and the Dockerfile bases.

## What would change my mind

If the airflow digest does not resolve, prediction 2 fails, and the fix is to replace it with the value
that machine reports rather than to remove the pin. A wrong digest found on the next pull is the
mechanism working.

If record 012's probe cannot handle a digest-pinned reference, prediction 3 fails and that probe is
rewritten before these pins are relied on, not after.

## Consequences

`make up` now resolves to the same bytes on every machine until somebody edits a digest, and a version
bump becomes a two-line change with the tag and the digest visibly disagreeing until both are updated —
which is a feature, because the disagreement is exactly the review question.

What this does not do is make the images trustworthy; it makes them *identical*. A pinned digest of a
vulnerable image is a reliably vulnerable image, and the scan that would say so is the M1 item still
outstanding.

## Extended, 2026-08-31: the rule reaches CI actions, which it should have from the start

This record has been about images since it was written, and the reasoning was never about images. It is
about pulled third-party code and a publisher's ability to move a pointer after review. Ten `uses:` lines
in `.github/workflows/` rode floating major tags — `actions/checkout@v4`, `azure/setup-helm@v4` — which
is the same arrangement this record rejects for `postgres:16.15-alpine`, and the case for pinning them is
*stronger* rather than weaker: a workflow action runs on the runner with the job's token and can read
whatever the job can, while a base image runs inside a container this repository configures.

All ten are now pinned to a commit SHA with the version in a trailing comment. The comment is not
decoration — a bare forty-character hex string tells a reader nothing about how old the pin is, and a
bump has to be legible in review. Three assertions in `tests/test_toolchain_pins.py` hold it: every
`uses:` resolves to a commit, every pin carries a version comment, and there are at least four actions to
check at all, because a rule that matches nothing passes.

**Two things this cost, both worth saying.** The four actions were also several majors behind — checkout
and setup-python at v4 and v5 against a current v7 — so pinning meant choosing a version rather than
inheriting one, and each was bumped to its current release after checking that the inputs actually passed
(`python-version`, `name`, `path`, `version`) are still the documented ones.

And this was found by asking whether the pins resolved at all, prompted by a narrower worry: **CI has
never run.** No remote exists, so not one of these workflows has ever executed, and a wrong action
reference would have failed the first push rather than anything before it. That is still true of
everything else in those files. Pinning removes one class of first-run failure; it does not make the
workflows tested, and `PUBLISH.md` says to read the Actions tab on the first push for exactly that reason.
