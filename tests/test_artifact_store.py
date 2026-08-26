"""MLflow's artifact root exists and accepts a write, asserted by round-tripping a real object.

This tier exists because of a defect a green M0 did not catch. MLflow was configured with
``--default-artifact-root s3://mlflow/`` and nothing anywhere created that bucket. Every test
passed, the stack was healthy, and the first ``log_artifact`` would have failed, because the smoke
path logs a param and a metric and both of those go to the Postgres-backed tracking store. The
artifact path had never been walked by anything.

So the assertion here is deliberately end to end rather than a check that a bucket exists. It logs
an artifact through the MLflow client, then reads the object back out of MinIO with boto3 and
compares the bytes. A bucket that exists but is unwritable, credentials that are accepted by the
tracking server but rejected by the object store, and an artifact root pointing somewhere other
than where the client writes are all failures this catches and a ``head_bucket`` would not.

Run inside the MLflow container, through its own loopback and its own environment. That is where
the artifact write happens in the real path: the MLflow *client* writes to object storage directly
rather than streaming through the server, so testing from the host would exercise a different code
path than the one the DAG uses.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import requires_docker, requires_local_credentials
from tests.stackops import QUICKSTART, Stack

pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]

#: The bucket named by `--default-artifact-root` in the compose file.
BUCKET = "mlflow"

EXPERIMENT_NAME = "artifact-store-check"
ARTIFACT_NAME = "probe.txt"
#: Content chosen to be worth comparing: an empty or single-character body would pass against a
#: store that silently truncates.
PROBE_TEXT = "artifact store round trip, asserted rather than assumed"

#: `list_objects_v2` against a bucket that does not exist raises rather than returning nothing,
#: which is the failure this file was written for and is worth keeping distinguishable from an
#: empty bucket.
ROUND_TRIP = f"""
import json, os
import boto3, mlflow

mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment({EXPERIMENT_NAME!r})
with mlflow.start_run() as active:
    mlflow.log_text({PROBE_TEXT!r}, {ARTIFACT_NAME!r})
    run_id = active.info.run_id

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
listing = client.list_objects_v2(Bucket={BUCKET!r})
keys = [item["Key"] for item in listing.get("Contents") or []]
matched = [key for key in keys if run_id in key and key.endswith({ARTIFACT_NAME!r})]
body = None
if matched:
    body = client.get_object(Bucket={BUCKET!r}, Key=matched[0])["Body"].read().decode()

print(json.dumps({{"run_id": run_id, "keys": keys, "matched": matched, "body": body}}))
"""

BUCKET_EXISTS = """
import json, os
import boto3

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
buckets = [entry["Name"] for entry in client.list_buckets().get("Buckets") or []]
print(json.dumps(buckets))
"""

stack = Stack(QUICKSTART)


@pytest.fixture(scope="module")
def running_stack() -> Iterator[Stack]:
    stack.up()
    try:
        yield stack
    finally:
        stack.down()


def test_the_provisioner_created_the_bucket_before_mlflow_started(running_stack: Stack) -> None:
    """Also the only direct evidence that the one-shot ran at all.

    MLflow is gated on `minio-init` completing, so a healthy MLflow already implies the
    provisioner exited zero. This asserts the thing it was supposed to *do*, which is a different
    claim: a provisioner that exits zero having created nothing would satisfy the gate.
    """
    reported = running_stack.check(
        "minio buckets", "exec", "-T", "mlflow", "python", "-c", BUCKET_EXISTS
    )
    buckets = json.loads(reported.stdout)
    assert BUCKET in buckets, (
        f"the artifact root names s3://{BUCKET}/ and MinIO holds {buckets}, so either the "
        "provisioner did not run or it created something else"
    )


def test_an_artifact_round_trips_through_minio(running_stack: Stack) -> None:
    """The claim M0 could not make: something wrote to the artifact store and read it back."""
    reported = running_stack.check(
        "artifact round trip", "exec", "-T", "mlflow", "python", "-c", ROUND_TRIP
    )
    result: dict[str, Any] = json.loads(reported.stdout)

    assert result["matched"], (
        f"nothing under run {result['run_id']} ending in {ARTIFACT_NAME} appeared in "
        f"s3://{BUCKET}/; the bucket holds {result['keys']}, so the client wrote somewhere other "
        "than where the artifact root points"
    )
    assert result["body"] == PROBE_TEXT, (
        f"the artifact read back as {result['body']!r} rather than {PROBE_TEXT!r}, so the object "
        "store accepted the write and did not preserve it"
    )
