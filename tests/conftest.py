"""Shared fixtures. Compose files are parsed as data, never rendered by Docker, so the
whole contract suite runs on a machine with no container runtime installed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "compose" / "docker-compose.yml"
QUICKSTART_FILE = REPO_ROOT / "compose" / "docker-compose.quickstart.yml"

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
        # Fixed argv, a path resolved by ``which``, and no shell: nothing here is interpolated.
        completed = subprocess.run(
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
