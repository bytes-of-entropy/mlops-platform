"""The compose spine is a contract, not a convenience.

These assertions are the reproducibility claims this repository makes in its README,
checked mechanically. They run without Docker: the file is parsed as YAML.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.conftest import COMPOSE_FILE, FULL_PROFILE

CREDENTIAL_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|ROOT_USER)$")
INTERPOLATED = re.compile(r"^\$\{[A-Z0-9_]+(:[?-][^}]*)?\}$")

STATEFUL_SERVICES = {"minio", "postgres", "airflow"}


def test_every_image_is_pinned(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        image = service["image"]
        assert ":" in image, f"{name} has no tag; an untagged image is `latest` in disguise"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest", f"{name} is pinned to `latest`, which is not a pin"
        assert not tag.endswith("-latest"), f"{name} tag {tag} is a moving target"


def test_every_service_declares_a_healthcheck(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        assert "healthcheck" in service, (
            f"{name} has no healthcheck, so `up --wait` returns before it is usable "
            "and the quickstart timing claim becomes a guess"
        )


def test_dependencies_wait_for_health_not_start(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        for dependency, spec in (service.get("depends_on") or {}).items():
            assert isinstance(spec, dict), (
                f"{name} depends on {dependency} by list form, which waits for container "
                "start rather than readiness"
            )
            assert spec.get("condition") == "service_healthy", (
                f"{name} -> {dependency} does not wait for health"
            )


def test_stateful_services_use_named_volumes(
    services: dict[str, dict[str, Any]], compose: dict[str, Any]
) -> None:
    declared = set(compose.get("volumes") or {})
    for name in STATEFUL_SERVICES:
        mounts = services[name].get("volumes") or []
        named = [m for m in mounts if not m.startswith(".") and not m.startswith("/")]
        assert named, f"{name} keeps state in the container, so `make down` loses it"
        for mount in named:
            source = mount.split(":", 1)[0]
            assert source in declared, f"{name} mounts undeclared volume {source}"


def test_no_credential_is_a_literal(services: dict[str, dict[str, Any]]) -> None:
    """Every credential-shaped value must be an interpolation, with no default.

    A literal here would be a plaintext secret in a committed file, and a `:-default`
    would be a plaintext secret wearing a fallback.
    """
    for name, service in services.items():
        for key, value in (service.get("environment") or {}).items():
            if not CREDENTIAL_KEY.search(key):
                continue
            assert isinstance(value, str) and INTERPOLATED.match(value), (
                f"{name}.{key} is not a bare interpolation: {value!r}"
            )
            assert ":-" not in value, (
                f"{name}.{key} has a default value, which is a committed credential"
            )


def test_host_bind_mounts_are_read_only(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        for mount in service.get("volumes") or []:
            if not mount.startswith("."):
                continue
            assert mount.endswith(":ro"), (
                f"{name} bind-mounts {mount} writable; a container writing into the "
                "working tree makes `make down && make up` non-idempotent"
            )


def test_restart_policy_declared(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        assert service.get("restart") == "unless-stopped", (
            f"{name} has no restart policy, so a crash looks like a config error"
        )


@pytest.mark.parametrize("name", ["spark-worker-2", "airflow"])
def test_heavy_services_are_behind_the_full_profile(
    services: dict[str, dict[str, Any]], name: str
) -> None:
    assert services[name].get("profiles") == [FULL_PROFILE], (
        f"{name} must be profile-gated or the quickstart envelope cannot hold"
    )


def test_no_literal_secret_anywhere_in_the_file() -> None:
    """The environment check misses `command:` strings; this one does not.

    Any line mentioning a credential must reach it through an interpolation.
    """
    sensitive = ("PASSWORD", "SECRET", "FERNET")
    for number, line in enumerate(COMPOSE_FILE.read_text(encoding="utf-8").splitlines(), start=1):
        if any(token in line for token in sensitive) and "${" not in line:
            pytest.fail(
                f"compose/docker-compose.yml:{number} names a credential inline: {line.strip()}"
            )


#: Credentials that some images act on only when a separate flag tells them to. A variable on
#: the left without every flag on the right is a login that exists in the documentation and
#: nowhere else: the value is passed, the image ignores it, and nothing in the file reads wrong.
CONSUMPTION_FLAGS: dict[str, tuple[str, ...]] = {
    "_AIRFLOW_WWW_USER_USERNAME": ("_AIRFLOW_DB_MIGRATE", "_AIRFLOW_WWW_USER_CREATE"),
    "_AIRFLOW_WWW_USER_PASSWORD": ("_AIRFLOW_DB_MIGRATE", "_AIRFLOW_WWW_USER_CREATE"),
}


def test_a_credential_the_image_was_never_told_to_use_is_not_configuration(
    services: dict[str, dict[str, Any]],
) -> None:
    """Interpolating a credential proves the file reads it, not that the image acts on it.

    Both existing checks on .env.example pass in this case -- the variable is declared and
    it is interpolated -- so the gap is one level deeper than either of them looks. What
    fails without this rule is the login itself, on a machine nobody is watching.
    """
    for name, service in services.items():
        environment = service.get("environment") or {}
        for supplied, required in CONSUMPTION_FLAGS.items():
            if supplied not in environment:
                continue
            for flag in required:
                assert environment.get(flag) == "true", (
                    f"{name} supplies {supplied} but leaves {flag} unset, so the image "
                    "never acts on the value it was given"
                )
