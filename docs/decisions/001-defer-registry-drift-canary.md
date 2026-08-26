# 001: Defer the registry, drift and canary milestones until two real workloads exist

- **Date:** 2026-08-18
- **Status:** accepted
- **Component:** repo-wide
- **Milestone:** M0

## Context

This repository is the platform that the two flagship repositories deploy onto. Its original plan
ran to six milestones before either flagship existed: compose spine, images and CI, Kubernetes
serving, model registry and promotion, drift detection with a retrain trigger, canary and rollback.
Four of those describe operating a model that is not written yet.

A promotion policy invented before there is a model to promote encodes guesses about a workload
nobody has run. It also blocks publishing: the repository stays private, closing no gap, while the
flagships take months.

## Decision

M0 (compose spine), M1 (images and CI) and M2 (Kubernetes serving) are built now and the repository
publishes on them. M3 (registry and promotion), M4 (drift and retrain trigger) and M5 (canary and
rollback) are deferred until both flagships exist and there are two real workloads to promote,
monitor and roll back. They land afterwards as dated additions, which is a more honest history than
a repository that appeared complete on day one.

## Alternative rejected

Build all six now against a stub model. It would look complete sooner and it is the more impressive
repository at a glance. It loses because every threshold in it would be arbitrary: a drift trigger
tuned against synthetic data proves the plumbing works and says nothing about whether the trigger
fires when it should. A reviewer who asks "why 5% recall degradation" gets an answer about a stub.

## Prediction (recorded before the evidence)

Publishing on M0–M2 will close the containerization gap in reviewer terms as completely as
publishing on M0–M5 would, because the gap is about Docker and Kubernetes literacy rather than about
MLOps maturity. I expect no interviewer to remark on the absence of a registry milestone, and I
expect at least one to ask why the drift thresholds are what they are, a question that is
answerable only in the deferred version.

## Deciding evidence

None yet. Decided on judgement; revisit after the first two interviews that reach this repository.

## What would change my mind

A reviewer treating the absent registry as evidence of an incomplete platform rather than a staged
one, or a flagship needing promotion mechanics before M2 ships.

## Consequences

Makes it possible to publish this repository months before the flagships, which is what closes the
gap early. Makes the eventual M3–M5 work harder to schedule, because it lands when attention has
moved on. The deferral is stated in the README so the gap is visible rather than concealed.
