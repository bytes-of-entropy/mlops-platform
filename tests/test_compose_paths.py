"""Where compose resolves relative paths, asserted without a container runtime.

Compose resolves the default ``.env`` and every relative bind mount against the *project
directory*, and the project directory defaults to the directory of the first ``-f`` file --
``compose/`` here, not the repository root. That single rule produced two defects at once:
the root ``.env`` went unread while the README told a reviewer to create it there, and
``./postgres/init`` pointed at a path Docker creates as an empty directory rather than
refusing, so the Postgres init SQL simply never ran and said nothing about it.

The contract suite could not see either one, because parsing compose files as data is
precisely what lets it run with no daemon installed -- and path resolution is the daemon's
half of the job. These tests close that hole from the data side: they check the flag that
anchors the project directory, and they check that the paths the mounts name actually exist
where the flag makes them point.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from preflight.runtime import COMPOSE as DOCTOR_ARGV
from tests.conftest import REPO_ROOT
from tests.stackops import BASE as INTEGRATION_ARGV

PROJECT_DIRECTORY_FLAG = "--project-directory"

#: One entry per place that builds a compose invocation. There are four: the Makefile, its
#: PowerShell mirror, ``tests/stackops.py``, and the doctor's one-shot probe -- each of them a
#: separate opportunity to resolve paths differently from the other three, so this list is also
#: the inventory. Adding an invocation without adding it here leaves it unchecked. The
#: integration tier counts once because both stacks it starts are built from one base.
MAKEFILE_INVOCATION = re.compile(r"^COMPOSE\w*\s*:=\s*docker compose (?P<flags>.+)$", re.MULTILINE)
POWERSHELL_INVOCATION = re.compile(
    r"^\$Compose\w*\s*=\s*@\('compose',(?P<flags>.+)\)$", re.MULTILINE
)


def relative_bind_mounts(services: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Every ``(service, host path)`` pair whose host side is written relative.

    A named volume has no path to resolve, so it is not this test's business.
    """
    found: list[tuple[str, str]] = []
    for name, service in services.items():
        for mount in service.get("volumes") or []:
            host = str(mount).split(":", 1)[0]
            if host.startswith("."):
                found.append((name, host))
    return found


def test_the_makefile_anchors_the_project_directory_in_every_invocation() -> None:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    invocations = MAKEFILE_INVOCATION.findall(text)
    assert invocations, "the Makefile builds no compose invocation for this test to check"
    for flags in invocations:
        assert f"{PROJECT_DIRECTORY_FLAG} ." in flags, (
            f"Makefile invocation resolves .env and bind mounts under compose/: {flags}"
        )


def test_the_powershell_mirror_anchors_it_too() -> None:
    """The mirror test compares target *names*, so a flag missing from one file is invisible to it.

    The machine that would find out is the Windows one, and it would find out as an empty
    ``compose/postgres/init`` rather than as an error.
    """
    text = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    invocations = POWERSHELL_INVOCATION.findall(text)
    assert invocations, "make.ps1 builds no compose invocation for this test to check"
    for flags in invocations:
        assert f"'{PROJECT_DIRECTORY_FLAG}', '.'" in flags, (
            f"make.ps1 invocation resolves .env and bind mounts under compose/: {flags}"
        )


def test_the_integration_suite_invokes_compose_the_way_the_entrypoints_do() -> None:
    """A suite that resolved paths differently from ``make up`` would test a stack nobody runs."""
    assert PROJECT_DIRECTORY_FLAG in INTEGRATION_ARGV, (
        f"the integration tier drops {PROJECT_DIRECTORY_FLAG}, so it would pass against a "
        f"stack assembled differently from the one the targets start"
    )
    at = list(INTEGRATION_ARGV).index(PROJECT_DIRECTORY_FLAG)
    assert INTEGRATION_ARGV[at + 1] == ".", (
        f"the integration tier points the project directory somewhere else: "
        f"{INTEGRATION_ARGV[at + 1]!r}"
    )


def test_the_doctor_invokes_compose_the_way_the_entrypoints_do() -> None:
    """The doctor reads a volume through a one-shot container, so it resolves paths too.

    It borrows the Postgres service rather than naming an image and a volume of its own, which is
    what keeps the pin and the project name in one place -- but borrowing only works if compose
    reads the same project directory. Anchored somewhere else it would look inside a volume named
    after compose/, find nothing, and report a fresh machine to someone holding a full one.
    """
    assert PROJECT_DIRECTORY_FLAG in DOCTOR_ARGV, (
        f"the doctor drops {PROJECT_DIRECTORY_FLAG}, so it probes a volume compose would not use"
    )
    at = DOCTOR_ARGV.index(PROJECT_DIRECTORY_FLAG)
    assert DOCTOR_ARGV[at + 1] == ".", (
        f"the doctor points the project directory somewhere else: {DOCTOR_ARGV[at + 1]!r}"
    )


def test_every_relative_bind_mount_exists_under_the_repository_root(
    services: dict[str, dict[str, Any]],
) -> None:
    """The check the silent failure needed: a mount naming a path that is not there goes red.

    Docker creates a missing host path as an empty directory instead of refusing, so the
    consequence of getting this wrong is a service that starts, reports healthy, and quietly
    skips whatever the mount was carrying.
    """
    mounts = relative_bind_mounts(services)
    assert mounts, "no relative bind mount in the compose file, so this test proves nothing"
    for name, host in mounts:
        resolved = REPO_ROOT / host
        assert resolved.exists(), f"{name} mounts {host}, which does not exist at {resolved}"


def test_no_relative_bind_mount_would_also_resolve_under_the_compose_directory(
    services: dict[str, dict[str, Any]],
) -> None:
    """Keeps the flag load-bearing rather than merely present.

    If these paths existed under ``compose/`` as well, both readings would work and the flag
    could be dropped without anything failing -- which is how a constraint stops constraining.
    """
    compose_directory = REPO_ROOT / "compose"
    for name, host in relative_bind_mounts(services):
        shadow = compose_directory / host
        assert not shadow.exists(), (
            f"{name}'s mount {host} also resolves under compose/ ({shadow}), so nothing here "
            f"can tell the two project directories apart"
        )


def test_the_env_file_the_readme_asks_for_sits_in_the_project_directory() -> None:
    """The `.env` instruction and the `.env` lookup have to name the same directory.

    They did not, and the symptom was compose refusing to start over a variable set in a file
    it never opened.
    """
    example = REPO_ROOT / ".env.example"
    assert example.exists(), "no .env.example at the repository root for the README to point at"

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "cp .env.example .env" in readme, (
        "the README no longer tells a reviewer to create .env at the root; if the location "
        "moved, this test and the --project-directory flag both need to move with it"
    )

    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in ignored], (
        ".env is not gitignored, so filling it in is one `git add -A` away from publishing "
        "credentials"
    )


def test_the_compose_files_are_where_the_invocations_say_they_are() -> None:
    """Anchoring the project directory makes the ``-f`` paths root-relative; they must hold."""
    for name in ("compose/docker-compose.yml", "compose/docker-compose.quickstart.yml"):
        assert Path(REPO_ROOT / name).exists(), f"{name} is named by an invocation but absent"
