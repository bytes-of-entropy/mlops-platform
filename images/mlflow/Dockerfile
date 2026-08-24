# MLflow's published image installs MLflow and nothing else. A tracking server pointed at Postgres
# needs a DBAPI driver, and one pointed at S3-compatible storage needs an S3 client; the base image
# carries neither, so `mlflow server` exits at import and the container never reports healthy. Two
# packages are the entire delta -- see docs/decisions/011.
FROM ghcr.io/mlflow/mlflow:v2.13.0

# psycopg2-binary rather than psycopg2: the source distribution needs a compiler and libpq headers
# this image does not carry either, so building from source would trade one missing dependency for
# three. Both pins are exact, because an image built from a floating pin is not a pinned image.
RUN pip install --no-cache-dir \
        psycopg2-binary==2.9.9 \
        boto3==1.34.131
