-- Airflow gets its own database in the same instance. Two logical databases, one
-- container: enough separation for the metadata to be restorable independently, without
-- a second Postgres eating a gigabyte of the quickstart envelope.
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
