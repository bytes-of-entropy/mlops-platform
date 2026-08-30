# MLflow's published image installs MLflow and nothing else. A tracking server pointed at Postgres
# needs a DBAPI driver, and one pointed at S3-compatible storage needs an S3 client; the base image
# carries neither, so `mlflow server` exits at import and the container never reports healthy. Two
# packages are the entire delta; see docs/decisions/011.
#
# Pinned by digest as well as by tag. The tag is a pointer its publisher can move; the digest is
# the bytes. Both are kept because the tag is what a reader recognises and the digest is what a
# build resolves, and a digest with no tag beside it is unreadable. See docs/decisions/018.
FROM ghcr.io/mlflow/mlflow:v2.13.0@sha256:47c5c26d06a4edadab1a7c10a4c9d3653427a3173da1e771e2b8efd7e82695af

# psycopg2-binary rather than psycopg2: the source distribution needs a compiler and libpq headers
# this image does not carry either, so building from source would trade one missing dependency for
# three. Both pins are exact, because an image built from a floating pin is not a pinned image.
RUN pip install --no-cache-dir \
        psycopg2-binary==2.9.9 \
        boto3==1.34.131

# The bucket provisioner runs as a one-shot from this same image, because this is where boto3 already
# is. A second image carrying one dependency for one script would be a second thing to pin and
# rebuild. See docs/decisions/015.
#
# Copied read-only and owned by root: the account the container ends as does not need to write to a
# script it only executes, and a one-shot that can rewrite itself has more privilege than its job.
COPY --chmod=0444 ensure_buckets.py /opt/ensure_buckets.py

# The published MLflow image runs as root and adds nothing to change that, so the tracking server, the
# provisioner that shares this image, and anything either executes all run as uid 0. On this spine that
# is not an exploit; it is the default that turns one container escape into a host compromise.
#
# A named account rather than a bare `USER 1000`: a uid with no passwd entry produces confusing failures
# in anything that looks up its own identity, and `mlflow` says what it is where a number says what it
# happens to be. No login shell and no password, because nothing here logs in. See
# docs/decisions/017, which also records why this image is not rebuilt multi-stage from a slim base.
RUN groupadd --gid 10001 mlflow \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mlflow
USER mlflow
