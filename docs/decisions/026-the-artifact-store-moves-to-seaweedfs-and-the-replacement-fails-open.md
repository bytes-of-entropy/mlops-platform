# 026: The artifact store moves to SeaweedFS, and the replacement fails open

- **Date:** 2026-09-24
- **Status:** accepted, and half-verified: see Consequences
- **Component:** `compose/`, `charts/mlops-platform/`, `tests/`
- **Milestone:** M2, surfaced as an R3 regression
- **Extends:** record 005 (a pin buys reproducibility, not availability), record 007 (a kept volume
  pins the first run's credentials), record 015 (a missing bucket survived a green M0), record 018
  (every pulled reference is pinned by digest), record 023 (the correction on mirroring)

## Context

Both CI jobs fail and `up` cannot start the spine. `minio/minio` has been withdrawn from Docker Hub,
and the digest pin in `compose/docker-compose.yml` went with it, because a digest names content
inside a repository and does not survive the repository being removed.

This is the second time, to the second publisher, in the same file. Record 005 was the first, and the
sentence it put in that file's header, that a pin buys reproducibility and not availability, was
written as a caution. It is now a measurement. Two of the five images this spine pulls have been
withdrawn by their publishers inside thirteen months, which is a base rate rather than an anecdote,
and it is the number that should inform how much the mirroring question in record 023 is worth.

The premise was checked rather than accepted, with controls, because a registry lookup fails for
several reasons and only one of them is withdrawal:

| probe | result | control run through the same code path |
| --- | --- | --- |
| `hub.docker.com/v2/repositories/minio/minio/` | `object not found` | `library/postgres` returns 200 with `status: active` |
| the pinned digest `sha256:14cea493...` | HTTP 401 | this spine's pinned `postgres` digest returns 200 |
| the `minio` namespace itself | alive, 20 repositories listed | the namespace is not the thing that was removed |
| `quay.io/api/v1/repository/minio/minio` | HTTP 401, `Requires authentication` | `prometheus/prometheus` returns JSON anonymously |

The Docker Hub half is decisive: the namespace answers, the controls answer, and the repository does
not. The quay half is consistent with withdrawal and is weaker evidence than it looks, because that
API answers 401 for a repository that is private and for one that is absent, and those two cannot be
told apart without credentials. It is recorded as consistent, not as confirmed.

## Decision

**The artifact store becomes `chrislusf/seaweedfs`, pinned at `4.47` by the digest of its OCI image
index**, `sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882`, which covers
`linux/amd64`, `arm64`, `arm` and `386` so that one digest is correct on a laptop and on a runner.
Apache-2.0, which matters here for the reason record 023's correction gives: the licence decides
whether the deletion insurance that record discusses is available at all, and MinIO's server being
AGPL-3.0 is precisely why 023 could not answer the mirroring question for it with a blanket yes.

Five decisions sit underneath that, and the last is the one worth the record.

**The service, the volume, the values key, the Secret key names and the component label keep saying
`minio`.** This change fixes a regression. Renaming the component is a refactor, it would change the
Deployment's `matchLabels` selector, which Kubernetes does not permit to be updated, and it would
therefore turn a `helm upgrade` into a delete and recreate. Those are separate consequences and they
belong to a separate change. The names are wrong on purpose and for one commit's duration, and this
paragraph is the record that they are wrong rather than overlooked.

**The S3 gateway listens on 9000, via `-s3.port=9000`, against the image's default of 8333.** Every
consumer in the spine and the chart already names 9000, as do the README, the guide and the
architecture diagram. Moving the port would have spread this change across all of them and bought
nothing, because the number is arbitrary on both sides.

**One process, started as `server -s3`.** That runs the master, the volume server, the filer and the
gateway together. The filer is not named on the command line because `-s3` starts it regardless,
which is visible at `weed/command/server.go:249`, and naming both would imply the gateway could be
had without one.

**Health is one endpoint, `/healthz`, probed twice in the chart.** MinIO published `live` and `ready`
as genuinely different questions and the chart was right to ask them separately. Here
`s3api_server.go:769-770` binds `/status` and `/healthz` to the same `StatusHandler`, so two paths
would assert the same thing twice and imply a distinction the implementation does not make. The two
probes remain, because readiness withdrawing an endpoint and liveness restarting a pod are still
different consequences drawn from the same signal.

**The credentials reach the server as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, and the
compose tier now asserts that a wrong credential is refused.** This is the part that is not a
migration detail.

### The replacement fails open, and nothing already in the suite could see it

MinIO refused to start without its root credentials. This server does the opposite, in two steps that
compose into one hazard.

Its own flag documentation states that by default any access key and secret key will be accepted. And
the environment variables above are a fallback: they are read only when no configuration file was
given **and no configuration is available from the filer**. The filer, in this topology, persists into
`/data`, which is the kept named volume.

So the failure mode is not a refused connection. It is an object store that answers `/healthz`, serves
the round trip in `tests/test_artifact_store.py`, satisfies the bucket check, passes the smoke DAG,
and authenticates nobody. Every one of those arrives holding a key that the store was never going to
check, so every one of them passes in exactly the state that should fail.

Two records already own half of this shape. Record 007 found that a kept volume pins the first run's
credentials, and the precedence rule above is that finding again, in a component replaced for
unrelated reasons. Record 015 found that a missing bucket survived a green M0 because nothing in the
smoke path touched object storage. This is both at once: a silent misconfiguration, in a component
whose green is not evidence.

`test_object_storage_refuses_a_wrong_credential` presents a credential that is definitely wrong and
requires a `ClientError`. It is the only assertion in the repository that separates "configured" from
"enforced", and it exists because against MinIO it would have been redundant.

### One check was quietly load-bearing and nearly went with the image

`CREDENTIAL_KEY` in `tests/test_compose_contract.py` matched `MINIO_ROOT_USER` through its
`ROOT_USER$` alternative. It does not match `AWS_ACCESS_KEY_ID`, which ends in neither `KEY` nor
`USER`, while its partner `AWS_SECRET_ACCESS_KEY` is matched. A literal access key id committed on
that line was therefore already caught by nothing, since the file-wide scan only looks for
`PASSWORD`, `SECRET` and `FERNET`. That gap was latent while a matched variable also existed and would
have gone live the moment MinIO's variable was deleted, so object storage would have had no checked
credential key at all. `KEY_ID` was added to the alternation in the same change, which is a net gain
rather than a restoration.

## Alternatives rejected

**Mirror the withdrawn digest into a registry we control.** The one honest answer, and unavailable:
the content is gone, and insurance has to be bought before the loss. Record 023's correction argued
that mirroring is ordinary practice and that record 012 exists because a publisher deleted a
catalogue, so the case for mirroring was already made and was not acted on. The base rate above is
the argument for acting on it now, for the images whose licences permit it.

**Pin an older MinIO tag.** The repository is gone, not a tag.

**Supply identities through `-s3.config`.** A JSON file holding an access key and its secret, on
disk, in a tree that is committed. Rejected on that alone, before reaching the question of whether it
would work better, which it would: a file outranks the environment and would close the precedence
hazard described above. That is a genuine cost of this decision and it is why the refusal test is not
optional.

**`weed mini` rather than `server -s3`.** It bundles an admin surface this spine has no use for and
whose ports were not verified, so it would trade a known shape for an unknown one.

**Keep the native 8333.** Churn through the compose file, the chart, the guide, the README and the
diagram, for a number that is arbitrary at both ends.

**Rename the component in this change.** A refactor inside a regression fix, and an immutable-selector
change inside a change nobody would look for one in.

## Prediction (recorded before the evidence)

Written on a machine with no Docker daemon, no `helm` and no cluster, so none of this is verified and
all of it is falsifiable on the build machine.

1. On a fresh volume, the environment credentials are honoured, and
   `test_object_storage_refuses_a_wrong_credential` passes on its first run.
2. On the `minio-data` volume as MinIO left it, the store initialises its own layout alongside MinIO's
   directories and ignores them, so the tier passes but the volume holds two dead layouts. The volume
   should be removed rather than reused.
3. boto3 reaches the gateway without `-domainName` being set, because path-style addressing is what
   that flag's absence leaves, and the existing round trip passes unchanged.
4. `ensure_buckets.py` succeeds, but not necessarily for its documented reason: record 015 bought its
   single call and two accepted codes against MinIO's responses, and `-autoCreateBucket` defaults on
   here, so the call may succeed trivially rather than through the path that was reasoned about. The
   provisioner stays either way, for record 015's argument about who holds permission to create.
5. `runAsNonRoot` with uid 1000 works, because the image creates a `seaweed` user at 1000 and
   `fsGroup: 1000` makes the volume writable to it. The entrypoint's own chown is skipped when it is
   not root, which is the branch this depends on not being needed.
6. The `sbom/` diff is confined to one image: MinIO's inventory removed, SeaweedFS's added, the other
   four untouched.
7. The advisory gate fires. A new base image means a new advisory set, and record 022 gates on
   identity rather than severity precisely so that this cannot pass silently.

## Deciding evidence

The withdrawal table above, with its controls. Beyond that, every claim about this image's behaviour
was read from its sources at tag `4.47` rather than at `master`, after a first pass did read `master`
and had to be discarded: `master` is not what the pinned digest contains, and checking the wrong
revision produces confident statements about software nobody is running.

What was read: `docker/Dockerfile.go_build` for the `curl` install and the uid, `docker/entrypoint.sh`
for the `shift` before `exec` that makes `command: ["server", "-s3", ...]` land correctly,
`weed/command/server.go` for `-s3.port`, the `-s3.config` flag and the filer implication, and
`weed/s3api/s3api_server.go` for the two health routes sharing one handler.

## What would change my mind

If the refusal test cannot be made to pass, this decision is wrong whatever its availability
properties, and the `-s3.config` file becomes the lesser evil against a secret manager rather than
against the environment. A store that cannot refuse is not a substitute for one that can.

If prediction 2 is wrong in the other direction, and a carried-over volume produces a *working* store
that ignores the supplied credentials, then the hazard is worse than described and the volume needs a
guard rather than a note.

## Consequences

- **Two CI jobs stay red until the build machine runs.** `supply.yml` compares `sbom/` against a
  regeneration, and the committed inventory still describes an image that cannot be pulled. `make
  sbom` and `make scan` need a daemon. This is a known red, not an unknown one.
- **The chart is `0.2.0-rc.1`.** Minor, because `minio.service.consolePort` is gone from `values.yaml`
  and a value a consumer could have been setting disappearing is an interface change. Pre-release,
  because no `helm template` and no cluster has seen it.
- **The MinIO console is gone.** Port 9001 and `MINIO_CONSOLE_HOST_PORT` are removed, and this server
  has no equivalent on its S3 gateway. Whether `weed admin` should be published in its place is a
  separate question with no evidence behind it yet.
- **Two extra listeners exist that this spine does not use.** 4.47 starts an Iceberg catalogue on 8181
  and a Lance namespace on 9101 by default. Neither is published and neither collides, so they are
  noted rather than disabled.
- **The names lie for one commit.** `minio`, `minio-data`, `minio-init`, `minioRootUser` and
  `app.kubernetes.io/component: minio` all name software that is no longer there. The rename is owed,
  it carries a forced delete and recreate of the Deployment, and it gets its own change.
- **The documentation is not swept.** Only statements that are now factually wrong about ports were
  corrected. `docs/setup.md`, `docs/architecture.md`, `COMPONENTS.md` and a dozen earlier records
  still describe MinIO, and they should be corrected once the predictions above are scored, so that
  they describe what happened rather than what was planned.
