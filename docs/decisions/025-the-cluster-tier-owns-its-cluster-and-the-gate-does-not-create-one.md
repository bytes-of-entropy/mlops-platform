# 025: The cluster tier owns its own cluster, and the gate does not create one

- **Date:** 2026-08-31
- **Status:** accepted
- **Component:** `tests/`, `Makefile`
- **Milestone:** M2
- **Extends:** record 006 (preconditions skip by name), record 016 (a failed service gets its own
  section in the report), record 024 (the chart covers the tracking core)

## Context

Record 024 decided what the chart is. This one decides how it gets tested, which turned out to carry
more decisions than expected, because a Kubernetes cluster differs from a compose project in three ways
that each force a choice: it takes minutes rather than seconds to create, it binds host ports, and it is
the first thing in this repository that a `make` target can create and leave behind.

The compose tier already answered the shape of this problem once. `tests/stackops.py` runs under its own
compose project so a volume left behind by a by-hand session cannot decide whether the suite passes. The
question was how much of that argument transfers.

## Decision

**The tier creates its own cluster, `mlops-platform-tests`, and destroys it.** The argument is
`stackops`' argument with a cluster in place of a volume: a cluster an operator left running, installed
from a chart two commits old, must not be able to decide whether the suite passes. The cost is real and
worth naming — the tier never exercises `make kind-deploy` itself, which is the target a reader would
run — and it is the same cost the compose tier already pays, which is why `test_compose_paths.py` exists.
The runner covers the target separately, so the documented path and the asserted path are both walked on
the build machine even though neither test walks both.

**Only one of the two clusters can exist at a time, and that is a host-port fact rather than a design
one.** Both use `charts/kind-cluster.yaml`, which publishes 80 and 443 so an Ingress is reachable, and
the second `kind create` to want port 80 fails on the bind. Separate names keep the clusters from
sharing state; nothing can make them share a port. So the tier refuses up front and names the other
cluster, and the runner deletes the operator's cluster in a step of its own rather than in a comment.
This was found by reasoning about the step order rather than by running it, which is the only reason it
is a paragraph here instead of a failed run.

**`make test` excludes the cluster tier; `make test-cluster` is how you ask for it.** `make test` is
what `make check` runs, what the pre-commit path runs, and what every fresh clone runs to prove itself.
A gate that creates a Kubernetes cluster, pulls a node image and an ingress controller, and takes
minutes is a gate people stop running. Excluded by selection rather than left to skip, so the count each
target prints is a count of tests that ran — the same reason record 006 gives for naming skips rather
than tolerating them.

**The tier installs the default values, not the quickstart file.** The quickstart exists for a
reviewer's laptop; the default values are what `kind-deploy` installs and what a claim in the README
rests on. A tier that only ever installed the lighter file would leave the shipped configuration
installed nowhere.

**The load generator is the image already on the node.** An HPA that scales needs real CPU in the
request path, and a generator needs an HTTP client and a loop. The built MLflow image has Python, is
already loaded, and is already pinned; a second image would be another reference to pin and bump for six
lines of code. It hits an experiment search rather than `/health`, because `/health` returns a constant
and a server can answer it out of almost no CPU, while a search goes through the connection pool to
Postgres — which is the work the request path actually does.

**Nothing in the tier asserts on a return code.** Every failure routes through `Cluster.check`, which
raises with the command, the exit code, both streams, and the pods, events, deployments and HPA gathered
afterwards. Record 016 established that for compose; the rule that enforced it named `stackops.py`
explicitly, and a second helper arriving is exactly what that rule was written for, so the check now
globs `tests/*ops.py`.

## Prediction (recorded before the evidence)

The build machine has not run any of this. Written now because a prediction written after the results
is not a prediction.

1. **The first failure will be in cluster setup, not in the chart.** Confidence: moderate, and lower
   than when this was first written. The chart has had two static passes and one real defect removed;
   `kind-up` had none, and it installs two third-party manifests by URL, patches one by JSON path, and
   waits on both. The specific bet was the metrics-server patch — `/spec/template/spec/containers/0/args/-`
   assumes an `args` array on container 0, and an `add` whose parent is absent fails — so it was checked
   rather than left as a prediction: v0.9.0's container 0 is `metrics-server` and it does carry `args`,
   five of them. That bet is settled and the patch is sound. What remains unverified is the *waiting*:
   two `wait --for=condition=available` calls with a 300-second budget each, on a control plane that is
   also running everything else.
2. **`kubectl create secret --from-env-file` handles the build machine's `.env` correctly.** Confidence:
   low, and this is the one where I would rather be wrong cheaply than right expensively. If the file
   has CRLF endings and this kubectl does not strip them, every value gains a trailing `\r` and Postgres
   authentication fails in a way indistinguishable from a wrong password. The runner now reports the
   file's line endings for exactly this reason, so the evidence will be present whichever way it goes.
3. **The HPA scales, and it takes longer than the 240 seconds allowed.** Confidence: low on the timing,
   moderate on eventually scaling. Three pods of four threads against a 250m CPU request should clear a
   70% target easily, but metrics-server's first scrape window plus the HPA's 15-second control loop plus
   a `scaleDown` stabilisation of 300 seconds are three delays I have not measured together. If it fails,
   I expect it to fail on the deadline rather than on the utilisation, and the fix is the deadline.
4. **The bucket check passes and proves less than it looks like it proves.** Confidence: high on passing.
   The initContainer runs the same script compose already runs, against the same MinIO image; what is new
   is only where it runs. Worth predicting because a pass here should not be read as evidence that the
   initContainer *approach* is better than the hook Job it replaced — that argument is record 015's and
   this run does not test it.
5. **Nothing will be wrong with the ingress that a Host header does not fix.** Confidence: moderate,
   and better founded than it started. Reading the pinned manifest rather than trusting kind's guide
   turned up that `controller-v1.15.1` selects only on `kubernetes.io/os` and reaches the host through
   `hostPort` 80 and 443 — the `ingress-ready` label this repository's kind config sets is not required
   by it, and three places here said it was. So the pairing that actually has to hold is the
   controller's `hostPort` against the config's `extraPortMappings`, and both are 80 and 443. What is
   still unrun is whether a single-node kind cluster schedules that controller at all. A 404 from nginx
   and a connection refused mean different things here, and the tier reports which.

## Deciding evidence

Empty until the build machine runs it. What is settled without a cluster: 52 contract-tier assertions,
three of which did not exist yesterday. One of those three found a real defect before any
cluster saw it: mlflow.yaml was applying its container security context to the pod, where two of its
fields do not exist.

## What would change my mind

If prediction 1 is right and cluster setup is where the time goes, the honest response is not to make
`kind-up` cleverer. It is to pin the two add-on manifests the way every image in this repository is
pinned — by digest or by a vendored copy — because a manifest fetched from a URL at deploy time is the
one unpinned input left in this repository, and it is being fetched from a project that reorganises its
manifests between minor versions.

If the tier's own cluster turns out to cost more than it buys — if eight minutes per run means it gets
run once and then skipped — then the right answer is to reverse this record and test against the
operator's cluster with an explicit refusal when its release does not match the working tree, rather than
to keep a tier nobody runs. That reversal is cheap; a tier that is green because nobody ran it is not.

## Consequences

`make test` and `make test-cluster` are now different questions, and CI asks the first one. The third
tier means "zero skips" needs qualifying whenever it is claimed: it is the pass condition for a tier
selected on a machine that can run it, and the cluster tier is selected only on the build machine.

The `cluster` marker is the second precondition in this repository that is deliberately absent from
`preflight.checks.ORDER`. `make doctor` answers whether this machine can start the compose spine, and
the spine needs none of kind, kubectl or helm. Widening the doctor to cover the cluster would make it
refuse on machines where everything it was written to check is fine.
