# 006 — A missing precondition skips with its name; it does not fail as the thing it blocks

- **Date:** 2026-08-23
- **Status:** accepted
- **Component:** `tests/`
- **Milestone:** r3-m0

## Context

On the build machine, in a perfectly reasonable order — install Docker, then run the gate — the
three idempotency tests failed. Not because idempotency is broken; because `.env` did not exist
yet. Compose refuses to render a file with an unset interpolation, so `up` returned non-zero, and
the assertion that reported it says `compose up failed`. The message underneath was accurate and
the test name on top of it was not: what the reader sees is
`test_down_then_up_reaches_the_same_healthy_set FAILED`, which describes a property of this
repository, on a machine where that property was never exercised.

The repository already had the right pattern one layer down. `probe_docker` exists because
installed is not the same as usable: a presence check would mark the tier runnable and let it fail
on a connection error, which reads like a broken repository rather than a stopped daemon. The
credentials are the same shape one step along — a daemon that answers is not the same as a spine
that can start — and nothing was checking for them.

The ordering that exposed it is not a mistake to correct in a runbook. Docker before credentials
and credentials before Docker are both sensible, and a suite that only works in one of the two
orders is a suite with an undocumented prerequisite.

## Decision

`tests/test_idempotency.py` gates on two preconditions instead of one:
`pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]`.

`requires_local_credentials` reads the *required* set out of `.env.example` rather than restating
the eight names in test code, so a variable added to the spine cannot be remembered in one place
and forgotten in the other. It treats a variable as satisfied by a non-empty value in `.env` **or**
in the process environment, because compose reads both and the export-instead-of-file route is a
supported choice — a guard that only looked for the file would skip on a machine that was in fact
ready, which is the failure mode that matters most here, since a wrong skip looks exactly like a
pass.

The skip reason names every missing variable and what to do, not just the first one, so the fix is
one round trip rather than eight.

`tests/test_local_credentials.py` tests the guard the way `tests/test_docker_probe.py` tests the
other one: the classification is a pure function of three inputs, so it is checked without
creating or deleting a real `.env`. Two of its assertions are about `.env.example` being a
trustworthy source — every variable the compose files interpolate appears in it, and it names
nothing the compose files do not use. Those are the only facts the guard depends on.

## Alternative rejected

**Leave it failing, and fix the runbook's step order.** Cheapest, and it has some merit: a loud
failure is not the worst outcome. Rejected because the failure names the wrong thing. Someone
reading `test_state_survives_down_and_up FAILED` on a fresh machine has been told the repository's
central claim is broken, and the true statement — "this machine has no credentials yet" — is four
lines further down in captured stderr. Documentation cannot fix a test that lies about its own
subject.

**Deselect the integration tier from the gate by default** (`-m "not integration"` in `addopts`).
This would also have avoided the failure, by never running those tests. Rejected as the wrong
trade in this repository: the tier has never been green anywhere, and the machine where it becomes
runnable is precisely the machine where the gate would then have stopped running it. Opt-in
coverage on the one machine that can provide it is coverage nobody gets.

**Make the gate itself depend on `.env`.** Rejected: `lint`, `hooks` and the whole contract tier
have no business requiring credentials to exist, and coupling them to a secret would make a
green gate impossible in CI, which is the environment the contract tier was designed for.

**Hardcode the eight variable names in the guard.** Simpler to read, and wrong within one commit
of the spine gaining a ninth. The example file is already the published contract for what a
reviewer must fill in; making it the machine-readable one too costs a five-line parser.

## Prediction (recorded before the evidence)

I expect twelve new test items and no change to any existing assertion: 54 passed / 8 skipped on
this machine, up from 42 / 8.

I expect three counts on the build machine, depending on where it is in the runbook:

| State | Expect |
| --- | --- |
| Docker not installed | 54 passed, 8 skipped |
| Docker ready, no `.env` yet | 59 passed, 3 skipped — and the three skips say `MINIO_ROOT_USER, …` |
| Docker ready, `.env` filled in | 62 passed, 0 skipped |

The middle row is the one this record exists for. It was three failures before this change.

## Deciding evidence

Measured here: **54 passed, 8 skipped**, matching the prediction, with the eight skips still
reporting the Docker reason because Docker is the precondition missing on this machine. The guard's
computed state on this machine is all eight variables, which is the same count the runbook asks a
reviewer to fill in — derived, not copied.

The twelve new tests cover the classification directly: a value present but empty does not count,
a variable exported into the environment does count, a default already filled in the example needs
nothing added, and every missing name reaches the reason string.

Not measured here: the middle row. This machine cannot produce a Docker-ready state, so the counts
for the two Docker-ready rows are derived from which markers apply, not observed. Step 7 of the
build-machine sequence is what settles them.

## What would change my mind

If a third precondition appears — a port already bound, a WSL2 memory limit too small for the
quickstart envelope — then three separate `skipif` markers stop being the right shape and this
becomes one probe returning a state, the way `probe_docker` already does for its three outcomes.

If a wrong skip is ever observed — the tier skipping on a machine that could have run it — then
the satisfied-set logic is too permissive and the guard should verify by asking compose
(`config --quiet`) rather than by reading files.

## Consequences

A fresh machine now gets a named instruction instead of a false failure, and the instruction is
generated from the file the reviewer is told to copy.

The cost is a skip where there used to be a failure, and a skip is quieter. That is why step 7 of
the build-machine sequence requires **0 skipped** rather than "no failures": on the machine that
has both preconditions, any skip at all is now a defect in the guard rather than a property of the
machine.
