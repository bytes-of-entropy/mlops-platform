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

## The same spine, on Kubernetes

`charts/mlops-platform` installs MLflow, Postgres and MinIO onto a cluster. It is a second way to start
three of the services above, not a replacement for the first: compose stays the local spine, and the
chart exists because the flagship repositories deploy onto a cluster and need a versioned release to
pin rather than a moving target.

- **Three components, not seven.** Spark and Airflow are deliberately absent. A plain `Deployment`
  misrepresents how either runs here — Spark wants `spark-submit --master k8s://` or an operator,
  Airflow's own chart is thousands of lines — and every criterion this milestone sets is demonstrable
  on the tracking core, which is a real workload rather than infrastructure with nothing running on it.
- **Postgres and MinIO are Deployments with `strategy: Recreate` and a PVC**, which is right for one
  replica and wrong for production. A StatefulSet buys ordinal identity and stable per-replica storage,
  and at one replica there is nothing to identify or to keep stable. `docs/decisions/024` says both
  halves of that plainly.
- **The chart holds no credential.** `values.yaml` names a Secret and its keys; the Secret is created
  from the same `.env` compose reads. MLflow's connection string is assembled at container start from
  `$(VAR)` references, which is Kubernetes' own substitution rather than Helm's, so the rendered
  manifest carries the literal `$(POSTGRES_PASSWORD)` and the value never enters a manifest at all.
- **The bucket is an initContainer, not a `post-install` hook.** A hook Job runs once per release and is
  absent on every reschedule; an initContainer re-checks before each pod's own container starts and
  blocks exactly the thing that needs it. `docs/decisions/015` is why that distinction is not academic.
- **The chart sets CPU requests, which the compose files do not.** HPA utilisation is a percentage of a
  container's request, so a workload with a limit and no request gives the autoscaler nothing to divide
  by. This is the one place the two spines genuinely differ in what they declare.
- **Nothing kind-specific is in a template.** The ingress class, every image and all resource numbers
  come from values, and `--kubelet-insecure-tls` lives in the cluster-setup target where it belongs.
  Portability to EKS is a claim this structure supports and nothing in this repository proves.

## What is not here yet

Terraform (M3). Registry, drift and canary are deferred; see `docs/decisions/001`.
