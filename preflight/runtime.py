"""Whether the container runtime can answer, what the kept volume says, and what tools are here.

The things in this repository that cannot be established by reading files. Both are split into
a pure classifier and a thin shell-out, so the interesting half is testable on a machine with no
daemon, which is every machine this code is written on.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
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
        "docker is installed but no daemon answered with a server version; start Docker Desktop "
        "or dockerd and re-run. A Desktop stuck part-way up answers the client and reports no "
        "server, which counts as stopped here"
    ),
}


#: The three binaries the cluster tier shells out to. A tuple because the order is the order a
#: message lists them in, and a reader chasing a missing tool should see a stable one.
CLUSTER_TOOLS = ("kind", "kubectl", "helm")


def missing_cluster_tools(which: Callable[[str], str | None] = shutil.which) -> tuple[str, ...]:
    """Which of the cluster tools are not on PATH, in declaration order.

    Presence only, deliberately, where `probe_docker` goes further and asks the daemon to answer.
    The asymmetry is not an oversight: a docker client with no daemon is the *usual* state of a
    developer machine and reads as installed, so presence there is misleading. `kind`, `kubectl` and
    `helm` are single binaries with no daemon of their own — an installed `helm` works — and the one
    thing they need that could be absent is a cluster, which the tier creates rather than requires.

    `which` is injected so the classifier can be tested on a machine that has these tools and on one
    that does not, which is the same reason `classify_docker_state` is separate from `probe_docker`.
    """
    return tuple(name for name in CLUSTER_TOOLS if which(name) is None)


def cluster_skip_reason(missing: tuple[str, ...]) -> str:
    """Why the cluster tier is skipping, naming what to install rather than that something is wrong.

    Record 006's rule: a missing precondition skips with its name, and does not fail as the thing it
    blocks. A reader who sees "helm is not installed" knows what to do; one who sees a chart failing
    to install goes looking for a defect in the chart.
    """
    if not missing:
        return ""
    listed = ", ".join(missing)
    plural = "are" if len(missing) > 1 else "is"
    return (
        f"{listed} {plural} not on PATH; the cluster tier needs all of "
        f"{', '.join(CLUSTER_TOOLS)}, and runs on the build machine"
    )


def classify_docker_state(
    binary: str | None, probe_exit_code: int | None, server_version: str | None
) -> str:
    """Turn what we observed into one of three states.

    Separated from the probe so the classification is testable without a daemon to start and
    stop. ``probe_exit_code`` is ``None`` when the probe could not be run or did not return, and
    ``server_version`` is whatever the probe printed, which is the half the exit code misses.

    An exit code of zero is not enough on its own. A Docker Desktop stuck part-way up answers the
    client, exits zero and prints an empty server version, so a check on the code alone calls it
    ready, the integration tier runs, and every test in it fails on `Error response from daemon:
    Docker Desktop is unable to start`. Eight failures that read as a broken stack, for a stopped
    one. The server version is the thing only a running daemon can supply, so it is what decides.
    """
    if binary is None:
        return DOCKER_ABSENT
    if probe_exit_code != 0:
        return DOCKER_STOPPED
    if not (server_version or "").strip():
        return DOCKER_STOPPED
    return DOCKER_READY


def probe_docker() -> str:
    """Whether Docker can actually run something, which is not the same as being installed.

    ``shutil.which`` finds the client. The client is a thin thing that talks to a daemon over a
    socket, and on a developer machine the usual state is installed-but-not-running, so a
    presence check marks the integration tests as runnable and they then fail on a connection
    error, which reads like a broken repository rather than a stopped service.

    ``docker info`` is the cheapest command that requires the daemon to answer, and the server
    version it is asked for is read rather than discarded: see ``classify_docker_state`` for the
    state in which the code says yes and the version says no.
    """
    binary = shutil.which("docker")
    if binary is None:
        return classify_docker_state(None, None, None)
    try:
        completed = subprocess.run(  # noqa: S603 (fixed argv, resolved path, no shell)
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=DAEMON_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Includes TimeoutExpired: a daemon that has not answered in 20 seconds is not one these
        # checks can use, and the distinction between slow and stopped does not change the advice.
        return classify_docker_state(binary, None, None)
    return classify_docker_state(binary, completed.returncode, completed.stdout)


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
