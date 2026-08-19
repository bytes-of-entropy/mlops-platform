# Components

One component is one folder, one commit scope, one test scope, and one unit of correction. A defect
is fixed in the folder that owns it; nothing is fixed by rewriting history.

This repository is deliberately not laid out as a Python package with a `src/` tree. Its subject is
infrastructure, so its top level is the infrastructure: the Python here exists to test the
configuration, not to be imported by it.

| Folder | Owns | Milestone | State |
|---|---|---|---|
| `compose/` | The local spine: Spark master and workers, MinIO, Postgres, MLflow, Airflow. Pinned tags, healthchecks, named volumes, declared limits, and the capped quickstart override. | M0 | built |
| `tests/` | The configuration contract: pinning, health gating, credential interpolation, the quickstart envelope, Makefile/PowerShell parity, and the `down`/`up` idempotency cycle. | M0 | built |
| `docs/decisions/` | The decision records. Every starred milestone owes one, committed with the code it explains. | M0 | built |
| `airflow/dags/` | Scheduler definitions, mounted read-only. Empty until a flagship has a pipeline worth scheduling. | M1 | placeholder |
| `postgres/init/` | First-boot SQL, mounted read-only. Creates the Airflow database alongside the platform one. | M0 | built |
| `images/` | Multi-stage, non-root, pinned base images with an SBOM and a scan step in CI. | M1 | not started |
| `charts/` | Versioned Helm charts: Deployment, Service, Ingress, probes, HPA. No serving CRD (`docs/decisions/002`). | M2 | not started |
| `infra/` | Terraform for the cloud footprint, with a destroy step in the runbook. | M2 | not started |

## Deferred, and why

M3 (model registry and promotion), M4 (drift detection and retrain trigger) and M5 (canary and
rollback) are deferred until two real workloads exist to promote, monitor and roll back. The
reasoning is in `docs/decisions/001`. They land after the flagships, as dated additions.

## Commit order

Within a milestone, commits follow the order the components depend on each other:

1. `compose/` — nothing else can be tested until the spine exists.
2. `tests/` — the contract, committed with the configuration it constrains.
3. `docs/decisions/` — committed in the same commit as the code each record explains.

Commit scope is the folder name: `feat(compose): …`, `test(compose): …`, `docs(decisions): …`.
