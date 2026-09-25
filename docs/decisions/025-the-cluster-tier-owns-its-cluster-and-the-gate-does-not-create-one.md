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

## Prediction scored, 2026-08-31: 1 holds for a reason I did not name, and four defects were mine

First run of the cluster tier. Three of seven assertions passed; the other four failed, and **all four
failures were defects in this repository rather than in the chart**. The chart installed and ran.

**Prediction 1 holds — the first failure was in setup, not in the chart — but not where I bet.** I had
narrowed it to the metrics-server JSON patch and then closed that bet by reading the manifest. The real
failure was one line earlier and in the other entrypoint: `make.ps1`'s `kind-up` ran
`$existing = & kind get clusters 2>$null`, and on a machine with no clusters `kind` writes
"No kind clusters found." to stderr and exits 0. Windows PowerShell 5.1 wraps a redirected native
command's stderr in an ErrorRecord, `$ErrorActionPreference = 'Stop'` throws it, and the target died on
its first line — on the exact input the `if` beneath it was written to handle.

That trap is documented in this portfolio already, in a comment in the transfer generator, and I wrote
the redirect anyway. It is now a grep assertion over `make.ps1` rather than a third comment, because
the knowledge existing somewhere had already been shown not to be enough.

**Prediction 2 is scored and did not fire.** The runner reported `.env line endings: LF`, so the
`--from-env-file` carriage-return hazard was absent on this machine. The Secret was created correctly
and Postgres authenticated. The check stays: it costs one line and the failure it watches for is
indistinguishable from a wrong password.

**Prediction 3 cannot be scored, because the load generator never ran.** The three `loadgen` pods went
`Error` then `CrashLoopBackOff` and the HPA read `cpu: 0%/70%` for the full 240 seconds. The cause is
mine and it is useful: the generator's program was assembled with `";".join(...)` around a `def`, and a
compound statement cannot follow a semicolon. It was a `SyntaxError`, so no pod ever made a request.
The test then reported that the Deployment "stayed at 1 replica after 240s of load from 3x4 clients" —
a true sentence about the wrong subject, which is the most expensive kind of test failure there is.

`compile()` on that string costs nothing and runs on a laptop. It is now
`test_the_load_generator_is_valid_python`. Writing a program as a string and never compiling it is the
gap; the semicolon is only how it showed up.

Two smaller defects from the same run, both in the tier rather than the chart:

- **The credential check reported a leak that was the release name.** `POSTGRES_DB=platform` is eight
  characters and a substring of `mlops-platform`, which appears in every label and object name the
  chart renders. The length filter was meant to prevent coincidental matches and eight was not enough;
  it now requires the match to stand alone rather than sit inside a longer identifier. **No credential
  reached the rendered manifest**, which is what the test existed to establish.
- **The bucket check passed and its assertion failed.** The pod printed `bucket present: mlflow` while
  the assertion looked for `bucket present: 'mlflow'` — a `!r` in the script template that `print` does
  not reproduce in its output. Record 015's concern is answered: the initContainer created the bucket
  and S3 confirmed it from inside the pod that needs it.

**One thing is genuinely unexplained and is not being guessed at.** `/health` returned 200 through the
Ingress and `/api/2.0/mlflow/experiments/create` returned 503 seconds later. 503 is what nginx returns
with no ready endpoint *and* what an application can return for itself, and the test recorded only the
status code, so this run cannot say which sent it. `through_the_ingress` now retries three times over
ten seconds and reports the body and the `Server` header, because nginx's 503 is an HTML page and
MLflow's would be JSON. Whether it was a race or a real refusal is what the next run answers.

**Prediction 5 holds.** The Ingress answered `/health` with 200 on the first attempt, routed by the
`Host` header with no DNS involved, so the controller's `hostPort` and the kind config's
`extraPortMappings` do line up. The 503 above is a separate question from whether routing works.

**What this says about the tier, which is this record's subject.** Its own cluster was created and
destroyed cleanly, the port-conflict guard never fired because the operator cluster had been deleted by
its own step, and every failure arrived with pods, events, deployments and HPA state attached — which
is why four defects were diagnosable from one results file without a second run. The design decisions
this record makes held; the code implementing them had four bugs.

## Prediction scored, 2026-08-31 (second run): the tier is green, and 3 is confirmed on first exercise

`7 passed, 0 skipped in 192s`. Every M2 exit criterion the tier covers is now demonstrated on a real
cluster, including the one no previous run had exercised at all.

**Prediction 3 is confirmed, and the timing half of it is falsified in the useful direction.** It said
the HPA would scale but take longer than the 240 seconds allowed, with the deadline as the expected fix.
It scaled inside the budget: the whole module, including cluster creation, the chart install, the
metrics-server wait and the load run, finished in three minutes twelve. So the deadline was never the
problem -- the load generator was, and once it was valid Python the autoscaler behaved exactly as the
chart's CPU *requests* predicted. That is the assertion record 024 said the chart could make and compose
could not, and it is now made.

**The three defects fixed after the first run stayed fixed.** The credential check passes without
reporting the release name, the bucket assertion matches what `print` emits, and the 503 did not recur --
the tracking API answered, so an experiment was created through the Ingress and read back out of
Postgres. That closes the question this record left open: **the 503 was a race, not a refusal.** It has
not reappeared, and the retry with the `Server` header and the in-cluster probe are what would name it
if it does.

**Prediction 1 fires a second time, on a second PowerShell defect, and the pattern is now the finding.**
`make kind-deploy` failed again. The stderr redirect was gone and the cluster created cleanly; the next
line died. `kubectl patch --type=json -p '[{...}]'` cannot be passed from Windows PowerShell 5.1, which
does not preserve embedded double quotes when handing an argument to a native executable, so kubectl
received malformed JSON and the API server answered "the request is invalid". It reads as a bad patch and
was a bad shell -- the same patch, from the tier, through Python's argv, worked.

Twice now the tier has passed while the documented target failed, and both times for a reason belonging
to PowerShell rather than to Kubernetes. That is worth stating as a property of this repository rather
than as two incidents: **the mirror is the least-tested surface here, precisely because the tier
deliberately does not use it.** This record chose that separation and this is its cost, arriving on
schedule. The patch is now a committed file both entrypoints pass by path, which removes the class
rather than the instance.

**What M2 still owes: nothing the tier can show.** The criteria are met. What is unproven is the
documented path -- `make kind-deploy` has never once installed the chart end to end -- and closing that
is a re-run rather than new work.

## Prediction scored, 2026-08-31 (third run): the mirror closes, and prediction 1 is finally spent

`make kind-deploy` installed the chart end to end -- three Deployments Running in 138 seconds -- and the
Ingress answered `status: 200`. M2's criteria are now met by both paths, the tier's and the documented
one, which is what the milestone actually asked for.

**Prediction 1 is scored a third time and is now closed.** It said the first failure would be in cluster
setup rather than in the chart, and it was right three times running, on three different defects: a
stderr redirect, an inline JSON argument, and -- caught by audit rather than by a run -- a namespace
deleted and recreated against its own finalizers. All three were PowerShell, none was Kubernetes, and the
chart was never the subject. The prediction has no remaining content: the setup path is exercised and
green, so there is nothing left for it to be right about.

**What the audit bought, stated plainly because it is the argument for auditing.** The third defect was
never hit by a run. It would have been hit by this one -- `kind-up` reuses an existing cluster, and a
second `kind-deploy` against one is exactly the case that races the finalizers. Fixing it cost an hour of
reading; discovering it would have cost this run and the one after it. Two defects found one-per-run is
what made the audit worth doing, and the audit is what stopped the third from being a fourth run.

**The render assertions ran for the first time: 19 passed.** Ten of those are the synthetic checks that
run anywhere, and nine are the absence claims that needed helm to resolve the conditionals first -- no
Secret rendered, no credential-shaped variable carrying a literal value, no `replicas` beside an HPA,
nothing pulling `Always`, and `$(POSTGRES_PASSWORD)` surviving as those characters rather than being
resolved into the manifest. The split between those two halves is what made them worth trusting on their
first execution, which is the lesson the four tier defects taught.

**M2 is closed at `v0.3.0`.** What it does not include is unchanged and still worth naming: EKS
portability, which the chart's structure supports and nothing here tests, and the GHCR push, which
record 023 sequences after the repository publishes.

## Prediction scored, 2026-09-04: the quote trap recurred, in an argument written after its own audit

`make push` failed on the build machine with

```
template parsing error: template: :1: function "com" not defined
docker image inspect failed with exit code 64
```

The argument was `--format '{{index .Config.Labels "com.docker.compose.service"}}'`. 5.1 dropped the inner
double quotes, docker received `index .Config.Labels com.docker.compose.service`, read `com` as a function
name, and exited 64. **Fourth instance of the class this record exists for, and the second of this exact
variant** -- the first was a `kubectl patch` with inline JSON, fixed by moving the JSON to `--patch-file`.

**It failed closed, by ordering rather than by design.** The check sat before the `docker tag`, so the
target threw and published nothing. Had it sat two lines later the wrong image would have gone out with a
guard that had never run. That is luck, and it is worth writing down as luck.

### The part that matters is the timing, not the trap

That same `push` arm was audited for exactly this trap earlier the same day, before the guard was written.
The audit's conclusion was recorded and was **correct**: "the Go template has no embedded double quotes, so
the argument-handoff trap can't fire either." Hours later an argument with embedded double quotes was added
to the arm that statement was about.

So the failure is not that the class was forgotten. It is that **an audit is a statement about a moment and
was treated as a property of the file.** Five assertions in this repository hold parts of this class
textually; none covered embedded quotes, because that instance had been handled by moving JSON out of the
argument rather than by asserting the shape. A defect fixed by restructuring leaves nothing behind that
notices the next one.

`test_no_native_argument_in_make_ps1_carries_an_embedded_double_quote` now holds it: every single-quoted
literal on a line naming a native executable, asserted to contain no double quote. Checked against both
known instances before being trusted -- the 2026-09-04 template and the earlier `kubectl patch` JSON are
both caught, and the replacement is clean.

The fix is the same shape as the first instance: ask for `{{json .Config.Labels}}`, which needs no inner
quotes, and parse it in PowerShell, where quoting is the language's problem rather than the handoff's.

### A second defect in the same run, of the same shape as one already fixed

The batch runner printed `git status --porcelain`, showed six modified `sbom/*.known.txt` advisory
baselines, and ran every later step anyway -- four builds and a publish against a tree that did not match
the commit those steps claimed to be exercising.

That is the *same defect* as the remote check sitting one line below it in the same function, which had
already been found and fixed for exactly this reason: it reported without deciding. Fixing one instance
taught nothing about its neighbour. Both now decide, and the runner refuses a dirty tree unless given
`--allow-dirty`, mirroring `make-transfer.ps1`.

**Twice in one run, the same lesson from two directions:** a check that produces output rather than a
verdict is not a check, and a fix applied to an instance does not protect the class.

## Claim tested, 2026-09-25: the route was fine, the question was asked too early

Prediction 5 said nothing would be wrong with the ingress that a Host header does not fix, and closed
with a line about diagnosis: "A 404 from nginx and a connection refused mean different things here,
and the tier reports which." The 11:45 run produced a third answer that line did not enumerate, from
the one probe that is not part of the tier.

The runner's own Ingress step fired a single `curl` the instant `make kind-deploy` returned, and got
`503`. It asserted on that and exited 1. Minutes later, on a cluster it built itself, the tier passed
the same route assertion seven ways. So the route was never broken. `helm --wait` returns when three
Deployments report Available, and nginx answers 503 until it has picked up their endpoints, which
means a single unretried request measures how fast the controller reloaded rather than whether the
chart is reachable.

**The suite already knew.** `through_the_ingress` allows three attempts over ten seconds and its
docstring records why: "The first real run got 200 from `/health` and 503 from the API seconds later."
The runner's probe was written later, strictly, and without that budget -- so the two disagreed about
a fact the repository had already established, and the stricter one was wrong. A probe outside the
suite that is stricter than the suite is not a stronger check, only a noisier one. It now allows the
same three attempts over ten seconds, and reports which attempt answered, because a 200 on the second
is evidence about the controller worth keeping rather than a detail to smooth over.

Third instance in this record of a check that only looked like one, and the first of this variant. The
two before it reported without deciding. This one decided, at a moment when the only honest answer was
"not yet" -- **a sound verdict at the wrong time, which is indistinguishable from a wrong verdict to
everyone downstream of it.**

### The diagnostic added with the fix was itself empty

The fix printed the `Server` header alongside the status, on the argument that 503 from nginx is an
empty upstream while 503 from gunicorn is MLflow refusing for itself. The 12:38 run answered
`status 200, served by nothing that named itself`: **this controller sends no `Server` header at
all**, because ingress-nginx clears it when server tokens are off. The discriminator could not
discriminate, and it took a passing run to show it, since a header absent on a 200 is absent on a 503
for the same reason.

The body does discriminate -- nginx serves an HTML error page, MLflow serves JSON -- and the tier's
helper has always reported it, which is the half of that helper that was actually doing the work. The
probe now prints the first 300 bytes of any non-200 and keeps the header line for a controller that
does send one. Verified against a local stub on both branches: three attempts and exit 1 with the HTML
body printed on a 503, one attempt and exit 0 on a 200.

Worth stating because it generalises: **a diagnostic shipped with a fix is unverified until a failure
prints it.** This one shipped in the same commit as the retry, read plausibly, and was inert. The
retry itself is still unexercised on its interesting branch -- the 12:38 run answered 200 on the first
attempt -- and the evidence that the race exists remains the 11:45 failure rather than anything this
run shows.

### What it says about this record's division

Nothing against it. The failing probe was the runner's, against the operator's cluster; the tier,
which owns its own, was green in the same run and reported 7 passed in 194 seconds. The division held
and the cost stayed where this record predicted it would. What the episode adds is that the operator's
cluster is probed by something outside the suite, and that probe has no tests of its own -- it is
shell in the runner, verified by running it. That is acceptable for one request against one route, and
it is the reason the budget was copied from the suite rather than chosen afresh.

## Scored by the next run, 2026-09-25 (15:28): the race recurred, and the diagnostic printed

```
attempt 1 of 3: status 503, served by nothing that named itself
  first 300 bytes of what answered: <html> <head><title>503 Service Temporarily Unavailable</title></head>
  <body> <center><h1>503 Service Temporarily Unavailable</h1></center> <hr><center>nginx</center> </body> </html>
attempt 2 of 3: status 200, served by nothing that named itself
-- exit 0, 6s
```

Two claims in the section above were written as unverified, and this run settled both within six
seconds of each other.

**The race is not rare.** It fired at 11:45, did not fire at 12:38, and fired again at 15:28 -- twice in
three runs. A single-attempt probe would therefore have failed this run too, on a cluster whose own tier
then reported 7 passed in 196 seconds. The window is narrow rather than unreliable: `kubectl` showed the
three pods at 60s old when `helm --wait` returned, and the route answered on the next attempt five
seconds later, so the gap between Deployments Available and endpoints picked up is measured in seconds
and a single request lands inside it about as often as it misses.

**The body was the discriminator, exactly where the header was not.** `<hr><center>nginx</center>` is
the controller's own error page, so the 503 was an empty upstream and not MLflow refusing for itself --
the distinction the `Server` header was added to draw and could not, arriving empty here on the 503 as
it had on the 200. The paragraph above says a diagnostic shipped with a fix is unverified until a
failure prints it. That is now retired by its own evidence, one run later, which is the shortest such
interval in this record: the previous instances took days.

Nothing else in the run moved. 392 passed, 10 skipped, 7 deselected at both gates, `sbom/ is unchanged.`
at both comparisons, the six baseline counts as committed, and every one of the 26 steps at exit 0.
