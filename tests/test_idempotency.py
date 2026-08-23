"""`make down && make up` must be repeatable, and repeatable twice.

This is the integration half of the M0 gate. It needs two things the contract suite does
not -- a container runtime and the local credentials -- and skips, naming which one is
absent, where either is missing. The contract suite next to it covers the properties that
make idempotency possible; this covers whether it actually holds.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.conftest import (
    REPO_ROOT,
    describe_process,
    requires_docker,
    requires_local_credentials,
)

# --project-directory, exactly as both entrypoints pass it: an integration suite that resolved
# .env and the bind mounts differently from `make up` would be testing a stack nobody runs.
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    ".",
    "-f",
    "compose/docker-compose.yml",
    "-f",
    "compose/docker-compose.quickstart.yml",
]
TIMEOUT_S = 600
#: Enough log to hold a start-up objection, short of replaying the whole boot.
LOG_TAIL_LINES = 30

pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is built in this module, no shell, no input
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=False,
    )


def diagnostics() -> dict[str, str]:
    """What the stack looked like at the moment it refused.

    A failed `up --wait` almost never says why: the reason is a container that started,
    logged its objection and went unhealthy. `role "x" does not exist` from a Postgres whose
    volume was initialised under a different POSTGRES_USER is exactly that shape -- invisible
    in compose's own output, unmissable in the service log.
    """
    gathered: dict[str, str] = {}
    for name, argv in (
        ("compose ps", [*COMPOSE, "ps", "--all"]),
        ("service logs", [*COMPOSE, "logs", "--tail", str(LOG_TAIL_LINES), "--no-color"]),
    ):
        try:
            probe = run(argv)
        except (OSError, subprocess.SubprocessError) as error:  # gathering must never mask
            gathered[name] = f"could not be gathered: {error!r}"
            continue
        gathered[name] = probe.stdout or probe.stderr
    return gathered


def succeeded(label: str, argv: list[str], result: subprocess.CompletedProcess[str]) -> None:
    """Assert the call worked, and if it did not, say everything about how it failed."""
    if result.returncode == 0:
        return
    raise AssertionError(
        describe_process(
            label, argv, result.returncode, result.stdout, result.stderr, diagnostics()
        )
    )


def healthy_services() -> set[str]:
    argv = [*COMPOSE, "ps", "--format", "json"]
    result = run(argv)
    succeeded("compose ps", argv, result)
    states: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("Health") in {"healthy", ""} and row.get("State") == "running":
            states.add(row["Service"])
    return states


def bring_up() -> set[str]:
    result = run([*COMPOSE, "up", "-d", "--wait"])
    assert result.returncode == 0, f"compose up failed:\n{result.stderr}"
    return healthy_services()


def bring_down() -> None:
    result = run([*COMPOSE, "down", "--remove-orphans"])
    assert result.returncode == 0, f"compose down failed:\n{result.stderr}"


def test_down_then_up_reaches_the_same_healthy_set() -> None:
    """The second cycle must land on the same services, not a subset that happens to work."""
    first = bring_up()
    assert first, "nothing came up healthy on the first cycle"
    bring_down()
    second = bring_up()
    try:
        assert second == first, (
            f"second cycle differs: only-first={first - second}, only-second={second - first}"
        )
    finally:
        bring_down()


def test_up_is_safe_to_run_twice_without_a_down() -> None:
    """A repeated `up` is what happens in practice; it must be a no-op, not a conflict."""
    first = bring_up()
    second = bring_up()
    try:
        assert second == first
    finally:
        bring_down()


def test_state_survives_down_and_up() -> None:
    """`make down` keeps volumes, so an object written before it is readable after it."""
    bring_up()
    try:
        write_argv = [
            *COMPOSE,
            "exec",
            "-T",
            "minio",
            "sh",
            "-lc",
            "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"
            " >/dev/null && mc mb --ignore-existing local/idempotency"
            " && echo persisted | mc pipe local/idempotency/marker",
        ]
        succeeded("minio write", write_argv, run(write_argv))
        bring_down()
        bring_up()
        read_argv = [
            *COMPOSE,
            "exec",
            "-T",
            "minio",
            "sh",
            "-lc",
            "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"
            " >/dev/null && mc cat local/idempotency/marker",
        ]
        read = run(read_argv)
        succeeded("minio read", read_argv, read)
        assert "persisted" in read.stdout
    finally:
        bring_down()
