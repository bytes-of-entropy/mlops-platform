# 002 — Serving is a plain Deployment, Service and Ingress; no KServe

- **Date:** 2026-08-18
- **Status:** accepted
- **Component:** `charts/`
- **Milestone:** r3-m2

## Context

The gap this repository closes is Docker and Kubernetes literacy. The question a reviewer asks is
whether the author can containerize a model service, get it scheduled, keep it healthy, scale it and
roll it back. A serving framework — KServe, Seldon, BentoML's operator — answers a different
question: whether the author can install and configure someone else's abstraction over those things.

## Decision

Model serving is a plain `Deployment`, `Service` and `Ingress`, with liveness and readiness probes, a
resource request and limit, and an `HorizontalPodAutoscaler`. Charts are versioned. No serving CRD is
installed.

## Alternative rejected

KServe. It is the more impressive line on a resume and it is what a large platform team would
actually run. It loses on two counts. First, it hides exactly the mechanics being demonstrated: an
`InferenceService` that works tells a reviewer nothing about whether the author understands probes.
Second, it is a CRD, a controller and a service mesh dependency to install, debug and explain inside
a `kind` cluster on a laptop — cost measured in days, against a gap that a Deployment closes.

## Prediction (recorded before the evidence)

I expect the plain-manifest version to survive hostile questioning better than the KServe version
would, because every field in it is one I chose and can defend. I also expect to be asked "why not
KServe" in at least one interview, and to be able to answer it in two sentences.

## Deciding evidence

None yet. Decided on judgement before M2 is built; the hostile-question dry run at the gate is the
first test of it.

## What would change my mind

A target role whose platform is explicitly KServe-based, which would make familiarity with the CRD
the point rather than a distraction. In that case the right move is a separate small repository, not
a rewrite of this one.

## Consequences

Makes the serving path fully legible and cheap to run on a laptop. Makes the repository silent on
serving-framework experience, which is a real omission and is stated as one in the README rather than
papered over.
