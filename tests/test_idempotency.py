"""`make down && make up` must be repeatable, and repeatable twice.

This is the integration half of the M0 gate. It needs two things the contract suite does
not (a container runtime and the local credentials) and skips, naming which one is
absent, where either is missing. The contract suite next to it covers the properties that
make idempotency possible; this covers whether it actually holds.

The stack it exercises is the capped quickstart, deliberately: idempotency is a property of the
smallest shape a reviewer can run, and proving it there proves it on the machine most likely to
be theirs. The full profile is covered by the smoke test beside this one.
"""

from __future__ import annotations

import pytest

from tests.conftest import requires_docker, requires_local_credentials
from tests.stackops import PAYLOAD, QUICKSTART, Stack, payload

pytestmark = [pytest.mark.integration, requires_docker, requires_local_credentials]

stack = Stack(QUICKSTART)

#: Its own bucket rather than the artifact root, so a surviving marker cannot be mistaken for a
#: surviving artifact, and so creating it exercises the write path a reviewer's first `up` takes.
MARKER_BUCKET = "idempotency"
MARKER_KEY = "marker"
MARKER_BODY = "persisted"

#: Both snippets run in the MLflow container and speak S3 over the network, rather than running a
#: client inside the store: the store image ships none, and the property under test is that the
#: volume kept the object, which is independent of where the request came from. Credentials and the
#: endpoint come from that container's own environment, so nothing here puts them in an argv.
WRITE_MARKER = f"""
import os
import boto3

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
names = [entry["Name"] for entry in client.list_buckets().get("Buckets") or []]
if {MARKER_BUCKET!r} not in names:
    client.create_bucket(Bucket={MARKER_BUCKET!r})
client.put_object(Bucket={MARKER_BUCKET!r}, Key={MARKER_KEY!r}, Body={MARKER_BODY!r}.encode())
"""

#: A missing bucket and a missing key raise the same class and mean different things, so the error
#: code comes back rather than being flattened into an absent body.
READ_MARKER = f"""
import json, os
import boto3
from botocore.exceptions import ClientError

client = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"])
try:
    body = client.get_object(Bucket={MARKER_BUCKET!r}, Key={MARKER_KEY!r})["Body"].read().decode()
except ClientError as error:
    outcome = {{"body": None, "code": error.response["Error"]["Code"]}}
else:
    outcome = {{"body": body, "code": None}}
print({PAYLOAD!r} + json.dumps(outcome))
"""


def test_down_then_up_reaches_the_same_healthy_set() -> None:
    """The second cycle must land on the same services, not a subset that happens to work."""
    first = stack.up()
    assert first, "nothing came up healthy on the first cycle"
    stack.down()
    second = stack.up()
    try:
        assert second == first, (
            f"second cycle differs: only-first={first - second}, only-second={second - first}"
        )
    finally:
        stack.down()


def test_up_is_safe_to_run_twice_without_a_down() -> None:
    """A repeated `up` is what happens in practice; it must be a no-op, not a conflict."""
    first = stack.up()
    second = stack.up()
    try:
        assert second == first
    finally:
        stack.down()


def test_state_survives_down_and_up() -> None:
    """`make down` keeps volumes, so an object written before it is readable after it."""
    stack.up()
    try:
        stack.check("marker write", "exec", "-T", "mlflow", "python", "-c", WRITE_MARKER)
        stack.down()
        stack.up()
        reported = stack.check("marker read", "exec", "-T", "mlflow", "python", "-c", READ_MARKER)
        outcome = payload(reported.stdout, "marker read")
        assert outcome["body"] == MARKER_BODY, (
            f"s3://{MARKER_BUCKET}/{MARKER_KEY} read back as {outcome['body']!r} rather than "
            f"{MARKER_BODY!r} (error code {outcome['code']}), so the down/up cycle did not keep "
            "what was written before it. NoSuchBucket means the volume itself was replaced; "
            "NoSuchKey means the volume survived and its contents did not"
        )
    finally:
        stack.down()
