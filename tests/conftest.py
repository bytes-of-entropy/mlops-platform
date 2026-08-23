"""Shared fixtures. Compose files are parsed as data, never rendered by Docker, so the
whole contract suite runs on a machine with no container runtime installed."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "compose" / "docker-compose.yml"
QUICKSTART_FILE = REPO_ROOT / "compose" / "docker-compose.quickstart.yml"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
ENV_FILE = REPO_ROOT / ".env"

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


DAEMON_PROBE_TIMEOUT_SECONDS = 20

DOCKER_ABSENT = "absent"
DOCKER_STOPPED = "stopped"
DOCKER_READY = "ready"

SKIP_REASONS = {
    DOCKER_ABSENT: "no container runtime on this machine; run on the build machine",
    DOCKER_STOPPED: (
        "docker is installed but its daemon did not answer; start Docker Desktop or dockerd "
        "and re-run"
    ),
}


def classify_docker_state(binary: str | None, probe_exit_code: int | None) -> str:
    """Turn what we observed into one of three states.

    Separated from the probe so the classification is testable without a daemon to start and
    stop. ``probe_exit_code`` is ``None`` when the probe could not be run or did not return.
    """
    if binary is None:
        return DOCKER_ABSENT
    if probe_exit_code != 0:
        return DOCKER_STOPPED
    return DOCKER_READY


def probe_docker() -> str:
    """Whether Docker can actually run something, which is not the same as being installed.

    ``shutil.which`` finds the client. The client is a thin thing that talks to a daemon over a
    socket, and on a developer machine the usual state is installed-but-not-running -- so a
    presence check marks the integration tests as runnable and they then fail on a connection
    error, which reads like a broken repository rather than a stopped service.

    ``docker info`` is the cheapest command that requires the daemon to answer.
    """
    binary = shutil.which("docker")
    if binary is None:
        return classify_docker_state(None, None)
    try:
        completed = subprocess.run(  # noqa: S603 -- fixed argv, resolved path, no shell
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=DAEMON_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a daemon that has not answered in 20 seconds is not one these
        # tests can use, and the distinction between slow and stopped does not change the skip.
        return classify_docker_state(binary, None)
    return classify_docker_state(binary, completed.returncode)


DOCKER_STATE = probe_docker()

requires_docker = pytest.mark.skipif(
    DOCKER_STATE != DOCKER_READY,
    reason=SKIP_REASONS.get(DOCKER_STATE, f"docker is not usable here: {DOCKER_STATE}"),
)


def parse_env_pairs(text: str) -> dict[str, str]:
    """Name/value pairs out of dotenv-shaped text. Comments and blank lines are neither."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        pairs[name.strip()] = value.strip()
    return pairs


def missing_credentials(
    example_text: str, env_text: str | None, environ: Mapping[str, str]
) -> frozenset[str]:
    """Which variables the spine would refuse to start without.

    Required is read out of the example file rather than restated here, so a variable added to the
    spine cannot be remembered in one place and forgotten in the other. Satisfied means a
    non-empty value in ``.env`` *or* in the process environment, because compose reads both and
    exporting the variables instead of writing them to a file is a supported choice rather than a
    workaround -- a guard that only looked for the file would skip on a machine that was in fact
    ready.
    """
    required = set(parse_env_pairs(example_text))
    satisfied = {name for name, value in parse_env_pairs(env_text or "").items() if value}
    satisfied |= {name for name, value in environ.items() if value.strip()}
    return frozenset(required - satisfied)


def credentials_skip_reason(missing: frozenset[str]) -> str:
    """Name the variables, because "not configured" is not an instruction."""
    return (
        "the compose spine has no credentials to start with: "
        + ", ".join(sorted(missing))
        + " unset in both .env and the environment. Copy .env.example to .env and fill it in."
    )


def _read_text_if_present(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


MISSING_CREDENTIALS = missing_credentials(
    _read_text_if_present(ENV_EXAMPLE_FILE) or "",
    _read_text_if_present(ENV_FILE),
    os.environ,
)

# The second precondition, and the one a fresh machine hits after Docker is installed but before
# the credentials exist. Without it those tests attempt a real `up`, compose refuses on an unset
# variable, and three idempotency failures report a broken cycle when the cycle was never run.

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
    """
    sections = [f"{label} failed with exit code {returncode}", "command: " + " ".join(argv)]
    named = {"stderr": stderr, "stdout": stdout, **(extra or {})}
    sections.extend(_report_section(name, body) for name, body in named.items())
    return "\n\n".join(sections)


requires_local_credentials = pytest.mark.skipif(
    bool(MISSING_CREDENTIALS),
    reason=credentials_skip_reason(MISSING_CREDENTIALS),
)
