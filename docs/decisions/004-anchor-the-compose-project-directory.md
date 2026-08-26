# 004: The compose project directory is the repository root, passed explicitly

- **Date:** 2026-08-19
- **Status:** accepted
- **Component:** `compose/`
- **Milestone:** M0

## Context

Compose resolves two different things against the *project directory*: the default `.env` file,
and every relative host path in a bind mount. The project directory is not the working directory;
it defaults to the directory holding the first file passed to `-f`. Both entrypoints invoke
`docker compose -f compose/docker-compose.yml`, so that default was `compose/`, while
`.env.example`, `postgres/init/` and `airflow/dags/` all sit at the repository root and the
README tells a reviewer to create `.env` there.

Two failures follow from the one rule, and they fail differently. The `.env` half is loud:
`${MINIO_ROOT_USER:?...}` stops the stack with a message naming a variable that is in fact set,
in a file compose never opened. The bind-mount half is silent: `./postgres/init` resolves to
`compose/postgres/init`, which does not exist, and Docker creates a missing host path as an
empty directory rather than refusing, so Postgres starts, reports healthy, and never runs its
init SQL.

Neither was reachable from the existing suite. Parsing the compose files as data is exactly what
lets the contract tests run with no daemon installed, and path resolution is the daemon's half of
the job. The first machine with Docker on it was the first machine able to find this, and it
found it before `up` had ever been run anywhere.

## Decision

Every compose invocation passes `--project-directory .`, in all three places that build one: the
`Makefile`, its `make.ps1` mirror, and the `COMPOSE` argv in `tests/test_idempotency.py`. The
compose files stay in `compose/`; the paths inside them stay written relative to the repository
root, which is now what they mean.

`tests/test_compose_paths.py` asserts the flag in all three places and, from the data side,
asserts that every relative bind mount exists under the repository root and does *not* also
exist under `compose/`, so the flag stays load-bearing rather than merely present.

## Alternative rejected

Move the compose files to the repository root, where the project directory would default to the
right place with no flag. Fewer moving parts, and it removes the failure by construction.

It loses on the architecture this repository is organised around: one component, one folder. The
compose spine is a component, `compose/` is its folder, and dissolving that folder to satisfy a
path-resolution default trades a structural property for a flag. The weaker variant,
`--env-file .env`, was rejected for a different reason: it fixes only the loud half and leaves
the silent half in place, which is the wrong half to fix.

## Prediction (recorded before the evidence)

I expect `make up-quickstart` on the build machine to start with the root `.env` read, and I
expect `docker compose --project-directory . -f compose/docker-compose.yml config` to print
`postgres/init` as an absolute path under the repository root rather than under `compose/`.

I expect the visible consequence of the old behaviour to be that Postgres came up healthy with
no database created by the init SQL: that is, that the silent half would have gone unnoticed
through the whole M0 gate, because every healthcheck it touches would have passed.

I expect the project-name change to be the only side effect anyone notices: container and volume
prefixes move from `compose-*` to `mlops-platform-*`, since the name derives from the project
directory.

## Deciding evidence

None from a daemon yet; this machine has no container runtime, which is the whole reason the
defect survived to be found by reading. What is measured: the three-place flag check and the
bind-mount resolution check fail on the previous state of the `Makefile` and `make.ps1` and pass
on the current one, and the contract suite still runs with no Docker installed
(36 passed, 3 skipped).

The integration tier settles it, and it runs on the build machine.

## What would change my mind

If `--project-directory .` turns out to break something else that resolves against the project
directory (a profile path, an extends target, an include), then the flag is not the cheap fix
it looks like and moving the compose files to the root becomes the honest answer, folder
architecture notwithstanding.

## Consequences

Makes the README's `cp .env.example .env` true, and makes a mount naming a missing path a red
build instead of an empty directory. Costs a flag that must be repeated in three places, which
is why a test now owns that repetition. A fourth place that builds a compose invocation has to
be added to that test, or it is unchecked, and the test's inventory comment says so.
