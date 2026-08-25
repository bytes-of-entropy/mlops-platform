"""The ordered checks, as pure functions over what was observed.

Ordered because each one is only meaningful when the one before it passed: there is nothing to say
about a volume on a machine whose daemon is stopped. Everything a check needs is passed in, so the
whole pipeline can be exercised on a laptop with no runtime, including the failures, which is the
half that is otherwise only ever seen in production.

Three statuses, not two. ``UNKNOWN`` exists because the honest answer to "were these credentials
the ones this volume was built with" is sometimes *cannot tell*, because a volume created before the
fingerprint existed carries no record, and reporting that as OK is the exact class of bug this
package was written to stop. It does not fail the run: a pre-existing volume is legitimate, and
blocking ``up`` on it would push a reviewer toward the one command that destroys their data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from preflight.credentials import (
    FIRST_INIT,
    READ_TIMING,
    credentials_skip_reason,
    effective_value,
    fingerprint,
    missing_credentials,
    parse_env_pairs,
)
from preflight.runtime import (
    DOCKER_READY,
    SKIP_REASONS,
    VOLUME_EMPTY,
    VOLUME_FINGERPRINTED,
    VOLUME_UNFINGERPRINTED,
    VolumeState,
)

OK = "OK"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

RUNTIME = "container runtime"
CREDENTIALS = "credentials"
POSTGRES_VOLUME = "postgres volume"

#: The order they run in, and the inventory the renderer needs to say what went unchecked.
ORDER = (RUNTIME, CREDENTIALS, POSTGRES_VOLUME)


@dataclass(frozen=True)
class Result:
    """One check, its verdict, and enough detail to act on without asking anyone."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class Inputs:
    """What the checks read. Injected rather than gathered, so a test can construct any state.

    ``read_volume`` is a callable and not a value because it starts a container: on a machine with
    no daemon, or with no credentials to render the compose file with, it must not be called at
    all.
    """

    docker_state: str
    example_text: str
    env_text: str | None
    environ: Mapping[str, str]
    read_volume: Callable[[], VolumeState]


def check_runtime(docker_state: str) -> Result:
    if docker_state == DOCKER_READY:
        return Result(RUNTIME, OK, "the daemon answered")
    return Result(RUNTIME, FAIL, SKIP_REASONS.get(docker_state, f"unusable: {docker_state}"))


def check_credentials(
    example_text: str, env_text: str | None, environ: Mapping[str, str]
) -> Result:
    """Every variable the example declares has a non-empty value somewhere compose will look."""
    missing = missing_credentials(example_text, env_text, environ)
    if missing:
        return Result(CREDENTIALS, FAIL, credentials_skip_reason(missing))

    declared = list(parse_env_pairs(example_text))
    exported = sum(1 for name in declared if environ.get(name, "").strip())
    source = "the environment" if exported == len(declared) else ".env"
    if 0 < exported < len(declared):
        source = f".env, with {exported} overridden by the environment"
    return Result(CREDENTIALS, OK, f"{len(declared)} variables set from {source}")


def check_postgres_volume(volume: VolumeState, user: str, password: str) -> Result:
    """Do the credentials in hand match the ones the data directory was built with?

    This is the failure that costs the most to diagnose from the outside: compose reports an
    unhealthy container, the reason is one line in a service log, and the cause was a file edited
    days earlier. It is also the failure a fresh clone cannot clear, because the volume name comes
    from the directory name and re-cloning into the same directory finds the same volume.
    """
    if volume.kind == VOLUME_EMPTY:
        return Result(
            POSTGRES_VOLUME,
            OK,
            "no data directory yet, so the next start initialises one with the values in hand",
        )

    if volume.kind == VOLUME_FINGERPRINTED:
        if volume.digest == fingerprint(volume.salt, user, password):
            return Result(
                POSTGRES_VOLUME, OK, "initialised with the POSTGRES_USER and password in hand"
            )
        return Result(
            POSTGRES_VOLUME,
            FAIL,
            "this volume was initialised with a different POSTGRES_USER or POSTGRES_PASSWORD, and "
            + READ_TIMING["POSTGRES_USER"].consequence
            + ". Either restore the values it was created with, or run `make reset` to discard the "
            "volume and start over, which also discards the MLflow runs and Airflow history "
            "inside it",
        )

    if volume.kind == VOLUME_UNFINGERPRINTED:
        return Result(
            POSTGRES_VOLUME,
            UNKNOWN,
            "cannot verify: this volume predates the fingerprint, so it holds no record of the "
            "credentials it was built with. If the stack starts, it matched; if Postgres or MLflow "
            "goes unhealthy, this is the first thing to suspect",
        )

    return Result(POSTGRES_VOLUME, UNKNOWN, f"cannot verify: {volume.detail}")


def run(inputs: Inputs) -> list[Result]:
    """Every check in order, stopping at the first failure, and saying what it stopped before.

    A short list of green lines reads as a clean bill of health. Naming the checks that never ran
    is the difference between "nothing is wrong" and "nothing else was looked at".
    """
    results = [check_runtime(inputs.docker_state)]
    if results[-1].status != FAIL:
        results.append(check_credentials(inputs.example_text, inputs.env_text, inputs.environ))
    if results[-1].status != FAIL:
        user = effective_value("POSTGRES_USER", inputs.env_text, inputs.environ)
        password = effective_value("POSTGRES_PASSWORD", inputs.env_text, inputs.environ)
        results.append(check_postgres_volume(inputs.read_volume(), user, password))

    stopped_at = results[-1]
    checked = {result.name for result in results}
    results.extend(
        Result(name, UNKNOWN, f"not checked: {stopped_at.name} failed first")
        for name in ORDER
        if name not in checked
    )
    return results


def first_init_variables() -> list[str]:
    """The variables a kept volume pins, for anything that needs to name them."""
    return sorted(name for name, entry in READ_TIMING.items() if entry.timing == FIRST_INIT)
