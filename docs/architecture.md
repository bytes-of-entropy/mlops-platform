# Architecture

Drawn before the code it describes, which is the point of drawing it.

```
                    ┌──────────────────────────────────────────────┐
                    │  make up            make up-quickstart       │
                    │  full profile       capped profile           │
                    │  ~20 GiB / 9 CPU    3.8 GiB / 2.0 CPU        │
                    └───────────────────┬──────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                               │                               │
┌───────▼────────┐            ┌─────────▼─────────┐          ┌──────────▼─────────┐
│  spark-master  │◄──────────►│  spark-worker-1   │          │  airflow           │
│  :8080 UI      │            │  spark-worker-2   │          │  (full profile)    │
│  :7077 submit  │            │  (2nd = full)     │          │  :8082 UI          │
└───────┬────────┘            └───────────────────┘          └──────────┬─────────┘
        │                                                               │
        │  reads and writes tables                                      │  metadata
        │                                                               │
┌───────▼────────────────────┐                              ┌───────────▼─────────┐
│  minio  :9000 / :9001      │◄─── artifacts ───────────────┤  mlflow  :5000      │
│  S3 API, stands in for S3  │                              │  tracking server    │
└────────────────────────────┘                              └───────────┬─────────┘
                                                                        │  backend store
                                                            ┌───────────▼─────────┐
                                                            │  postgres :5432     │
                                                            │  platform, airflow  │
                                                            └─────────────────────┘
```

## What each boundary is for

- **MinIO is the S3 seam.** Everything downstream speaks the S3 API against an endpoint URL, so the
  same code runs against real S3 by changing one environment variable and nothing else. That is the
  whole reason the local stack is worth building rather than reading about.
- **MLflow's backend store is Postgres, not SQLite.** SQLite works until two processes write, and the
  first thing a real pipeline does is write from two processes.
- **Airflow shares the Postgres instance in a separate logical database.** Two containers would buy
  restorability this repository does not yet need and cost a gigabyte the quickstart cannot spare.
- **Health gating, not start gating.** Every `depends_on` waits for `service_healthy`, which is why
  `up --wait` returning means the stack is usable rather than merely created.

## What is not here yet

Images (M1), Helm charts (M2), Terraform (M3). Registry, drift and canary are deferred; see
`docs/decisions/001`.
