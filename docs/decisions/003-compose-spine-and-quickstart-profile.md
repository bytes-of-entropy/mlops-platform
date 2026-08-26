# 003: The spine is docker-compose with pinned tags, and the quickstart is a capped profile

- **Date:** 2026-08-18
- **Status:** accepted
- **Component:** `compose/`
- **Milestone:** M0

## Context

Every later milestone in this repository, and both flagship repositories, run against the same local
services: object storage standing in for S3, a tracking server, a scheduler, a Spark cluster, and a
metadata database. That spine has to satisfy two audiences with incompatible budgets. The build
machine has 32 GB and can run three Spark workers; a reviewer following the quickstart has a laptop
with other things open and will abandon a repository that swaps.

## Decision

One `compose/docker-compose.yml` holds the full spine with every image pinned to an exact tag, a
healthcheck on every service, `depends_on` gated on `service_healthy`, named volumes for all state,
and declared CPU and memory limits. The second Spark worker and Airflow sit behind a `full` profile.
A `compose/docker-compose.quickstart.yml` override cuts the remaining services to a total of 3.8 GiB
and 2.0 CPUs, and the totals are asserted by a test rather than claimed in prose.

`make down` stops containers and keeps volumes; only `make clean` removes them.

## Alternative rejected

A single unprofiled compose file plus a README paragraph saying "reduce the worker memory if you
have less RAM". It is less machinery. It loses because an unverified claim about a 4 GB envelope is
exactly the kind of README statement this portfolio's publication gate exists to forbid, and because
the failure mode (a reviewer's laptop swapping during the ten-minute quickstart) is invisible to
the author and fatal to the reviewer.

## Prediction (recorded before the evidence)

I expect the envelope tests to catch at least one real regression as services are added at M1 and M2,
most likely a service added without a limit rather than a limit set too high. I expect the pinned
tags to require at least one deliberate bump before publication, and I expect the Airflow image to be
the one that forces it.

## Deciding evidence

The contract and envelope suites pass on a machine with no container runtime installed, which is what
makes them useful in CI. The full `up`/`down` cycle is asserted by `tests/test_idempotency.py`, which
is skipped where no runtime exists and must be run on the build machine before the M0 gate passes.

## What would change my mind

If the quickstart turns out to need Airflow to demonstrate anything worth seeing, the profile split
is wrong and the envelope has to be renegotiated rather than the claim quietly dropped.

## Consequences

Makes the reviewer path checkable and the reproducibility claim mechanical. Costs two compose files
and a small test suite to maintain, and it means every new service must arrive with limits and a
healthcheck or the build goes red, which is the intent.
