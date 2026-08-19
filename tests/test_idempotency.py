"""`make down && make up` must be repeatable, and repeatable twice.

This is the integration half of the M0 gate and it needs a container runtime, so it is
marked and skipped where there is none. The contract suite next to it covers the
properties that make idempotency possible; this covers whether it actually holds.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.conftest import REPO_ROOT, requires_docker

COMPOSE = [
    "docker",
    "compose",
    "-f",
    "compose/docker-compose.yml",
    "-f",
    "compose/docker-compose.quickstart.yml",
]
TIMEOUT_S = 600

pytestmark = [pytest.mark.integration, requires_docker]


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


def healthy_services() -> set[str]:
    result = run([*COMPOSE, "ps", "--format", "json"])
    assert result.returncode == 0, result.stderr
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
        written = run(
            [
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
        )
        assert written.returncode == 0, written.stderr
        bring_down()
        bring_up()
        read = run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "minio",
                "sh",
                "-lc",
                "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"
                " >/dev/null && mc cat local/idempotency/marker",
            ]
        )
        assert read.returncode == 0, read.stderr
        assert "persisted" in read.stdout
    finally:
        bring_down()
