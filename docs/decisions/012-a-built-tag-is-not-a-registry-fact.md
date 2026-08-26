# 012: Probe the base a built image comes from, not the tag it is built into

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `tests/`
- **Milestone:** M0

## Context

`test_every_pinned_image_still_resolves` asks a registry about every `image` key in the compose file.
That was exactly right while every image was pulled. Decision 011 added a built one, and the built
service keeps an `image` key on purpose (the tag is what `ps` and `inspect` report), so the tag
`mlops-platform/mlflow:2.13.0` silently joined the set of things a registry gets asked about. No
registry has heard of it, because this repository produces it. `docker manifest inspect` returned exit
code 1 and the suite reported a withdrawn pin, on the first run of the tier that got far enough to
reach the assertion.

Two things went wrong and only one of them is the visible failure. The visible one is a false alarm
naming an upstream problem that does not exist. The other is a silent loss of coverage: the pin that
*was* being checked, `ghcr.io/mlflow/mlflow:v2.13.0`, stopped being checked the moment the service's
`image` key changed, and nothing said so. A test whose input set is derived from the configuration can
have its premise revoked by an edit to that configuration, and it will keep passing, or fail for the
wrong reason, without anyone editing the test.

## Decision

Sort every `image` key into one of two sets by whether its service declares a `build`, and ask a
registry about the pulled tags plus the `FROM` of everything built here. A third test asserts the two
sets account for every `image` key between them, so a tag can move from one to the other but cannot
fall out of both.

The supply-chain claim is unchanged in substance and moves one level down, which is where the pin now
lives: what an upstream publisher could withdraw is `ghcr.io/mlflow/mlflow:v2.13.0`, and that is again
probed. The count of references probed is five either way.

## Alternative rejected

**Assert the built tag exists locally, with `docker image inspect`.** It is the honest local
counterpart and it was rejected because it asserts something about the order things ran in rather
than about the spine: the tag exists if someone has built it, so the test passes or fails on whether
`make build` came before `pytest` in this session. That is a fact about a session, and a test that
changes answer with no change to the code is worse than no test. The build is proven by the stack
starting at all, which is the assertion the integration tier already makes.

Also rejected: **excluding built services from the module entirely.** Cheapest to write, and it would
have left the base image unprobed, turning a false alarm into a silent gap, which is the worse of the
two failures.

## Prediction (recorded before the evidence)

The resolution tier passes on all five references on the next run, with `ghcr.io/mlflow/mlflow:v2.13.0`
among them. `test_every_service_image_is_either_pulled_or_built` is the test that fails first if a
second service is ever given a `build`, before anyone notices the coverage moved.

## Deciding evidence

The failure itself: `AssertionError: resolving mlops-platform/mlflow:2.13.0 failed with exit code 1`,
on the build machine, with every other assertion in the tier passing. Locally, the two sets now read
four pulled tags and one base, five references in total, the same number the module probed before
decision 011, and no longer the same five.

## What would change my mind

A registry this project actually publishes to. If the built image is ever pushed, its tag becomes a
registry fact like any other and belongs back in the probed set, at which point the interesting
question is the reverse one, whether the pushed tag matches what the Dockerfile would produce today,
and neither of these tests answers that.

## Consequences

Makes it harder to lose supply-chain coverage by editing the compose file, which is how it was lost
here. Makes explicit that this repository builds one image and pulls the rest, in a place that fails
when that stops being true.

Leaves one gap named rather than hidden: nothing asserts that the locally tagged image was built from
the Dockerfile currently on disk. A stale tag from an earlier build satisfies compose, and only a
rebuild, which both `up` targets now force with `--build`, makes them agree.
