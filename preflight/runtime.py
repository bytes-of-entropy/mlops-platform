"""Whether the container runtime can answer, and what the kept volume says about itself.

The two things in this repository that cannot be established by reading files. Both are split into
a pure classifier and a thin shell-out, so the interesting half is testable on a machine with no
daemon, which is every machine this code is written on.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from preflight.locations import REPO_ROOT

DAEMON_PROBE_TIMEOUT_SECONDS = 20

#: Generous, because this pulls the Postgres image on a cold machine before it can read a file.
VOLUME_PROBE_TIMEOUT_SECONDS = 300

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
    socket, and on a developer machine the usual state is installed-but-not-running, so a
    presence check marks the integration tests as runnable and they then fail on a connection
    error, which reads like a broken repository rather than a stopped service.

    ``docker info`` is the cheapest command that requires the daemon to answer.
    """
    binary = shutil.which("docker")
    if binary is None:
        return classify_docker_state(None, None)
    try:
        completed = subprocess.run(  # noqa: S603 (fixed argv, resolved path, no shell)
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=DAEMON_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a daemon that has not answered in 20 seconds is not one these
        # checks can use, and the distinction between slow and stopped does not change the advice.
        return classify_docker_state(binary, None)
    return classify_docker_state(binary, completed.returncode)


# The fourth place in this repository that builds a compose invocation, and the reason
# tests/test_compose_paths.py keeps an inventory of them. --project-directory is what makes the
# relative -f path and the root .env mean what they read as; the spine file alone is enough here
# because the service being borrowed is in it.
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    ".",
    "-f",
    "compose/docker-compose.yml",
]

#: The service whose definition is borrowed to look inside the volume. Borrowed rather than
#: rebuilt: it already names the image and already mounts postgres-data under the project name
#: compose derives from the directory, so nothing here restates a pin or guesses at a volume name.
POSTGRES_SERVICE = "postgres"

VOLUME_EMPTY = "empty"
VOLUME_UNFINGERPRINTED = "initialised-without-fingerprint"
VOLUME_FINGERPRINTED = "fingerprint"
VOLUME_UNREADABLE = "unreadable"

#: Three states, one line each, no command substitution: the container reports what it found and
#: this process decides what it means. Printing the file rather than comparing inside the container
#: keeps the credentials being checked out of the container's argument list.
REPORT_SCRIPT = (
    'if [ -f "$PGDATA/.init-credentials" ]; then '
    "echo " + VOLUME_FINGERPRINTED + '; cat "$PGDATA/.init-credentials"; '
    'elif [ -f "$PGDATA/PG_VERSION" ]; then '
    "echo " + VOLUME_UNFINGERPRINTED + "; "
    "else echo " + VOLUME_EMPTY + "; fi"
)


@dataclass(frozen=True)
class VolumeState:
    """What the Postgres data volume holds, before anything is compared against it."""

    kind: str
    salt: str = ""
    digest: str = ""
    detail: str = ""


def parse_volume_report(returncode: int, stdout: str, stderr: str) -> VolumeState:
    """Read the one-shot container's report.

    Scans for a marker line rather than reading the first one, because compose narrates its own
    work (pulling, creating a volume, creating a container) and which stream it narrates on
    varies by version.
    """
    if returncode != 0:
        tail = (stderr.strip() or stdout.strip() or "no output").splitlines()[-1]
        return VolumeState(VOLUME_UNREADABLE, detail=f"exit code {returncode}: {tail}")

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line == VOLUME_FINGERPRINTED and index + 1 < len(lines):
            salt, _, digest = lines[index + 1].partition(":")
            if salt and digest:
                return VolumeState(VOLUME_FINGERPRINTED, salt=salt, digest=digest)
            return VolumeState(
                VOLUME_UNREADABLE, detail="the recorded fingerprint is not salt:digest"
            )
        if line in (VOLUME_UNFINGERPRINTED, VOLUME_EMPTY):
            return VolumeState(line)
    return VolumeState(VOLUME_UNREADABLE, detail="the probe container reported nothing readable")


def read_postgres_volume() -> VolumeState:
    """Look inside the volume with a one-shot container built from the Postgres service.

    ``compose run`` rather than ``docker run``: compose resolves the project name from the
    directory and therefore the real volume name, and it takes the image tag from the service
    definition. A hand-written ``docker run`` would need both restated, and a second copy of a pin
    is a second thing to forget.
    """
    argv = [
        *COMPOSE,
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "sh",
        POSTGRES_SERVICE,
        "-c",
        REPORT_SCRIPT,
    ]
    try:
        completed = subprocess.run(  # noqa: S603 (argv is built here, no shell, no input)
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=VOLUME_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return VolumeState(VOLUME_UNREADABLE, detail=f"{type(error).__name__} running the probe")
    return parse_volume_report(completed.returncode, completed.stdout, completed.stderr)
