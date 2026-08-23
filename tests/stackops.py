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
import subprocess
from dataclasses import dataclass

from tests.conftest import REPO_ROOT, describe_process

#: --project-directory, exactly as both entrypoints pass it. An integration suite that resolved
#: `.env` and the bind mounts differently from `make up` would be testing a stack nobody runs.
BASE = (
    "docker",
    "compose",
    "--project-directory",
    ".",
    "-f",
    "compose/docker-compose.yml",
)
#: The capped overlay: one Spark worker, no Airflow, inside the 4 GiB envelope.
QUICKSTART = (*BASE, "-f", "compose/docker-compose.quickstart.yml")
#: The whole spine, which is the only shape that has an Airflow to schedule anything.
FULL = (*BASE, "--profile", "full")

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
        self.check("compose up", "up", "-d", "--wait")
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
