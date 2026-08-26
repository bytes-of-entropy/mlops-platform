"""The compose spine is a contract, not a convenience.

These assertions are the reproducibility claims this repository makes in its README,
checked mechanically. They run without Docker: the file is parsed as YAML.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.conftest import COMPOSE_FILE, FULL_PROFILE, REPO_ROOT

CREDENTIAL_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|ROOT_USER)$")
INTERPOLATED = re.compile(r"^\$\{[A-Z0-9_]+(:[?-][^}]*)?\}$")
#: A published port's host half: a variable named for the service, with today's number
#: as its default. `"${MLFLOW_HOST_PORT:-5000}:5000"` matches; `"5000:5000"` does not.
PUBLISHED_HOST_PORT = re.compile(r"^\$\{[A-Z0-9_]+:-\d+\}$")

STATEFUL_SERVICES = {"minio", "postgres", "airflow"}

# What each pinned image is known to provide, per image rather than per guess. Only what a
# healthcheck names is listed: this is a record of what was verified, not an inventory. `python`
# for the two python-tagged images because an interpreter is what those images are; `wget` for
# Spark because that image was inspected once and the finding is written on its healthcheck.
IMAGE_PROVIDES: dict[str, frozenset[str]] = {
    "apache/spark": frozenset({"wget"}),
    "minio/minio": frozenset({"mc"}),
    "postgres": frozenset({"pg_isready"}),
    "mlops-platform/mlflow": frozenset({"python"}),
    "apache/airflow": frozenset({"python"}),
}


def test_every_image_is_pinned(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        image = service["image"]
        assert ":" in image, f"{name} has no tag; an untagged image is `latest` in disguise"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest", f"{name} is pinned to `latest`, which is not a pin"
        assert not tag.endswith("-latest"), f"{name} tag {tag} is a moving target"


def completion_waiters(services: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """Map each service to the services gated on it *finishing*, not on it answering.

    One-shot provisioners are the reason this exists. They cannot have a healthcheck, because a
    healthcheck asks whether something is still answering and the answer is deliberately no.
    """
    waiters: dict[str, set[str]] = {}
    for name, service in services.items():
        for dependency, spec in (service.get("depends_on") or {}).items():
            if not isinstance(spec, dict):
                continue
            if spec.get("condition") == "service_completed_successfully":
                waiters.setdefault(str(dependency), set()).add(name)
    return waiters


def test_every_service_is_either_healthchecked_or_waited_for(
    services: dict[str, dict[str, Any]],
) -> None:
    """The generalisation of "every service declares a healthcheck", which this replaces.

    That rule was right about what it was defending, `up --wait` returning before the stack is
    usable, and wrong to assume the only way to defend it is a healthcheck. A one-shot has a
    stronger gate available: something waits for it to *complete*, which a healthcheck cannot
    express. So the requirement is that every service carries one of the two, and the failure
    this catches is a service carrying neither, which is the case that actually breaks `--wait`.
    """
    waiters = completion_waiters(services)
    for name, service in services.items():
        if "healthcheck" in service:
            continue
        assert waiters.get(name), (
            f"{name} declares no healthcheck and nothing waits for it to complete, so `up --wait` "
            "returns before it is either usable or finished, and the quickstart timing claim "
            "becomes a guess"
        )


def test_a_one_shot_service_does_not_restart(services: dict[str, dict[str, Any]]) -> None:
    """A provisioner that restarts never completes, so the condition waiting on it never fires.

    The symptom is not a crash. It is `up --wait` sitting until its timeout and then reporting the
    *consumer* as unhealthy, which is the same misattribution three healthchecks in this file
    already caused once.
    """
    keeps_alive = {"always", "unless-stopped", "on-failure"}
    for name in completion_waiters(services):
        policy = str(services[name].get("restart", "no"))
        assert policy not in keeps_alive, (
            f"{name} is waited on with service_completed_successfully but declares "
            f"restart: {policy}, so it is restarted rather than allowed to finish"
        )


def _healthcheck_binary(test: list[str] | str) -> str:
    """The program a healthcheck actually runs, in either of the forms compose accepts."""
    if isinstance(test, str):
        return test.split()[0]
    form, *rest = test
    assert form in {"CMD", "CMD-SHELL"}, f"unrecognised healthcheck form {form}"
    assert rest, "a healthcheck that declares a form and no command"
    return rest[0] if form == "CMD" else rest[0].split()[0]


def test_a_healthcheck_only_names_a_binary_its_image_provides(
    services: dict[str, dict[str, Any]],
) -> None:
    """A healthcheck is the one command in this file that has to run inside the image.

    Naming a binary the image does not ship costs the whole `--wait` timeout and then reports a
    broken service, which is the most expensive way this file can be wrong: the failure names the
    wrong thing, so it gets read as a bug in whatever that service does rather than as a typo in
    one line of YAML. Same shape as the DAG import rule: a dependency that exists only in the
    mind of whoever wrote the file.
    """
    for name, service in services.items():
        if "healthcheck" not in service:
            # A one-shot has no healthcheck to check a binary against. What it runs instead is
            # gated by test_every_service_is_either_healthchecked_or_waited_for.
            continue
        image = service["image"]
        known = next(
            (binaries for prefix, binaries in IMAGE_PROVIDES.items() if image.startswith(prefix)),
            None,
        )
        assert known is not None, (
            f"{name} runs {image}, which no IMAGE_PROVIDES entry covers, so its healthcheck "
            "is unchecked; add the image and what was verified to be in it"
        )
        binary = _healthcheck_binary(service["healthcheck"]["test"])
        assert binary in known, (
            f"{name} healthchecks with `{binary}`, which {image} is not known to provide "
            f"(verified: {', '.join(sorted(known))})"
        )


def test_a_built_image_still_declares_a_pinned_tag_and_a_pinned_base(
    services: dict[str, dict[str, Any]],
) -> None:
    """Building an image moves the pin, it does not remove it.

    A service with `build` and no `image` gets a tag compose invents, which the pin check above
    cannot see and an operator reading `ps` cannot recognise. And the reproducibility claim moves
    from the compose file into the Dockerfile, so the `FROM` has to be pinned for the same reason
    the `image` keys are; otherwise the one image this repository builds is the one image it
    cannot rebuild identically.
    """
    for name, service in services.items():
        build = service.get("build")
        if build is None:
            continue
        assert "image" in service, (
            f"{name} builds without naming a tag, so its pin is compose's to invent"
        )
        context = build if isinstance(build, str) else build["context"]
        dockerfile = REPO_ROOT / context / "Dockerfile"
        assert dockerfile.is_file(), f"{name} builds from {context}, which holds no Dockerfile"
        bases = [
            line.split()[1]
            for line in dockerfile.read_text(encoding="utf-8").splitlines()
            if line.startswith("FROM ")
        ]
        assert bases, f"{dockerfile} declares no FROM"
        for base in bases:
            assert ":" in base, f"{dockerfile} builds FROM {base}, which is `latest` in disguise"
            assert not base.endswith(":latest"), (
                f"{dockerfile} builds FROM {base}, which is not a pin"
            )


def test_dependencies_wait_for_health_not_start(services: dict[str, dict[str, Any]]) -> None:
    for name, service in services.items():
        for dependency, spec in (service.get("depends_on") or {}).items():
            assert isinstance(spec, dict), (
                f"{name} depends on {dependency} by list form, which waits for container "
                "start rather than readiness"
            )
            condition = spec.get("condition")
            assert condition in {"service_healthy", "service_completed_successfully"}, (
                f"{name} -> {dependency} waits on {condition}, which is neither readiness nor "
                "completion, so it waits for container start and races whatever it needs"
            )
            if condition == "service_completed_successfully":
                # Only legitimate against something that terminates. Waiting for a long-running
                # service to complete is a hang, not a dependency, and `up --wait` would sit
                # until its timeout and then blame the waiter.
                assert "healthcheck" not in services[str(dependency)], (
                    f"{name} waits for {dependency} to complete, but {dependency} declares a "
                    "healthcheck, so it is meant to stay up and will never complete"
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


def test_no_published_host_port_is_a_literal(services: dict[str, dict[str, Any]]) -> None:
    """The host half of every published port must be a variable with a default.

    A literal here is what stopped the integration tier running beside a stack started by hand.
    The project name the tier uses isolates containers, networks and volumes, and host ports are
    not among them, so two projects publishing 7077 cannot both start and the second one to try
    fails on a bind. The tier sets these variables to 0 and lets Docker choose; the defaults keep
    `make up` publishing the numbers the README and the guide name. Putting a number back here
    restores the collision, and it shows up as a bind error six tests deep rather than anywhere
    near the line that caused it, which is the reason this is checked rather than remembered.
    """
    for name, service in services.items():
        for mapping in service.get("ports") or []:
            assert isinstance(mapping, str), (
                f"{name} publishes {mapping!r} in long form; this check reads the short one"
            )
            host, _, container = mapping.rpartition(":")
            assert host, f"{name} publishes {mapping!r} with no host half to check"
            assert PUBLISHED_HOST_PORT.match(host), (
                f"{name} publishes host port {host!r}, which is a literal rather than a variable "
                f"with a default; the tier cannot override it and will collide with `make up`"
            )
            assert container.isdigit(), (
                f"{name} publishes container port {container!r}, which is not a number"
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
    """Required of everything meant to stay up, and deliberately absent from what is not.

    The rule used to apply to every service without exception, which was correct while every
    service was long-running. A one-shot provisioner with `restart: unless-stopped` is restarted
    forever and never completes, so the condition waiting on it never fires; the separate
    assertion in test_a_one_shot_service_does_not_restart is what catches that, and this one
    stops requiring the policy that would cause it.
    """
    one_shot = set(completion_waiters(services))
    for name, service in services.items():
        if name in one_shot:
            continue
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

    Both existing checks on .env.example pass in this case: the variable is declared and
    it is interpolated, so the gap is one level deeper than either of them looks. What
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
