"""`make down && make up` must be repeatable, and repeatable twice.

This is the integration half of the M0 gate. It needs two things the contract suite does
not -- a container runtime and the local credentials -- and skips, naming which one is
absent, where either is missing. The contract suite next to it covers the properties that
make idempotency possible; this covers whether it actually holds.

The stack it exercises is the capped quickstart, deliberately: idempotency is a property of the
smallest shape a reviewer can run, and proving it there proves it on the machine most likely to
be theirs. The full profile is covered by the smoke test beside this one.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_docker, requires_local_credentials
from tests.stackops import QUICKSTART, Stack

pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]

stack = Stack(QUICKSTART)


def test_down_then_up_reaches_the_same_healthy_set() -> None:
    """The second cycle must land on the same services, not a subset that happens to work."""
    first = stack.up()
    assert first, "nothing came up healthy on the first cycle"
    stack.down()
    second = stack.up()
    try:
        assert second == first, (
            f"second cycle differs: only-first={first - second}, only-second={second - first}"
        )
    finally:
        stack.down()


def test_up_is_safe_to_run_twice_without_a_down() -> None:
    """A repeated `up` is what happens in practice; it must be a no-op, not a conflict."""
    first = stack.up()
    second = stack.up()
    try:
        assert second == first
    finally:
        stack.down()


def test_state_survives_down_and_up() -> None:
    """`make down` keeps volumes, so an object written before it is readable after it."""
    stack.up()
    try:
        stack.shell(
            "minio write",
            "minio",
            "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"
            " >/dev/null && mc mb --ignore-existing local/idempotency"
            " && echo persisted | mc pipe local/idempotency/marker",
        )
        stack.down()
        stack.up()
        read = stack.shell(
            "minio read",
            "minio",
            "mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD"
            " >/dev/null && mc cat local/idempotency/marker",
        )
        assert "persisted" in read
    finally:
        stack.down()
