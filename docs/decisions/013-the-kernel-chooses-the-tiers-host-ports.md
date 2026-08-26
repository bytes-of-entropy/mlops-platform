# 013: Let the kernel choose the integration tier's host ports

- **Date:** 2026-08-24
- **Status:** accepted
- **Component:** `compose/`
- **Milestone:** M0

## Context

A compose project name isolates containers, networks and volumes. It does not isolate published host
ports, and nothing in the file said so. While the compose file published fixed numbers, the
integration tier and a stack brought up by hand were competing for the same six ports on the same
machine, so whichever bound second failed.

Every failure in the first full-profile run came from that, and none of them said so. The visible
error was `Bind for 0.0.0.0:7077 failed: port is already allocated`, reported under test names about
idempotency and smoke: six tests away from the cause, naming behaviour that was never exercised. A
Spark master crash came with them, on an endpoint the aborted network programming never finished
creating, which read as a seventh independent defect and was a consequence of the first.

This record lands a day after the code it explains, in violation of the same-commit rule. Saying so
is the point: the rule exists because a record written afterwards can be tidied to fit the outcome.
What protects this one is not its date but that the outcome does not exist yet. The build machine has
not run the tier since the change, so the prediction below is still unsettled at the time of writing.

## Decision

The host half of every published mapping is a variable whose default is the number it has always
been, so `make up` publishes exactly what it published before. The tier sets all six to `0`, which
asks Docker for a free port at bind time.

Two checks come with it. A contract test rejects a literal host port anywhere in the file, because
putting one back reintroduces a bind failure that surfaces six tests from its cause. And the
required-variable set the credentials guard reads no longer counts a defaulted interpolation: only a
bare or `:?` form can make compose refuse to render, so demanding a published port number of a fresh
machine would have the guard skip the tier over something it can supply itself.

## Alternative rejected

**Publish nothing from the base file, and add a `docker-compose.dev.yml` that publishes for human
targets.** The stronger design on the merits: the safe state becomes the default, exposing a port
becomes the thing you opt into and therefore the thing you notice, and the tier needs no variables at
all because there is nothing to override. It lost on who pays. A person on a fresh clone would have
to pass a second `-f` to reach a UI, or `make up` would have to carry it and the tier would have to
remember not to, which puts the surprise back one level down. The variable-with-default form leaves
by-hand behaviour byte-identical and confines the change to the tier that needed it. This alternative
is retained as the named fallback if the prediction below fails.

Also rejected: **scan for a free port, then bind it.** It looks like the careful version and it is
the less safe one. Between finding a port free and binding it, anything on the machine can take it,
which trades a collision that happens every time for one that happens sometimes, and a test that
fails sometimes is the worse defect.

## Prediction (recorded before the evidence)

On the build machine's next full-profile run, all six bind failures are gone and the tier starts with
a by-hand stack already up. High confidence: a host port of `0` yielding an ephemeral bind is
documented Docker behaviour, not an inference.

The Spark master's endpoint crash goes with them, because it was downstream of network programming
that aborted mid-way. Moderate confidence only. If it survives, it was never a port problem and needs
its own record.

No assertion should notice the change. Nothing in the suite dials a published port: the two
host-shaped URLs, MinIO's `mc alias` and MLflow's run query, both run inside their own container
through its loopback, and `test_m0_smoke.py` says in a comment that asking from the host would be a
different claim. If that reasoning is wrong, the symptom is a connection refused rather than a bind
failure, and it appears in the same six tests.

## Deciding evidence

Left empty deliberately. The build machine has not run the tier since the change; this section is
filled by the commit that reports what happened, and that commit must not touch the prediction.

## What would change my mind

A host port of `0` not producing an ephemeral bind under Docker Desktop on Windows, or the tier
colliding anyway: then invert the arrangement to the rejected alternative above, base file publishing
nothing and a dev overlay publishing for people.

Separately, the first test that genuinely needs to reach a service from the host. That test would
have to ask `compose port` what was assigned before it could connect, and at that moment the
ephemeral choice stops being free and starts being a lookup every host-side test pays for.

## Consequences

Makes easy: running the tier on a machine that is already running the stack, which is the normal
state of the machine it runs on.

Makes hard: reading a URL off the compose file. For the tier there is no longer a number to read;
`compose ps` prints the mappings and `compose port <service> <container-port>` answers for one
service, and both are in the troubleshooting notes.

Rules out: a literal host port in the compose file, now enforced rather than remembered.
