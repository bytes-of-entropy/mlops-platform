"""The chart, installed on a real cluster, asserted against the milestone's own exit criteria.

M2 asks for four things — healthy pods, correct probes, an Ingress that answers, and an HPA that
scales under synthetic load — and every one of them is a claim about a running cluster that no
amount of parsing can settle. `test_chart_contract.py` and `test_chart_templates.py` read the chart
as text and catch the defects that are visible in text; this file is the tier where `helm install`
either works or does not.

**Why the assertions are end to end rather than "the object exists".** Record 015 exists because a
green M0 shipped an artifact root whose bucket had never been created: everything reported healthy,
and the first write would have failed, because nothing had walked that path. So `kubectl get
deploy` reporting Available is the weakest thing this file checks, not the strongest. The bucket is
confirmed by asking S3 for it from inside the pod that needs it, the Ingress by a request that
crosses it from outside the cluster, and the HPA by putting real CPU through the request path and
watching the replica count move.

**Its own cluster.** `tests/clusterops.py` explains the choice: `mlops-platform-tests`, created and
destroyed here, so a cluster an operator left running cannot decide whether this passes. The cost is
about eight minutes of cluster setup per run on the build machine, paid once for the module.

**Zero skips is the pass condition.** These are marked `cluster` as well as `integration` so a
machine without kind can exclude them by selection rather than by skipping — a skip that reads as a
pass is the failure mode the tier's rule exists to prevent. `make test` on the build machine runs
them; CI's compose job selects `integration and not cluster`.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any, cast

import pytest
import yaml

from tests.clusterops import TEST_RELEASE, Cluster
from tests.conftest import REPO_ROOT, requires_cluster, requires_local_credentials

pytestmark = [
    pytest.mark.integration,
    pytest.mark.cluster,
    requires_cluster,
    requires_local_credentials,
]

#: Every workload the chart installs, by the suffix the fullname template appends. All three,
#: because MLflow reporting Available while Postgres is still starting is a state that resolves
#: itself and proves nothing; MLflow Available *and* both dependencies Available is the real spine.
COMPONENTS = ("mlflow", "postgres", "minio")

#: kind publishes the ingress controller on the host's port 80 via `extraPortMappings`.
INGRESS_ORIGIN = "http://127.0.0.1"

#: How long to give the autoscaler. Its control loop recomputes every 15 seconds by default and
#: `scaleUp.stabilizationWindowSeconds` is 0, so a working setup moves inside a minute; the rest of
#: the budget is for metrics-server's own first scrape window, which is the slow part.
SCALE_DEADLINE_S = 240
METRIC_DEADLINE_S = 180

#: How many times to ask the Ingress before calling a status code the answer, and how long to
#: wait between. Three attempts over ten seconds distinguishes a controller that is still
#: wiring up from an endpoint that is genuinely absent, without turning a real failure into a
#: two-minute one.
REQUEST_ATTEMPTS = 3
REQUEST_BACKOFF_S = 5

#: Three pods, four threads each. Enough to exceed 70% of MLflow's 250m CPU request without being so
#: much load that the server stops answering and the readiness probe starts failing, which would
#: scale the Deployment down at exactly the moment the test is waiting for it to scale up.
LOAD_REPLICAS = 3
LOAD_THREADS = 4

#: `head_bucket` raises on a bucket that is absent or not readable with these credentials, so this
#: exits non-zero and `Cluster.check` turns that into a report. Reading the endpoint out of the
#: environment rather than naming it keeps the check honest about which MinIO the pod actually talks
#: to — a test that hardcoded the service name would pass against a pod configured to reach a
#: different one.
BUCKET_PRESENT = """
import os

import boto3

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
client.head_bucket(Bucket={bucket!r})
print("bucket present:", {bucket!r})
"""


def chart_values() -> dict[str, Any]:
    """The chart's own defaults, so this file holds no second copy of a name or a port."""
    path = pathlib.Path(REPO_ROOT, "charts", "mlops-platform", "values.yaml")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


VALUES = chart_values()
MLFLOW: dict[str, Any] = VALUES["mlflow"]
BUCKET: str = VALUES["minio"]["bucket"]
INGRESS_HOST: str = MLFLOW["ingress"]["host"]
MLFLOW_PORT: int = MLFLOW["service"]["port"]
TARGET_UTILISATION: int = MLFLOW["hpa"]["targetCPUUtilizationPercentage"]
MAX_REPLICAS: int = MLFLOW["hpa"]["maxReplicas"]


def appears_alone(value: str, haystack: str) -> bool:
    """Whether `value` occurs as a whole token rather than inside a longer identifier.

    A plain substring test fails this check on a name. `POSTGRES_DB=platform` is eight characters
    and a substring of `mlops-platform`, which appears in every label, image reference and object
    name the chart renders -- so the first version of this test reported a leaked credential on the
    first real cluster, and the credential was the release name. A leaked secret appears in JSON as
    its own quoted scalar, so requiring the neighbours not to be identifier characters keeps the
    check strong while removing that whole class of false positive.
    """
    return (
        re.search(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9_-])", haystack) is not None
    )


def through_the_ingress(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """One request to the published port, routed by the Host header rather than by DNS.

    The chart's host is `mlflow.localtest.me`, which public DNS does resolve to 127.0.0.1 — and
    relying on that would make a name server a dependency of this assertion and turn an offline
    build machine into a failing Ingress test. The header is what nginx routes on, so sending it
    explicitly tests the rule and nothing else.

    Retried, and the retry is not defensive padding. The first real run got 200 from `/health` and
    503 from the API seconds later, and 503 is what nginx returns when it has no ready endpoint as
    well as what an application can return for itself. A bounded retry settles whether it was a
    race; the reported body settles who sent it, because nginx's 503 is an HTML page and MLflow's
    would be JSON. Neither question was answerable from the first run, which recorded only a status
    code.
    """
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    last: dict[str, Any] = {}
    for attempt in range(REQUEST_ATTEMPTS):
        request = urllib.request.Request(  # noqa: S310 - fixed scheme, loopback origin
            f"{INGRESS_ORIGIN}{path}",
            data=body,
            headers={"Host": INGRESS_HOST, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return {
                    "status": response.status,
                    "body": response.read().decode("utf-8"),
                    "attempts": attempt + 1,
                }
        except urllib.error.HTTPError as error:
            last = {
                "status": error.code,
                # Read from the error, which carries the response body a bare status code discards.
                "body": error.read().decode("utf-8", errors="replace")[:600],
                "server": error.headers.get("Server", "unnamed"),
                "attempts": attempt + 1,
            }
        if attempt + 1 < REQUEST_ATTEMPTS:
            time.sleep(REQUEST_BACKOFF_S)
    raise AssertionError(
        f"{path} answered {last.get('status')} on all {REQUEST_ATTEMPTS} attempts. "
        f"Server header: {last.get('server')!r} -- nginx means no ready endpoint behind the "
        f"Ingress, anything else means the application answered. Body:\n{last.get('body')}"
    )


@pytest.fixture(scope="module")
def cluster() -> Iterator[Cluster]:
    """A cluster with the chart installed, torn down when the module finishes.

    `install()` passes `--wait`, so a workload that never becomes Available fails here rather than
    in a test, and it fails with the full report `Cluster.check` assembles — pods, events,
    deployments and the HPA — because by the time a test could look, the fixture has already raised.

    Torn down unconditionally, because a kept cluster is state that decides the next run, which is
    the whole reason this tier does not reuse the operator's. `KEEP_TEST_CLUSTER=1` opts out for
    someone debugging at the machine, and is deliberately not something CI or the runner sets.
    """
    site = Cluster()
    site.create()
    site.load_built_image()
    site.create_namespace_and_secret()
    site.install()
    try:
        yield site
    finally:
        if not os.environ.get("KEEP_TEST_CLUSTER"):
            site.destroy()


def test_every_workload_reports_available(cluster: Cluster) -> None:
    """The floor: all three Deployments satisfy the condition `helm --wait` waits on."""
    available = cluster.available_deployments()
    expected = {f"{TEST_RELEASE}-{component}" for component in COMPONENTS}
    assert expected <= available, (
        f"not Available: {sorted(expected - available)}; available: {sorted(available)}"
    )


def test_the_rendered_manifest_holds_no_credential(cluster: Cluster) -> None:
    """The strong form of the contract tier's grep: real values, real render.

    `test_chart_templates.py` can only assert that no template contains a literal, which a template
    assembling a URI from `.Values` would satisfy while still rendering a password into the
    manifest. This renders the chart and looks for each value in the operator's own `.env`, so a
    credential that reached the manifest by any route is found. Values shorter than eight characters
    are skipped, because a short value matches by coincidence and would fail this on a name.
    """
    rendered = json.dumps(cluster.rendered())
    env = pathlib.Path(REPO_ROOT, ".env").read_text(encoding="utf-8")
    secrets = {
        line.partition("=")[2].strip().strip("'\"")
        for line in env.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    leaked = sorted(
        value for value in secrets if len(value) >= 8 and appears_alone(value, rendered)
    )
    assert not leaked, (
        f"{len(leaked)} value(s) from .env appear in the rendered manifest ({leaked}); "
        "every credential must reach a container through secretKeyRef"
    )


def test_the_ingress_answers_the_health_path(cluster: Cluster) -> None:
    """The Ingress, the controller, the Service and the readiness probe's own endpoint, in one hop.

    A ClusterIP that answers proves the pod; only a request from outside proves the Ingress rule,
    the ingress class actually matching a controller, and kind's port mapping. All three are things
    the contract tier asserts the shape of and cannot assert the behaviour of.
    """
    try:
        response = through_the_ingress(MLFLOW["probes"]["readiness"]["path"])
    except (urllib.error.URLError, OSError) as error:
        raise AssertionError(
            f"the Ingress did not answer {INGRESS_ORIGIN} for host {INGRESS_HOST}: {error}\n\n"
            + json.dumps(cluster.diagnostics(), indent=2)
        ) from error
    assert response["status"] == 200, response


def test_the_tracking_api_writes_through_to_postgres(cluster: Cluster) -> None:
    """A create that must reach the backend store, then a read that must find it there.

    `/health` answers out of the process and says nothing about the database, so a chart that wired
    the backend URI wrongly would pass every check above this one. Creating an experiment writes a
    row through the `$(VAR)`-substituted connection string, and searching for it again reads that
    row back, which is the only way to tell a working credential from an unexercised one.

    Asked from inside the cluster first, and that ordering is deliberate. The first real run got 200
    from `/health` and 503 from this endpoint, which left two possible subjects: the Ingress and its
    endpoints, or MLflow itself. Asking the ClusterIP directly separates them before the assertion
    is made, so a failure names one side instead of leaving the next run to find out.
    """
    name = "kind-cluster-check"
    service = f"{TEST_RELEASE}-mlflow"
    inside = cluster.ask_from_inside(
        service,
        f"http://{service}:{MLFLOW_PORT}/api/2.0/mlflow/experiments/create",
        json.dumps({"name": f"{name}-inside"}),
    )
    assert "status 200" in inside, (
        "MLflow refused this request on its own ClusterIP, so the Ingress is not the subject:\n"
        f"{inside}"
    )

    created = through_the_ingress("/api/2.0/mlflow/experiments/create", {"name": name})
    assert "experiment_id" in created["body"], created

    listed = through_the_ingress("/api/2.0/mlflow/experiments/search", {"max_results": 100})
    assert name in listed["body"], listed
    assert f"s3://{BUCKET}" in listed["body"], (
        f"the experiment's artifact location is not in s3://{BUCKET}: {listed['body'][:400]}"
    )


def test_the_artifact_bucket_exists_because_the_init_container_made_it(cluster: Cluster) -> None:
    """Record 015's defect, asserted on the cluster this time.

    The initContainer is the chart's answer to a `post-install` hook Job, and its whole claim is
    that the bucket is present before MLflow's container starts. Asking S3 from inside the running
    pod checks the claim in the place and with the credentials that matter.
    """
    output = cluster.exec_script(f"{TEST_RELEASE}-mlflow", BUCKET_PRESENT.format(bucket=BUCKET))
    assert f"bucket present: {BUCKET}" in output, output


def test_the_hpa_reads_a_cpu_metric(cluster: Cluster) -> None:
    """Before any load: the autoscaler has a number, not `<unknown>`.

    Separated from the scaling test on purpose. An HPA with no metrics source never scales, and if
    that were only ever observed through the scaling test the report would say "it did not scale",
    which sends a reader looking at the load generator instead of at metrics-server. Named here, the
    failure says which of the two broke.
    """
    name = f"{TEST_RELEASE}-mlflow"
    reached = cluster.poll(
        lambda: cluster.hpa_utilisation(name) is not None, deadline_s=METRIC_DEADLINE_S
    )
    assert reached, (
        f"the HPA still reports no CPU metric after {METRIC_DEADLINE_S}s, so metrics-server is "
        "not serving this cluster and no amount of load will scale anything\n\n"
        + json.dumps(cluster.diagnostics(), indent=2)
    )


def test_the_hpa_scales_above_one_replica_under_load(cluster: Cluster) -> None:
    """The milestone's last criterion, and the only one that needs the chart's requests to be right.

    The compose spine sets CPU limits and no requests, which is why this chart sets both:
    utilisation is a percentage of the request, and an HPA with nothing to divide by reads
    `<unknown>` forever.
    So this test is also the evidence that the requests are real, and it is the reason record 024
    can say the chart does something compose cannot.

    The generator is stopped in `finally` rather than by a fixture, because it exists for one test
    and leaving it running would keep the Deployment scaled up while later modules ran.
    """
    name = f"{TEST_RELEASE}-mlflow"
    cluster.start_load(name, MLFLOW_PORT, LOAD_REPLICAS, LOAD_THREADS)
    try:
        scaled = cluster.poll(lambda: cluster.replicas(name) > 1, deadline_s=SCALE_DEADLINE_S)
        assert scaled, (
            f"{name} stayed at {cluster.replicas(name)} replica(s) after {SCALE_DEADLINE_S}s of "
            f"load from {LOAD_REPLICAS}x{LOAD_THREADS} clients; the HPA read "
            f"{cluster.hpa_utilisation(name)}% against a {TARGET_UTILISATION}% target\n\n"
            + json.dumps(cluster.diagnostics(), indent=2)
        )
        assert cluster.replicas(name) <= MAX_REPLICAS, (
            f"{name} has more than the HPA's maxReplicas of {MAX_REPLICAS}, so something other "
            "than the HPA is setting the replica count"
        )
    finally:
        # No assertion in here: a failing `finally` replaces the failure the test was reporting,
        # and `stop_load` already raises with a full report if the delete itself fails.
        cluster.stop_load()
