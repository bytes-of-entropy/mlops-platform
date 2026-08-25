"""One place where the integration tier builds a compose invocation, and runs one.

Two integration modules now need a running stack and they need different ones: the idempotency
cycle wants the capped quickstart, and the M0 smoke wants the full profile because that is the only
one that includes Airflow. Different argv, same plumbing -- and a second copy of the plumbing would
be a second chance to anchor the project directory somewhere other than the repository root, which
is the defect ``docs/decisions/004`` exists for. So both invocations are built from one base here,
and the inventory in ``test_compose_paths.py`` checks that base rather than chasing copies.

Every call routes through :meth:`Stack.check`, which raises with the command, the exit code, both
streams and the container state gathered afterwards. That is not a convenience: an integration
failure is produced on one machine and read on another, and a bare ``compose up failed`` costs a
round trip to ask what it actually said.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from tests.conftest import REPO_ROOT, describe_process

#: The suite's own project name. Not cosmetic: compose derives the default from the directory
#: basename, so without this the tier's containers and volumes are the ones `make up` created -- one
#: stack under two names, where either side's teardown lands on the other. A developer's kept
#: volume would then decide whether the tier passes, and `make clean` in another window would delete
#: state a running test case is mid-way through asserting. Naming a project is the only way to
#: separate them, because re-cloning cannot: the basename is the same in every clone. The tier's
#: `down` keeps its volumes, as `make down` does, so they outlive a run under this name; removing
#: them is `docker compose -p mlops-platform-tests down --volumes`.
TEST_PROJECT = "mlops-platform-tests"

#: --project-directory, exactly as both entrypoints pass it. An integration suite that resolved
#: `.env` and the bind mounts differently from `make up` would be testing a stack nobody runs.
#: The project *name* is the one thing deliberately not shared -- it renames containers and volumes
#: and changes nothing about how the files are read.
BASE = (
    "docker",
    "compose",
    "--project-directory",
    ".",
    "-p",
    TEST_PROJECT,
    "-f",
    "compose/docker-compose.yml",
)
#: The capped overlay: one Spark worker, no Airflow, inside the 4 GiB envelope.
QUICKSTART = (*BASE, "-f", "compose/docker-compose.quickstart.yml")
#: The whole spine, which is the only shape that has an Airflow to schedule anything.
FULL = (*BASE, "--profile", "full")

#: Host ports for the tier, left to the kernel to choose. The project name above isolates
#: containers, networks and volumes and nothing else, so while the compose file published fixed
#: host ports the tier could not start alongside a by-hand stack: whichever bound second failed,
#: and it failed as `Bind for 0.0.0.0:7077 failed: port is already allocated` underneath test
#: names about idempotency and smoke. A host port of 0 asks Docker for a free one at bind time.
#:
#: That is deliberately not a scan for a free port before starting. Between finding one free and
#: binding it, anything on the machine can take it, which trades a collision that happens every
#: time for one that happens sometimes -- and a test that fails sometimes is the worse defect.
#: `docker compose -p mlops-platform-tests port <service> <container-port>` reports what was
#: assigned, and `compose ps` prints the mappings, so the diagnostics already carry them.
EPHEMERAL_PORTS = {
    "SPARK_MASTER_UI_HOST_PORT": "0",
    "SPARK_MASTER_HOST_PORT": "0",
    "MINIO_API_HOST_PORT": "0",
    "MINIO_CONSOLE_HOST_PORT": "0",
    "MLFLOW_HOST_PORT": "0",
    "AIRFLOW_HOST_PORT": "0",
}

TIMEOUT_S = 600
#: Enough log to hold a start-up objection, short of replaying the whole boot.
LOG_TAIL_LINES = 30


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is built in this module, no shell, no input
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=False,
        # Every call, not only `up`: compose interpolates on each invocation, and a `down` that
        # rendered different ports from the `up` it is tearing down is a different stack to it.
        env={**os.environ, **EPHEMERAL_PORTS},
    )


@dataclass(frozen=True)
class Stack:
    """A compose invocation, plus the operations the integration tier performs through it."""

    argv: tuple[str, ...]

    def diagnostics(self) -> dict[str, str]:
        """What the stack looked like at the moment it refused.

        A failed `up --wait` almost never says why: the reason is a container that started,
        logged its objection and went unhealthy. `role "x" does not exist` from a Postgres whose
        volume was initialised under a different POSTGRES_USER is exactly that shape -- invisible
        in compose's own output, unmissable in the service log.
        """
        gathered: dict[str, str] = {}
        for name, args in (
            ("compose ps", ["ps", "--all"]),
            ("service logs", ["logs", "--tail", str(LOG_TAIL_LINES), "--no-color"]),
        ):
            try:
                probe = run([*self.argv, *args])
            except (OSError, subprocess.SubprocessError) as error:  # gathering must never mask
                gathered[name] = f"could not be gathered: {error!r}"
                continue
            gathered[name] = probe.stdout or probe.stderr
        return gathered

    def check(self, label: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run a compose subcommand, and if it fails say everything about how it failed."""
        argv = [*self.argv, *args]
        result = run(argv)
        if result.returncode != 0:
            raise AssertionError(
                describe_process(
                    label, argv, result.returncode, result.stdout, result.stderr, self.diagnostics()
                )
            )
        return result

    def healthy(self) -> set[str]:
        """The services compose reports as running, and healthy where they declare a check."""
        result = self.check("compose ps", "ps", "--format", "json")
        states: set[str] = set()
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("Health") in {"healthy", ""} and row.get("State") == "running":
                states.add(row["Service"])
        return states

    def up(self) -> set[str]:
        self.check("compose up", "up", "-d", "--build", "--wait")
        return self.healthy()

    def down(self) -> None:
        self.check("compose down", "down", "--remove-orphans")

    def shell(self, label: str, service: str, script: str) -> str:
        """Run one shell line inside a service and hand back its stdout.

        `-T` because there is no terminal in a test run, and `sh -lc` because the scripts here
        read variables the image itself put in the environment rather than values passed in from
        outside -- which is what keeps credentials out of an argv this module builds.
        """
        return self.check(label, "exec", "-T", service, "sh", "-lc", script).stdout
