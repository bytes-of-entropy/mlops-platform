"""Create the buckets this spine's consumers are configured to write to, then exit.

Run as a one-shot before MLflow starts, so the server cannot come up healthy against an artifact
root that does not exist. That failure mode is the reason this file exists: MLflow was configured
with ``--default-artifact-root s3://mlflow/`` and nothing created the bucket, so every test passed
and the first artifact write would have failed.

**Why boto3 and not `mc`.** The first implementation ran `mc mb --ignore-existing` in the MinIO
image, which already ships `mc`. That image's `mc` rejected the invocation, printed its top-level
help into a pager and exited 1, which cost a full cycle on the build machine to learn. The same job
in boto3 has semantics that can be reasoned about in advance rather than discovered: exactly one
call, two documented error codes that mean "already there", and everything else raised. It also
needs no configuration file, no alias resolution and no TTY, three things the CLI wanted and none
of which this job needs.

The image is the one this repository already builds for MLflow, because that is where ``boto3``
already lives. A second Dockerfile carrying one dependency for six lines of code would be a second
thing to pin, rebuild and keep current, which is worse than one image with two roles.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError

#: The two codes S3 uses for "this bucket is already here and it is yours". Anything else is a real
#: failure and is raised: a refused connection, a rejected credential, a name S3 will not accept.
#: Catching more broadly is how a provisioner exits zero having created nothing.
ALREADY_PRESENT = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})


def ensure(client: Any, bucket: str) -> str:
    """Create one bucket if it is absent. Returns what happened, for the log."""
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code not in ALREADY_PRESENT:
            raise
        return "already present"
    return "created"


def main(argv: list[str]) -> int:
    buckets = argv[1:]
    if not buckets:
        print("ensure_buckets: no bucket named, so nothing was checked", file=sys.stderr)
        return 2

    endpoint = os.environ.get("MLFLOW_S3_ENDPOINT_URL")
    if not endpoint:
        print(
            "ensure_buckets: MLFLOW_S3_ENDPOINT_URL is unset, so there is no object store to "
            "provision. Refusing rather than defaulting to AWS.",
            file=sys.stderr,
        )
        return 2

    client = boto3.client("s3", endpoint_url=endpoint)
    for bucket in buckets:
        print(f"ensure_buckets: {bucket}: {ensure(client, bucket)} at {endpoint}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
