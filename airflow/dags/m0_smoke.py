"""The M0 gate as an artefact: one DAG, one task, one MLflow run.

M0 claims the spine is wired. Until something crosses it, that claim rests on healthchecks --
which prove each service answers its own port and nothing about whether any two of them can talk.
This DAG is the smallest thing that crosses the whole width: Airflow parses it, executes it, it
writes a run to MLflow, and MLflow persists that run to Postgres. One artefact, four boundaries,
and a failure anywhere along it is a failure of this task rather than a mystery in a log.

It is a *smoke* DAG and deliberately not a pipeline. A real pipeline needs a workload worth
scheduling, and that arrives with a flagship repository; inventing one here would put a fictional
dataset in the folder that is supposed to hold real ones.

Two things it does not prove, stated because a smoke test that overstates its reach is worse than
none. It does not touch MinIO: logging an artefact goes through the artifact store rather than the
tracking API, which would need an S3 client this image does not ship. And it exercises the
scheduler's liveness only through the healthcheck -- the integration tier runs this synchronously so
its assertion cannot depend on how long a scheduler takes to notice a manual trigger.

The MLflow REST API is called through the standard library on purpose. This image is pinned and has
no install step, so an `import mlflow` here would parse on the authoring machine and fail inside the
container -- a dependency that exists only in the mind of whoever wrote the DAG. A contract test
keeps the imports in this file to the standard library and Airflow itself.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from airflow.decorators import dag, task

#: Named here and asserted against the integration tier, which triggers this by string. A rename
#: that missed one side would fail only on the machine that has Docker.
DAG_ID = "m0_smoke"
EXPERIMENT_NAME = "m0-smoke"

#: Set by the compose file rather than defaulted here. A default would let this task appear to
#: work while talking to something nobody configured, which is the failure shape this whole
#: milestone has been spent on.
TRACKING_URI_VARIABLE = "MLFLOW_TRACKING_URI"

API_ROOT = "/api/2.0/mlflow"
REQUEST_TIMEOUT_SECONDS = 30

#: One of each, because the point is that the write path works, not that it scales. Declared
#: one name per line so both test tiers can read them out of this file without importing it.
PARAM_KEY = "stack"
PARAM_VALUE = "compose"
METRIC_KEY = "wired"
METRIC_VALUE = 1.0

ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"


def tracking_base() -> str:
    """The tracking server's address, or an error naming the variable that should hold it.

    Read at task time and not at parse time: a DAG that raises while being imported takes the
    scheduler's whole parse with it, and reports as a broken Airflow rather than as one unset
    variable.
    """
    base = os.environ.get(TRACKING_URI_VARIABLE, "").rstrip("/")
    if not base:
        raise RuntimeError(
            f"{TRACKING_URI_VARIABLE} is unset in this container, so there is no tracking server "
            f"to write to. The compose file sets it on the airflow service; if this fires, that "
            f"service is running with an environment the committed file does not describe"
        )
    return base


def _post(base: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 -- http, to a service on the compose network
        f"{base}{API_ROOT}/{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read()
    parsed: dict[str, Any] = json.loads(body or b"{}")
    return parsed


def _get(base: str, path: str, query: dict[str, str]) -> dict[str, Any]:
    url = f"{base}{API_ROOT}/{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, method="GET")  # noqa: S310 -- as above
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read()
    parsed: dict[str, Any] = json.loads(body or b"{}")
    return parsed


def experiment_id(base: str) -> str:
    """Create the experiment, or find the one an earlier run of this DAG created.

    Creating unconditionally would make the second run of a smoke test fail, which is the
    idempotency property the rest of this repository spends its time on.
    """
    try:
        created = _post(base, "experiments/create", {"name": EXPERIMENT_NAME})
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if ALREADY_EXISTS not in detail:
            raise
    else:
        return str(created["experiment_id"])

    found = _get(base, "experiments/get-by-name", {"experiment_name": EXPERIMENT_NAME})
    return str(found["experiment"]["experiment_id"])


@dag(
    dag_id=DAG_ID,
    description="M0 smoke: prove Airflow can reach MLflow and MLflow can reach Postgres",
    # Triggered, never scheduled. This exists to be run deliberately -- by a reviewer or by the
    # integration tier -- and a schedule would fill the metadata database with proof of nothing.
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    tags=["m0", "smoke"],
    doc_md=__doc__,
)
def m0_smoke() -> None:
    @task
    def log_one_run() -> str:
        """Write one finished run with one param and one metric, and hand back its id."""
        base = tracking_base()
        started = int(time.time() * 1000)
        created = _post(
            base,
            "runs/create",
            {
                "experiment_id": experiment_id(base),
                "start_time": started,
                "tags": [
                    {"key": "mlflow.runName", "value": "m0-smoke"},
                    {"key": "airflow.dag_id", "value": DAG_ID},
                ],
            },
        )
        run_id = str(created["run"]["info"]["run_id"])

        _post(
            base, "runs/log-parameter", {"run_id": run_id, "key": PARAM_KEY, "value": PARAM_VALUE}
        )
        _post(
            base,
            "runs/log-metric",
            {
                "run_id": run_id,
                "key": METRIC_KEY,
                "value": METRIC_VALUE,
                "timestamp": started,
                "step": 0,
            },
        )
        # Left RUNNING, a crashed task and a finished one look identical in the UI, so the
        # integration tier could not tell "the write path works" from "the write path started".
        _post(
            base,
            "runs/update",
            {"run_id": run_id, "status": "FINISHED", "end_time": int(time.time() * 1000)},
        )
        return run_id

    log_one_run()


m0_smoke()
