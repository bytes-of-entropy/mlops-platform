"""What a CI job has to do before it may touch compose, and what its first run proved.

`supply.yml`'s first execution failed in zero seconds on `required variable MINIO_ROOT_PASSWORD is
missing a value: set MINIO_ROOT_PASSWORD in .env`, before syft was reached. That message is the
compose file's own: every credential is interpolated as `${VAR:?set VAR in .env}`, the form that
refuses rather than substituting an empty value, so compose declines to parse its own file without a
`.env` -- even for `build`, which starts nothing and reads none of the values. The property
protecting the credentials is what makes the step impossible without one.

So any job invoking a compose-touching target needs a `.env` first, and the failure is silent until
a machine without one runs it. Neither the authoring laptop nor the build machine is such a machine:
both have had a real `.env` for months. Only a fresh runner is, which is why this went unnoticed
until the repository had a remote.

These assertions are textual and run anywhere. That is the point: the alternative is discovering the
next instance the same way, on a job that runs weekly.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: Make targets whose recipes invoke docker compose, and which therefore cannot run without a `.env`
#: no matter what they do afterwards. `build` is the surprising member and the one that failed: it
#: neither starts a container nor reads a credential, and compose still refuses to parse.
COMPOSE_TARGETS = ("build", "up", "up-quickstart", "down", "clean", "reset", "config", "ps", "logs")

#: Every variable the compose file requires. Named here rather than derived, because the assertion
#: is that a job supplies all of them: a job supplying six of seven fails on the seventh, in zero
#: seconds, with a message about whichever one compose happened to reach first.
REQUIRED_VARIABLES = (
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "AIRFLOW_ADMIN_PASSWORD",
    "AIRFLOW_FERNET_KEY",
)


def workflows() -> dict[str, dict[str, Any]]:
    found = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict), f"{path.name} does not parse to a mapping"
        found[path.name] = loaded
    return found


def jobs() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (name, job_name, job)
        for name, workflow in workflows().items()
        for job_name, job in workflow["jobs"].items()
    ]


def steps_of(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


def touches_compose(job: dict[str, Any]) -> list[str]:
    """Which compose-requiring make targets a job invokes, if any."""
    found = []
    for step in steps_of(job):
        run = step.get("run") or ""
        for target in COMPOSE_TARGETS:
            if f"make {target}" in run:
                found.append(target)
    return found


def test_there_are_workflows_and_jobs_to_check() -> None:
    """The anti-vacuity guard: every rule below passes trivially against nothing."""
    assert len(workflows()) >= 2, "fewer than two workflows found"
    assert len(jobs()) >= 4, "fewer than four jobs found"


def test_at_least_one_job_touches_compose() -> None:
    """If none did, the rule below would be vacuous rather than satisfied."""
    touching = [f"{w}:{j}" for w, j, job in jobs() if touches_compose(job)]
    assert touching, f"no job invokes any of {COMPOSE_TARGETS}, so the .env rule proves nothing"


def test_every_job_touching_compose_writes_an_env_first() -> None:
    """The defect `supply.yml`'s first run found, as an assertion rather than a second incident.

    Order matters and is checked: a credential step *after* the compose step is the same failure
    with a tidier diff. So this finds the index of both and compares them.
    """
    for workflow, name, job in jobs():
        targets = touches_compose(job)
        if not targets:
            continue
        steps = steps_of(job)
        writes = [i for i, step in enumerate(steps) if ".env" in (step.get("run") or "")]
        first_compose = next(
            i
            for i, step in enumerate(steps)
            if any(f"make {target}" in (step.get("run") or "") for target in targets)
        )
        assert writes, (
            f"{workflow}:{name} runs `make {targets[0]}` and writes no .env. Compose refuses "
            f"to parse its own file without one, so this fails in zero seconds on a runner"
        )
        assert min(writes) < first_compose, (
            f"{workflow}:{name} writes its .env at step {min(writes)} but reaches compose at step "
            f"{first_compose}; the credentials have to exist before compose parses the file"
        )


def test_every_job_that_writes_an_env_supplies_every_required_variable() -> None:
    """Six of seven fails exactly like zero of seven, and names whichever compose reached first.

    Checked against the variable list rather than against the other job's text, so that adding a
    service with a new credential fails here rather than in a weekly workflow nobody is watching.
    """
    for workflow, name, job in jobs():
        env_steps = [step for step in steps_of(job) if ".env" in (step.get("run") or "")]
        if not env_steps:
            continue
        written = "\n".join(step.get("run") or "" for step in env_steps)
        missing = [variable for variable in REQUIRED_VARIABLES if variable not in written]
        assert not missing, f"{workflow}:{name} writes a .env without {missing}"


def test_no_workflow_writes_a_credential_that_is_not_generated() -> None:
    """A literal in a workflow is a committed secret, whatever it is a secret for.

    The generated values are `openssl rand` output, discarded with the runner. This asserts the
    shape rather than the strength: any credential line whose value is neither a command
    substitution nor a GitHub secret reference is a literal somebody typed.
    """
    offenders = []
    for workflow, name, job in jobs():
        for step in steps_of(job):
            for line in (step.get("run") or "").splitlines():
                stripped = line.strip().lstrip("{").strip()
                if not stripped.startswith("echo "):
                    continue
                if not any(word in stripped for word in ("PASSWORD", "KEY", "SECRET", "TOKEN")):
                    continue
                if "$(" in stripped or "${{" in stripped:
                    continue
                offenders.append(f"{workflow}:{name}: {stripped}")
    assert not offenders, (
        f"a workflow writes a credential-shaped literal: {offenders}. Generate it on the runner or "
        f"read it from a secret; a value typed into a workflow is committed"
    )


#: The one required variable that is a name rather than a credential, and is therefore allowed a
#: default. `POSTGRES_DB` resolves to `platform` when unset, which is a configuration convenience; a
#: default password would be a committed secret, which is the distinction record 009 draws.
DEFAULTED_VARIABLE = "POSTGRES_DB"


@pytest.mark.parametrize("variable", [v for v in REQUIRED_VARIABLES if v != DEFAULTED_VARIABLE])
def test_every_credential_is_interpolated_in_the_form_that_refuses(variable: str) -> None:
    """`${VAR:?message}` errors when unset; bare `${VAR}` interpolates to empty and only warns.

    That difference is the whole protection, and it is why `supply.yml` failed in zero seconds
    rather than building an image against an empty password. Each credential has to appear at least
    *once* in the refusing form -- once is enough, because compose validates the whole file, so one
    `:?` on a variable protects every bare use of it elsewhere.

    Asserted per credential rather than over the file, so a rename or a downgrade to the bare form
    fails naming which variable lost its guard. This test replaces one that asserted the bare form
    was present, which was wrong about the mechanism and would have passed while the protection was
    gone.
    """
    compose = (REPO_ROOT / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    assert f"${{{variable}:?" in compose, (
        f"{variable} is never interpolated as ${{{variable}:?...}}, so compose would substitute an "
        f"empty value and warn rather than refuse. A credential that silently becomes empty "
        f"is worse than one that is missing"
    )


def test_no_credential_is_given_a_default() -> None:
    """A default is fine for a port or a database name and never for a credential.

    Seven variables in the compose file carry `:-` defaults and six are host-port overrides, which
    exist so two checkouts can run side by side. The seventh is `POSTGRES_DB`, a database name. What
    must never appear in that list is a credential, because a default credential is a committed
    secret and is exactly what record 009 forbids -- the harm is not that it is weak, it is that it
    works, so a machine with no `.env` starts successfully and nobody notices.

    Written this way after two narrower versions were wrong about the file rather than the file
    being wrong about itself: the first asserted every variable used the bare form, the second that
    only one
    default existed anywhere. Both would have failed on correct configuration.
    """
    compose = (REPO_ROOT / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    defaulted = set(re.findall(r"\$\{([A-Z_]+):-", compose))
    credentials = {v for v in REQUIRED_VARIABLES if v != DEFAULTED_VARIABLE}
    offenders = sorted(defaulted & credentials)
    assert not offenders, (
        f"{offenders} carry a `:-` default. A default credential means a machine with no .env "
        f"starts successfully instead of refusing, which record 009 exists to prevent"
    )
    assert all(name.endswith("_HOST_PORT") or name == DEFAULTED_VARIABLE for name in defaulted), (
        f"a variable outside the host-port set gained a default: "
        f"{sorted(n for n in defaulted if not n.endswith('_HOST_PORT'))}. "
        f"Defaults are for ports and names; anything else needs an argument"
    )
