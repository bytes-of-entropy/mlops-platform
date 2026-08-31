# 024: The chart covers the tracking core, and its stateful parts are Deployments

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `charts/`
- **Milestone:** M2
- **Extends:** record 002 (no serving CRD), record 015 (a provisioner creates the bucket), record 018
  (digest pinning), record 014 (chart versions are orderable)

## Context

M2 asks for "`make kind-deploy` → healthy pods; plain Deployment/Service/Ingress; probes correct; HPA
scales under synthetic load; `helm lint` clean; charts versioned so the flagship pins a release".
Record 002 already fixed the shape — plain manifests, probes, requests and limits, an HPA, no serving
CRD — so what was left to decide was scope and the handful of places where Kubernetes cannot be given
the same answer as compose.

The compose spine runs six images. Two of the decisions below are about which of them belong here, and
the rest are about the four places where a faithful port would have been wrong.

## Decision

**The chart covers MLflow, Postgres and MinIO. Spark and Airflow are not in it.**

This is not a subset chosen for effort. "Plain Deployment" is the wrong model for both, and a chart
that pretended otherwise would misrepresent how either runs. Spark on Kubernetes is
`spark-submit --master k8s://` or an operator, which creates driver and executor pods per job and is
the opposite of a long-lived Deployment; the anti-scope forbids the operator and rightly so. Airflow's
own chart is thousands of lines and exists because the topology — scheduler, triggerer, workers, an
API server, a migration job — is genuinely that complicated; reducing it to one Deployment would
demonstrate that the author had not looked.

Every one of M2's criteria is demonstrable on the tracking core, and the roadmap's own anti-scope
names the failure to avoid: "infrastructure with no workload is the most common way an MLOps repo
reads as padding". MLflow serving real requests against a real backend store and a real object store
is a workload. Three Deployments that exist to be counted would not be.

**Postgres and MinIO are Deployments with `strategy: Recreate` and a PVC, not StatefulSets.**

At one replica a StatefulSet buys nothing this needs. Its distinguishing features are stable ordinal
identity, a per-replica volume template, and ordered rollout — all of which are about replica *two*.
The milestone says plain Deployment, and adding a controller concept to gain properties that only
matter at a scale this chart does not reach would be the padding the anti-scope warns about.

`Recreate` is not cosmetic. The default `RollingUpdate` would start a second Postgres against a
`ReadWriteOnce` volume the first one still holds, and the new pod would sit `Pending` on a volume that
is never released, because the old pod is not asked to leave until the new one is Ready. One replica
and one volume means the old pod goes first.

**This is the right answer for a kind demo and the wrong answer for production, and that is stated
here rather than left for a reader to notice.** Production Postgres is not a single pod with a PVC
whatever the controller: it is a managed service, or an operator that handles failover, backups and
point-in-time recovery. The chart demonstrates that the author can schedule a stateful workload
correctly; it does not claim to be how one should run a database.

**The bucket is created by an initContainer, not a Helm hook Job.**

Record 015 exists because a missing bucket survived a green M0 — the smoke path logged a param and a
metric, both of which go to Postgres, so nothing walked the artifact path and nothing failed. A
`post-install` hook runs once per release. It does not run when a pod is rescheduled onto another node,
when a node is drained, or when the Deployment restarts for any reason, and in every one of those cases
MLflow comes up pointing at an artifact root that may not exist. An initContainer runs before its own
pod's container every time, and blocks exactly the thing that needs the bucket. The script is
idempotent, so the cost is one round trip per pod start.

**The chart holds no credential, and the Secret is created outside it.**

`make kind-deploy` runs `kubectl create secret generic --from-env-file=.env`, and every workload reads
it by `secretKeyRef`. `values.yaml` names the Secret and its keys and nothing else. This is the same
arrangement compose has: both read `.env`, neither stores a value. A contract test asserts no template
renders a `Secret`, because a Secret built from values means the values hold the credential — and
values files get committed.

`--from-env-file` rather than repeated `--from-literal` is deliberate. `--from-literal=KEY=value` puts
the credential in the command line, where it reaches the process table and the shell history. The cost
is that the Secret carries two Airflow keys nothing in this chart reads, which is over-broad by two
keys and preferable to putting a password in `argv`.

**MLflow's backend URI is assembled by Kubernetes at container start, not by Helm at render time.**

The URI contains the Postgres password. Interpolating it in the template would put it in the rendered
manifest, readable by anyone who can run `kubectl get deploy -o yaml`. The args instead contain the
literal string `$(POSTGRES_PASSWORD)`, which Kubernetes substitutes from the container's environment —
so the credential is in the environment, as it already is under compose, and not in the object.

**Everything that differs between kind and EKS is a value, not a template.**

`OFFLINE_FIRST.md` promises "same manifests, same Helm charts" across the two, with the delta being
IRSA, the ALB ingress controller and the EBS CSI driver. That promise is only true if the templates
never learn which cluster they are on, so `ingressClassName`, the storage class, the image references
and the pull policy are all keys. `charts/kind-cluster.yaml` holds the things that are facts about kind
— published ports for an Ingress with no load balancer in front of it, and the `ingress-ready` label
its controller schedules on — and nothing in the chart refers to them.

`pullPolicy: IfNotPresent` is the only setting that serves both. `Never` forbids the pull EKS depends
on; `Always` makes the locally built image unusable, because nothing can pull `mlops-platform/mlflow`
from anywhere. The `digest` key is empty for that image, which is record 018's argument as a value: a
local build has no registry digest, and setting one would pin the chart to a single machine's image
store.

**The chart's version is its own, not the repository's.** `0.1.0` here and `v0.2.0` on the repository
are answering different questions. A chart version that tracked the repository's would force every
consumer to re-pin for a change to a test or a document.

## Alternative rejected

**Chart all six services, for parity with compose.** The strongest "it really is the same platform"
claim, and it requires modelling Spark and Airflow as things they are not. It also roughly triples the
chart against a 4 GB reviewer budget that already has a control plane, metrics-server and an ingress
controller in it before any workload starts.

**StatefulSets for Postgres and MinIO.** More correct in the abstract and the milestone says plain
Deployment. See above: at one replica the difference is a concept, not a behaviour. The honest version
of this rejection is that a reviewer who asks "why not a StatefulSet" should get the answer in this
record rather than a shrug, which is why the paragraph above says what a StatefulSet is actually for.

**MLflow alone, with stubbed backends.** Satisfies every criterion faster, and produces a chart with
one workload and two mocks — which is a tutorial. The artifact path is exactly what record 015 shows
goes wrong when nothing exercises it.

**A `post-install` hook Job for the bucket.** The idiomatic Helm answer, and it runs once per release
rather than once per pod. Rejected on record 015's evidence.

**Creating the Secret from values, with `create: true`.** Convenient, and it puts a password in a file
that gets committed. A `create` toggle briefly existed in `values.yaml` and came out during this work
because no template read it: a switch that looks operative and is not is worse than its absence, and
the invariant belongs in a test rather than a hint.

## Prediction (recorded before the evidence)

1. `helm lint` passes first time, and `helm template` renders without error. Confidence: moderate. The
   contract tier already checks that every `.Values` reference resolves — 56 of them — which is the
   defect most likely to break rendering, but no test here can catch a malformed `nindent` or a
   mis-scoped `.` inside a `define`.
2. **The non-root `securityContext` on Postgres or MinIO fails on the first cluster run.**
   Confidence: moderate to high, and this is the prediction I would least like to be wrong about in
   the comfortable direction. A `ReadWriteOnce` volume arrives owned by root; `fsGroup` is what makes
   a non-root process able to write to it, and `999`/`1000` are read off each image's conventional
   account rather than verified. If it fails, the symptom will be a permission error from `initdb` or
   from MinIO's data directory check, and the fix is a values change rather than a template one.
3. The HPA reports `<unknown>` until metrics-server is installed, and `make kind-up` installing it is
   what makes the difference. Confidence: high. It is worth predicting because the symptom looks like
   a broken HPA and is a missing component.
4. Pods reach Ready in under two minutes on the build machine once the images are loaded, dominated by
   MLflow's Alembic migrations against a cold Postgres. Confidence: low. The `startupProbe` allows 150
   seconds before liveness engages, and that number is a guess I would rather see corrected than
   defended.

## Deciding evidence

Empty until the build machine runs it. What is checked here, without a cluster: 23 contract-tier
assertions covering version orderability, agreement with the compose spine's image references,
digest-pinning per record 018, requests and limits on every component, HPA bounds that can actually
scale, a named ingress class, the credential keys existing in `.env.example`, no `Secret` rendered by
any template, and the kind config publishing the ports an Ingress needs.

## What would change my mind

If prediction 2 fails in a way a values change cannot fix — if a non-root Postgres on a PVC needs an
init container to chown the volume, which is what several charts in the wild do — then the honest
answer is to add it and say why, not to quietly run as root and leave record 017's non-root claim
looking broader than it is.

If `helm lint` finds something the contract tier could have caught, that gap belongs in
`tests/test_chart_templates.py` rather than being fixed and forgotten. The point of a static gate is
that the next occurrence is caught on a laptop.

## Consequences

`charts/` moves from "not started" to built, and `COMPONENTS.md`'s row gains a contract. The chart is
now a dependency of `aml-graph-detection` M5, which deploys onto this cluster, so its values interface
is a seam: renaming a key is a breaking change for a consumer that pins a release.

**What this does not demonstrate.** EKS portability is a property of the chart's structure and nothing
here proves it. `OFFLINE_FIRST.md` schedules a paid rehearsal in week -2 precisely because IRSA, the
ALB controller and the EBS CSI driver are what kind does not emulate. The chart is written to make that
day a configuration change; whether it is remains untested, and `Chart.yaml`'s annotation says so where
a chart repository will show it.
