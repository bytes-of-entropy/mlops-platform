"""Something crosses the spine: Airflow parses a DAG, runs it, and the run lands in Postgres.

This is the other half of the M0 gate. The idempotency tier proves the stack comes up the same way
twice; this proves the parts of it can reach each other, which no healthcheck can say, since a
healthcheck is a service answering its own port.

The crossing is asserted at both ends rather than the near one. MLflow's API reporting a finished
run proves Airflow reached MLflow; the same run id turning up as a row in the Postgres database
proves MLflow reached its backend store rather than buffering the write somewhere that lasts until
the next restart. Either claim alone leaves the more expensive half of the path unproven.

It runs the DAG synchronously with `airflow dags test`. A manual trigger plus a poll would also
exercise the scheduler noticing new work, and would make the assertion depend on how long that takes
on the machine of the day: a test that fails at a slow moment reports a broken spine. The
scheduler's liveness is already gated on by `up --wait`, so the flaky version buys almost nothing.

The whole profile comes up once for the module. Bringing 20 GB of stack up per test would be honest
and unusable; the tests below share one stack and assert independently of each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import requires_docker, requires_local_credentials
from tests.dagfile import declared
from tests.stackops import FULL, PAYLOAD, Stack, payload

pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]

DAG_ID = str(declared("DAG_ID"))
EXPERIMENT_NAME = str(declared("EXPERIMENT_NAME"))
PARAM_KEY = str(declared("PARAM_KEY"))
PARAM_VALUE = str(declared("PARAM_VALUE"))
METRIC_KEY = str(declared("METRIC_KEY"))
METRIC_VALUE = float(declared("METRIC_VALUE"))

#: The services this file's claim depends on. Spark is in the profile and irrelevant here.
REQUIRED_SERVICES = frozenset({"airflow", "mlflow", "postgres"})

#: Run inside the MLflow container, through its own loopback, using the standard library that
#: image already has. Asking from the host would test the published port as well, which is a
#: different claim and one the quickstart tier has no interest in.
QUERY_RUNS = f"""
import json, urllib.parse, urllib.request

BASE = "http://localhost:5000/api/2.0/mlflow"

query = urllib.parse.urlencode({{"experiment_name": {EXPERIMENT_NAME!r}}})
found = json.load(urllib.request.urlopen(f"{{BASE}}/experiments/get-by-name?{{query}}"))
request = urllib.request.Request(
    f"{{BASE}}/runs/search",
    data=json.dumps({{"experiment_ids": [found["experiment"]["experiment_id"]]}}).encode(),
    headers={{"Content-Type": "application/json"}},
    method="POST",
)
print({PAYLOAD!r} + json.dumps(json.load(urllib.request.urlopen(request))))
"""

#: -tA: no alignment, no header, so each output line is a value and nothing else. The user and
#: database come from the container's own environment, which keeps a credential out of this argv,
#: and the statement takes no parameters; the run id is compared in Python rather than
#: interpolated into SQL. Bounded, because a query that grows with the table is a query that
#: eventually returns more than anyone wanted to read.
RECENT_RUN_ROWS = (
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc '
    '"select run_uuid from runs order by start_time desc limit 20"'
)

stack = Stack(FULL)


@pytest.fixture(scope="module")
def running_stack() -> Iterator[Stack]:
    stack.up()
    try:
        yield stack
    finally:
        stack.down()


def latest_run(current: Stack) -> dict[str, Any]:
    """The most recently started run in the smoke experiment, as MLflow reports it."""
    reported = current.check("mlflow query", "exec", "-T", "mlflow", "python3", "-c", QUERY_RUNS)
    parsed = payload(reported.stdout, "mlflow run lookup")
    runs = parsed.get("runs") or []
    assert runs, f"MLflow holds no run in the {EXPERIMENT_NAME} experiment: {parsed}"
    return max(runs, key=lambda run: int(run["info"]["start_time"]))


def test_the_full_profile_brings_up_the_services_the_smoke_needs(running_stack: Stack) -> None:
    """Airflow only exists in this profile, so this is also the first check that it starts."""
    healthy = running_stack.healthy()
    missing = REQUIRED_SERVICES - healthy
    assert not missing, f"came up without {sorted(missing)}; healthy: {sorted(healthy)}"


def test_the_scheduler_registers_the_dag_without_an_import_error(running_stack: Stack) -> None:
    """A DAG with a bad import is not a failing DAG, it is an absent one.

    Airflow reports the traceback on a page nobody opens during a test run and carries on serving,
    so the DAG the next test triggers would simply not be there, and `dags test` would say
    "does not exist" rather than naming the import that broke.
    """
    listed = running_stack.check(
        "airflow dags list", "exec", "-T", "airflow", "airflow", "dags", "list"
    )
    assert DAG_ID in listed.stdout, (
        f"{DAG_ID} is not registered; the scheduler is running but does not know about it:\n"
        f"{listed.stdout}"
    )

    errors = running_stack.check(
        "airflow import errors", "exec", "-T", "airflow", "airflow", "dags", "list-import-errors"
    )
    assert "m0_smoke.py" not in errors.stdout, (
        f"the scheduler could not import the smoke DAG:\n{errors.stdout}"
    )


def test_the_dag_run_reaches_mlflow_and_lands_in_postgres(running_stack: Stack) -> None:
    """The M0 claim, asserted at the far end of the path rather than the near one."""
    running_stack.check(
        "airflow dags test", "exec", "-T", "airflow", "airflow", "dags", "test", DAG_ID
    )

    run = latest_run(running_stack)
    info = run["info"]
    assert info["status"] == "FINISHED", (
        f"the smoke run is {info['status']}, so the task started writing and did not finish: {info}"
    )

    data = run.get("data") or {}
    params = {entry["key"]: entry["value"] for entry in data.get("params") or []}
    metrics = {entry["key"]: float(entry["value"]) for entry in data.get("metrics") or []}
    tags = {entry["key"]: entry["value"] for entry in data.get("tags") or []}

    assert params.get(PARAM_KEY) == PARAM_VALUE, f"params: {params}"
    assert metrics.get(METRIC_KEY) == METRIC_VALUE, f"metrics: {metrics}"
    assert tags.get("airflow.dag_id") == DAG_ID, (
        f"the newest run was not written by this DAG, so something else is using the "
        f"{EXPERIMENT_NAME} experiment: {tags}"
    )

    run_id = str(info["run_id"])
    rows = running_stack.shell("postgres run rows", "postgres", RECENT_RUN_ROWS)
    persisted = {line.strip() for line in rows.splitlines() if line.strip()}
    assert run_id in persisted, (
        f"MLflow reports run {run_id}, and the twenty newest rows in the Postgres runs table are "
        f"{sorted(persisted)}, so the tracking server is not persisting where the compose file "
        f"says it is"
    )
