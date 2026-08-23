"""Shared fixtures. Compose files are parsed as data, never rendered by Docker, so the
whole contract suite runs on a machine with no container runtime installed.

The preconditions -- is there a daemon, are the credentials set -- are imported from ``preflight``
rather than implemented here. They were implemented here first, and then ``make doctor`` needed the
same two answers: a suite that skipped on its own idea of "configured" while the doctor passed on
another would be two guards disagreeing about one machine. Dependencies point one way only, tests
to preflight, so nothing in that package can be written to suit the suite.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from preflight.credentials import credentials_skip_reason, missing_credentials
from preflight.locations import (
    COMPOSE_FILE,
    ENV_EXAMPLE_FILE,
    ENV_FILE,
    QUICKSTART_FILE,
    REPO_ROOT,
    read_text_if_present,
)
from preflight.runtime import DOCKER_READY, SKIP_REASONS, probe_docker

__all__ = [
    "COMPOSE_FILE",
    "ENV_EXAMPLE_FILE",
    "ENV_FILE",
    "FULL_PROFILE",
    "MAX_REPORT_LINES",
    "QUICKSTART_FILE",
    "REPO_ROOT",
    "describe_process",
    "requires_docker",
    "requires_local_credentials",
]

FULL_PROFILE = "full"


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), f"{path.name} did not parse to a mapping"
    return loaded


@pytest.fixture(scope="session")
def compose() -> dict[str, Any]:
    return _load(COMPOSE_FILE)


@pytest.fixture(scope="session")
def quickstart() -> dict[str, Any]:
    return _load(QUICKSTART_FILE)


@pytest.fixture(scope="session")
def services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(compose["services"])


DOCKER_STATE = probe_docker()

requires_docker = pytest.mark.skipif(
    DOCKER_STATE != DOCKER_READY,
    reason=SKIP_REASONS.get(DOCKER_STATE, f"docker is not usable here: {DOCKER_STATE}"),
)

MISSING_CREDENTIALS = missing_credentials(
    read_text_if_present(ENV_EXAMPLE_FILE) or "",
    read_text_if_present(ENV_FILE),
    os.environ,
)

# The second precondition, and the one a fresh machine hits after Docker is installed but before
# the credentials exist. Without it those tests attempt a real `up`, compose refuses on an unset
# variable, and three idempotency failures report a broken cycle when the cycle was never run.
requires_local_credentials = pytest.mark.skipif(
    bool(MISSING_CREDENTIALS),
    reason=credentials_skip_reason(MISSING_CREDENTIALS),
)

#: Enough of a stream to diagnose from, not so much that pytest's own output becomes the problem.
MAX_REPORT_LINES = 40


def _report_section(name: str, body: str) -> str:
    """One labelled block, tail-first and honest about what it dropped."""
    lines = body.strip().splitlines()
    if not lines:
        return f"{name}: empty"
    kept = lines[-MAX_REPORT_LINES:]
    header = name if len(kept) == len(lines) else f"{name} (last {len(kept)} of {len(lines)})"
    return "\n".join([f"{header}:", *kept])


def describe_process(
    label: str,
    argv: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    extra: Mapping[str, str] | None = None,
) -> str:
    """Everything needed to diagnose a failed subprocess, in the assertion itself.

    An integration failure on a machine that is not this one costs a round trip to ask
    "what did it actually say". Docker Compose splits its output unpredictably -- progress
    and the unhealthy-container line land on stderr in some versions and stdout in others --
    so a report that reads only stderr can be empty at exactly the moment it matters.

    ``extra`` carries what the caller could gather afterwards -- container state, service
    logs -- because the cause of a failed ``up`` is usually inside a container's log rather
    than in the output of the command that started it.

    Stays in the test tier rather than moving into ``preflight`` with the preconditions: this
    writes for someone reading a CI log days later, and the doctor writes for someone standing at
    a prompt with the machine in front of them. One report cannot be terse and exhaustive at once.
    """
    sections = [f"{label} failed with exit code {returncode}", "command: " + " ".join(argv)]
    named = {"stderr": stderr, "stdout": stdout, **(extra or {})}
    sections.extend(_report_section(name, body) for name, body in named.items())
    return "\n\n".join(sections)
