"""``make doctor``: gather the state, run the checks, say what is wrong before an ``up`` does.

The gathering lives here and nowhere else. Everything below this file is pure or injectable, which
is why the checks have tests and this does not need many: it reads two files, probes the daemon,
and formats.
"""

from __future__ import annotations

import os
import sys

from preflight.checks import FAIL, OK, Inputs, Result, first_init_variables, run
from preflight.locations import ENV_EXAMPLE_FILE, ENV_FILE, read_text_if_present
from preflight.runtime import probe_docker, read_postgres_volume

NAME_WIDTH = 18
STATUS_WIDTH = 8


def gather() -> Inputs:
    return Inputs(
        docker_state=probe_docker(),
        example_text=read_text_if_present(ENV_EXAMPLE_FILE) or "",
        env_text=read_text_if_present(ENV_FILE),
        environ=os.environ,
        read_volume=read_postgres_volume,
    )


def render(results: list[Result]) -> list[str]:
    """One line per check, wrapped nowhere: a detail that is a sentence stays a sentence."""
    return [
        f"{result.name:<{NAME_WIDTH}} {result.status:<{STATUS_WIDTH}} {result.detail}"
        for result in results
    ]


def main() -> int:
    results = run(gather())
    for line in render(results):
        print(line)

    if any(result.status != OK for result in results):
        print()
        print(
            "pinned by the postgres volume, so editing one after the first start changes nothing "
            "inside it: " + ", ".join(first_init_variables())
        )
    return 1 if any(result.status == FAIL for result in results) else 0


if __name__ == "__main__":
    # UNKNOWN deliberately does not reach here as a failure; see the module docstring in checks.py.
    sys.exit(main())
