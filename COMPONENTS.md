# Components

One component is one folder, one commit scope, one test scope, and one unit of correction. A defect
is fixed in the folder that owns it; nothing is fixed by rewriting history.

This repository is deliberately not laid out as a Python package with a `src/` tree. Its subject is
infrastructure, so its top level is the infrastructure: the Python here exists to test the
configuration, not to be imported by it.

Each row states the folder's contract as one line: what it takes in, and what it hands out. Unlike the
flagship repository, that contract is not repeated in a README inside each folder. These folders hold one
or two configuration files each, and a per-folder README at this size would be more inventory than
content -- two places to describe the same YAML, which is one more than can stay accurate.

| Folder | Contract (in → out) | Owns | Milestone | State |
|---|---|---|---|---|
| `compose/` | credentials from the environment, interpolated bare so no default can become a committed secret → seven named services with healthchecks, named volumes, declared limits, and two profiles | The local spine: Spark master and workers, MinIO, Postgres, MLflow, Airflow. Pinned tags, healthchecks, named volumes, declared limits, and the capped quickstart override. | M0 | built |
| `preflight/` | the environment, the runtime, and the fingerprint inside a kept volume → a pass, or a refusal naming the variable and what to do about it | The preconditions `up` depends on: a container runtime that answers, the seven credential variables present and non-placeholder, and whether a kept data volume was initialised with the credentials in the current `.env`. Not a documented step — a prerequisite, so it cannot be skipped (`docs/decisions/009`). | M0 | built |
| `tests/` | the compose files parsed as YAML data, both build entrypoints read as text, and the smoke DAG parsed with `ast` because Airflow lives in an image → pass or fail, with no container runtime needed outside the integration tier | The configuration contract: pinning, health gating, credential interpolation, the quickstart envelope, Makefile/PowerShell parity, what a DAG is allowed to import, the `down`/`up` idempotency cycle, and the M0 crossing asserted at both ends. | M0 | built |
| `docs/` (outside `decisions/`) | a clone and a machine that has never run any of this → a stack brought up, or a refusal traced to its cause | The narrative documentation: `architecture.md`, drawn before the code it describes, and `setup.md`, the single procedure from a bundle on a memory stick to a green integration tier, with troubleshooting keyed by symptom. Versioned with the code rather than carried alongside it, so a step that stops being true fails review with the change that made it untrue. | M0 | built |
| `docs/decisions/` | nothing → one record per starred milestone, committed with the code it explains | The decision records. Every starred milestone owes one, committed with the code it explains. | M0 | built |
| `airflow/dags/` | `MLFLOW_TRACKING_URI` from the compose file → one run in MLflow and one row in Postgres, proving the spine end to end. Mounted read-only so the scheduler cannot write to the checkout | Scheduler definitions, mounted read-only. Owns smoke coverage at M0 — the M0 gate closes on something crossing the spine, not on seven healthchecks — and real pipelines when a flagship has one worth scheduling. DAGs import Airflow and the standard library only, because the image has no install step (`docs/decisions/010`). | M0 | built |
| `postgres/init/` | the first boot of an empty data volume → the Airflow database beside the platform one, and a salted fingerprint of the credentials that built it. Runs once and never again, which is why `make down` keeps volumes | First-boot SQL, mounted read-only. Creates the Airflow database alongside the platform one and records what the volume was initialised with, so a later start can tell a kept volume from a matching one. | M0 | built |
| `images/` | `compose/` | Images the spine builds rather than pulls. One so far, and only because MLflow's published image ships neither of the drivers its own store flags accept (`docs/decisions/011`). Every `FROM` is pinned and a contract test reads the Dockerfile to check it. Multi-stage, non-root, SBOM and a CI scan step are M1 — what exists now is the minimum that lets M0 start. | M0 | built |
| `charts/` | — | Versioned Helm charts: Deployment, Service, Ingress, probes, HPA. No serving CRD (`docs/decisions/002`). | M2 | not started |
| `infra/` | — | Terraform for the cloud footprint, with a destroy step in the runbook. | M2 | not started |

## Deferred, and why

M3 (model registry and promotion), M4 (drift detection and retrain trigger) and M5 (canary and
rollback) are deferred until two real workloads exist to promote, monitor and roll back. The
reasoning is in `docs/decisions/001`. They land after the flagships, as dated additions.

## Commit order

Within a milestone, commits follow the order the components depend on each other:

1. `images/` — the compose file names the tag it builds, so the Dockerfile comes first.
2. `compose/` — nothing else can be tested until the spine exists.
3. `tests/` — the contract, committed with the configuration it constrains.
4. `preflight/` — guards a start, so it comes after there is something to start.
5. `airflow/dags/` — crosses the spine, so it comes after the spine is guarded.
6. `docs/decisions/` — committed in the same commit as the code each record explains.

Commit scope is the folder name: `feat(compose): …`, `test(compose): …`, `docs(decisions): …`.
