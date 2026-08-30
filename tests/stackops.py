"""One place where the integration tier builds a compose invocation, and runs one.

Two integration modules now need a running stack and they need different ones: the idempotency
cycle wants the capped quickstart, and the M0 smoke wants the full profile because that is the only
one that includes Airflow. Different argv, same plumbing, and a second copy of the plumbing would
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
from typing import Any

from tests.conftest import REPO_ROOT, describe_process

#: Fences a snippet's JSON inside stdout that is not *only* that JSON.
#:
#: Not defensiveness; a defect that happened. Two modules run a Python snippet inside a
#: container and parsed the whole of stdout as one JSON document. MLflow 2.22 prints a
#: "View run at ..." banner when a run exits and 2.13 did not, so the first suite run after
#: the base bump failed with `Expecting value: line 1 column 1` on a round trip that had
#: *succeeded* -- the JSON was there, with the right body, behind two lines of someone
#: else's output.
#:
#: The general lesson rather than the MLflow one: a test that parses another program's
#: stdout as if it owns all of it is asserting something about that program's console output
#: that nobody promised. A library may start printing at any version. Fencing costs one line
#: and cannot be broken by a banner nobody has written yet.
PAYLOAD = "<<<payload>>>"


def payload(stdout: str, what: str) -> Any:
    """The JSON a snippet fenced with :data:`PAYLOAD`, out of whatever was printed around it.

    `raw_decode` rather than `loads`, so output *after* the document is ignored the same way output
    before the marker is. The last marker wins, so a snippet that printed twice is read as meaning
    its final answer.
    """
    at = stdout.rfind(PAYLOAD)
    if at < 0:
        raise AssertionError(
            f"{what}: no {PAYLOAD} marker in the container's stdout, so the snippet did not reach "
            f"its print. Output was {stdout!r}"
        )
    tail = stdout[at + len(PAYLOAD) :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(tail)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"{what}: the text after {PAYLOAD} is not JSON ({error}). Output was {stdout!r}"
        ) from error
    return value


#: The suite's own project name. Not cosmetic: compose derives the default from the directory
#: basename, so without this the tier's containers and volumes are the ones `make up` created: one
#: stack under two names, where either side's teardown lands on the other. A developer's kept
#: volume would then decide whether the tier passes, and `make clean` in another window would delete
#: state a running test case is mid-way through asserting. Naming a project is the only way to
#: separate them, because re-cloning cannot: the basename is the same in every clone. The tier's
#: `down` keeps its volumes, as `make down` does, so they outlive a run under this name; removing
#: them is `docker compose -p mlops-platform-tests down --volumes`.
TEST_PROJECT = "mlops-platform-tests"

#: --project-directory, exactly as both entrypoints pass it. An integration suite that resolved
#: `.env` and the bind mounts differently from `make up` would be testing a stack nobody runs.
#: The project *name* is the one thing deliberately not shared; it renames containers and volumes
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
#: time for one that happens sometimes, and a test that fails sometimes is the worse defect.
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
#: A service that exited non-zero gets more room than the shared tail allows, because its output
#: is the one thing the report exists to surface.
FAILURE_LOG_LINES = 80


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 (argv is built in this module, no shell, no input)
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
        volume was initialised under a different POSTGRES_USER is exactly that shape: invisible
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

        # The section above is one shared budget across every service, and the report caps each
        # section, so a stack of chatty services crowds out the quiet one that actually failed.
        # That is not hypothetical: a one-shot provisioner exited 1, and its output was the part
        # truncated away, leaving a report that named the failure and not its cause. Anything that
        # exited non-zero therefore gets a section to itself, which cannot be squeezed out by
        # Postgres announcing that it is ready.
        for service in self.exited_badly():
            key = f"{service} log (exited non-zero)"
            try:
                probe = run(
                    [*self.argv, "logs", "--no-color", "--tail", str(FAILURE_LOG_LINES), service]
                )
            except (OSError, subprocess.SubprocessError) as error:
                gathered[key] = f"could not be gathered: {error!r}"
                continue
            gathered[key] = probe.stdout or probe.stderr or "(the container produced no output)"
        return gathered

    def exited_badly(self) -> list[str]:
        """Services whose container is gone and left a non-zero code behind.

        Best effort by construction: this runs while something has already failed, so it must never
        raise and never mask the failure it is describing. An empty list means "nothing to add",
        never "everything is fine".
        """
        try:
            probe = run([*self.argv, "ps", "--all", "--format", "json"])
        except (OSError, subprocess.SubprocessError):
            return []

        text = (probe.stdout or "").strip()
        if not text:
            return []
        try:
            # Compose has emitted both a JSON array and one object per line across versions, and
            # which one is not worth depending on.
            records = (
                json.loads(text)
                if text.startswith("[")
                else [json.loads(line) for line in text.splitlines() if line.strip()]
            )
        except (TypeError, ValueError):
            return []

        failed: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            code = record.get("ExitCode")
            service = record.get("Service")
            if isinstance(service, str) and isinstance(code, int) and code != 0:
                failed.append(service)
        return sorted(set(failed))

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
        outside, which is what keeps credentials out of an argv this module builds.
        """
        return self.check(label, "exec", "-T", service, "sh", "-lc", script).stdout
