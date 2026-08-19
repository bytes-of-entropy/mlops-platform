"""Shared fixtures. Compose files are parsed as data, never rendered by Docker, so the
whole contract suite runs on a machine with no container runtime installed."""

from __future__ import annotations

import shutil
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


def docker_available() -> bool:
    return shutil.which("docker") is not None


requires_docker = pytest.mark.skipif(
    not docker_available(),
    reason="no container runtime on this machine; run on the build machine",
)
