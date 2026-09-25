"""MLflow's artifact root exists and accepts a write, asserted by round-tripping a real object.

This tier exists because of a defect a green M0 did not catch. MLflow was configured with
``--default-artifact-root s3://mlflow/`` and nothing anywhere created that bucket. Every test
passed, the stack was healthy, and the first ``log_artifact`` would have failed, because the smoke
path logs a param and a metric and both of those go to the Postgres-backed tracking store. The
artifact path had never been walked by anything.

So the assertion here is deliberately end to end rather than a check that a bucket exists. It logs
an artifact through the MLflow client, then reads the object back out of the store with boto3 and
compares the bytes. A bucket that exists but is unwritable, credentials that are accepted by the
tracking server but rejected by the object store, and an artifact root pointing somewhere other
than where the client writes are all failures this catches and a ``head_bucket`` would not.

One assertion here runs the other way round. A round trip proves the store accepts the credential
it was given; it cannot distinguish that from a store accepting anything at all, and the artifact
store this spine now runs does exactly that when its credentials do not reach it. So the last test
presents a credential that is definitely wrong and requires a refusal.

Run inside the MLflow container, through its own loopback and its own environment. That is where
the artifact write happens in the real path: the MLflow *client* writes to object storage directly
rather than streaming through the server, so testing from the host would exercise a different code
path than the one the DAG uses.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.conftest import requires_docker, requires_local_credentials
from tests.stackops import PAYLOAD, QUICKSTART, Stack, payload

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

result = {{"run_id": run_id, "keys": keys, "matched": matched, "body": body}}
print({PAYLOAD!r} + json.dumps(result))
"""

BUCKET_EXISTS = f"""
import json, os
import boto3

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
buckets = [entry["Name"] for entry in client.list_buckets().get("Buckets") or []]
print({PAYLOAD!r} + json.dumps(buckets))
"""

#: Deliberately not derived from the real credentials. Mutating the configured value would pass
#: against a store that compares nothing, which is the condition being tested for.
WRONG_ACCESS_KEY_ID = "not-the-configured-access-key-id"
WRONG_SECRET = "not-the-configured-secret"  # noqa: S105 (invalid on purpose; a refusal is the assertion)

REFUSES_WRONG_CREDENTIAL = f"""
import json, os
import boto3
from botocore.exceptions import ClientError

client = boto3.client(
    "s3",
    endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"],
    aws_access_key_id={WRONG_ACCESS_KEY_ID!r},
    aws_secret_access_key={WRONG_SECRET!r},
)
try:
    listing = client.list_objects_v2(Bucket={BUCKET!r})
except ClientError as error:
    outcome = {{
        "refused": True,
        "code": error.response["Error"]["Code"],
        "status": error.response["ResponseMetadata"]["HTTPStatusCode"],
    }}
else:
    outcome = {{
        "refused": False,
        "keys": [item["Key"] for item in listing.get("Contents") or []],
    }}
print({PAYLOAD!r} + json.dumps(outcome))
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
    buckets = payload(reported.stdout, "minio buckets")
    assert BUCKET in buckets, (
        f"the artifact root names s3://{BUCKET}/ and MinIO holds {buckets}, so either the "
        "provisioner did not run or it created something else"
    )


def test_an_artifact_round_trips_through_minio(running_stack: Stack) -> None:
    """The claim M0 could not make: something wrote to the artifact store and read it back."""
    reported = running_stack.check(
        "artifact round trip", "exec", "-T", "mlflow", "python", "-c", ROUND_TRIP
    )
    result: dict[str, Any] = payload(reported.stdout, "artifact round trip")

    assert result["matched"], (
        f"nothing under run {result['run_id']} ending in {ARTIFACT_NAME} appeared in "
        f"s3://{BUCKET}/; the bucket holds {result['keys']}, so the client wrote somewhere other "
        "than where the artifact root points"
    )
    assert result["body"] == PROBE_TEXT, (
        f"the artifact read back as {result['body']!r} rather than {PROBE_TEXT!r}, so the object "
        "store accepted the write and did not preserve it"
    )


def test_object_storage_refuses_a_wrong_credential(running_stack: Stack) -> None:
    """That the store authenticates at all, which every other test here would pass without.

    The same shape of defect as the missing bucket this file was written for, one level worse. The
    artifact store starts with no identities configured and, in that state, accepts any key offered
    to it; the two variables the compose file supplies are consulted only when its filer holds no
    configuration of its own, and its filer persists into the kept volume. So a stack whose
    credentials never reached the server, or whose volume carries an older identity, serves objects
    to anyone who asks -- and passes the round trip above, the healthcheck, the bucket check and the
    smoke DAG, because every one of those arrives holding a key the store was never going to check.

    Presenting a credential that is definitely wrong is the only assertion that separates
    "configured" from "enforced". It is written against the round trip's own bucket so that a
    refusal cannot be confused with a missing one.
    """
    reported = running_stack.check(
        "wrong credential", "exec", "-T", "mlflow", "python", "-c", REFUSES_WRONG_CREDENTIAL
    )
    outcome: dict[str, Any] = payload(reported.stdout, "wrong credential")

    assert outcome["refused"], (
        f"a deliberately wrong access key listed s3://{BUCKET}/ and was handed "
        f"{outcome.get('keys')}, so the artifact store authenticates nobody. Every other assertion "
        "in this file still passes in that state, which is what makes it worth its own test: check "
        "that the two credentials reached the container, and that the data volume does not carry "
        "an S3 identity from an earlier run that outranks them"
    )
