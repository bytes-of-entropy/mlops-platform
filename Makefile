# Canonical entrypoint. CI runs these targets; make.ps1 mirrors them on Windows and a
# test asserts the two do not drift.

# --project-directory is not decoration. Without it, compose takes the project directory from
# the directory of the first -f file, which is compose/, so the default .env lookup becomes
# compose/.env and every relative bind mount resolves under compose/ too. The .env then goes
# unread while sitting in plain sight, and ./postgres/init resolves to a path that does not
# exist, which Docker creates as an empty directory rather than refusing. Anchoring the project
# directory at the repository root is what makes both paths mean what they read as.
COMPOSE      := docker compose --project-directory . -f compose/docker-compose.yml
COMPOSE_QS   := docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.quickstart.yml
PY           := .venv/bin/python
BOOTSTRAP_PY := python3
ifeq ($(OS),Windows_NT)
PY           := .venv/Scripts/python.exe
BOOTSTRAP_PY := py -3
endif

# ``--wait`` on its own waits forever. A service that never reports healthy then hangs the
# job until something outside this repository kills it, which loses the compose logs that
# would have said why. Bounded, it exits nonzero and ``make logs`` still works.
WAIT_TIMEOUT := 300

# Two cataloguers, run as containers so a reviewer installs nothing to reproduce a scan. Both write
# into $(SBOM_DIR) through a bind mount rather than through a shell redirect: the Windows mirror
# cannot redirect a JSON stream without deciding an encoding for it, and the two entrypoints
# producing byte-different documents from the same image would defeat the point.
#
# `?=`, not `:=`: the committed value is the default and the environment can override it, which is
# what makes an exploratory scan possible without editing a tracked file. `SCAN_FAIL_ON=none` is the
# one that matters -- the first scan of an image nobody has scanned wants the whole finding table,
# not a gate that stops at the first High. A mirror test asserts make.ps1 honours all five.
#
# GRYPE_DB_VOLUME is a named volume for the vulnerability database. Without it every invocation
# downloads the whole database again, because `--rm` discards the container filesystem: six
# documents, six downloads. The cache directory is named explicitly rather than left to the image's
# default, so a change of base image cannot move it silently.
#
# Both tools are digest-pinned, and both carry an EXPIRY, which no other pin in this repository has.
# A scanner is not like an image. An image pinned to old bytes is old and still works; a scanner is
# only as good as a vulnerability database that must be fresh by definition, and its publisher
# retires the database schema that old versions speak. The first pin here was on the wrong side of
# such a retirement, so grype refused to run at all -- correctly, and only on a machine with a
# daemon, which is the worst place for a laptop-checkable fact to hide. The expiry is how a test
# says so without one. Record 020 argues it; renewing means the version, the digest and this date,
# edited together.
# SUPPLY_TOOLS_EXPIRE: 2027-02-28
SYFT            ?= anchore/syft:v1.51.1@sha256:95fe0835e5bebc6f8b1f8acef68d47d63d594ef4c0f25c097ff853b23cbac74c
GRYPE           ?= anchore/grype:v0.118.0@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7
SBOM_DIR        ?= sbom
GRYPE_DB_VOLUME ?= mlops-platform-grype-db

# Where a published image goes. The owner is a variable because it is the one value here that belongs
# to a person rather than to the project, and the path is nested under the repository name so a reader
# of `ghcr.io/<owner>/mlops-platform/mlflow` can tell which repository produced it.
GHCR_OWNER      ?= bytes-of-entropy
GHCR_IMAGE      ?= ghcr.io/$(GHCR_OWNER)/mlops-platform/mlflow
MLFLOW_TAG      ?= 2.22.4

# The cluster the chart is developed against, and the three things kind does not bring with it.
#
# Pinned like everything else here, and for the reason record 020 spells out: a version chosen from
# memory rather than from a registry is how the scanner ended up two schema retirements behind. These
# four came from the projects' own release metadata.
#
# The node image is the one kind v0.33.0 publishes as its default. It is pinned *with* its digest
# because the node image and the kind binary are a matched pair -- a newer kind expects a newer node --
# so this is the pin to move when the kind version moves, and not before.
KIND_CLUSTER    ?= mlops-platform
KIND_CONFIG     ?= charts/kind-cluster.yaml
KIND_NODE_IMAGE ?= kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
METRICS_SERVER  ?= v0.9.0
INGRESS_NGINX   ?= controller-v1.15.1

CHART           ?= charts/mlops-platform
RELEASE         ?= mlops-platform
K8S_NAMESPACE   ?= mlops

.PHONY: help setup test lint fmt hooks check doctor build push sbom scan-report scan scan-accept chart-lint kind-up kind-deploy kind-down up up-quickstart down clean reset ps logs config

help:
	@echo "setup           create .venv and install dev dependencies"
	@echo "test            run the test suite"
	@echo "lint            formatting, ruff and mypy, changing nothing"
	@echo "hooks           run every pre-commit hook over the whole tree"
	@echo "check           everything the gate requires: lint, hooks, test"
	@echo "doctor          check the machine can start the stack, and say what is wrong"
	@echo "build           build the one image in the spine, without starting anything"
	@echo "push            push that one image to $(GHCR_IMAGE), and nothing else"
	@echo "sbom            catalogue every image and write the reviewable inventories"
	@echo "scan-report      scan every SBOM and print what was found, gating on nothing"
	@echo "scan            the same scan, failing on an advisory not in the baseline"
	@echo "scan-accept     rewrite the baselines from the current scan, as a diff to review"
	@echo "chart-lint      lint and render the chart, without a cluster"
	@echo "kind-up         create the kind cluster, with metrics-server and an ingress"
	@echo "kind-deploy     kind-up, then install the chart and wait for it"
	@echo "kind-down       delete the kind cluster"
	@echo "up              start the full spine (all services)"
	@echo "up-quickstart   start the 4 GB / 2 CPU reviewer profile"
	@echo "down            stop and remove containers, KEEP volumes"
	@echo "clean           stop and remove containers AND volumes"
	@echo "reset           clean, then start the full spine from nothing"

setup:
	$(BOOTSTRAP_PY) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	# The hook config is committed; the installed hook is not, so every clone installs it once.
	# Without this line the config is decoration, which is what it was. An extracted tarball has
	# no .git to install into, which is not an error, and CI runs the hooks either way.
	@if [ -d .git ]; then $(PY) -m pre_commit install; else \
	  echo "no .git here, so no hook was installed; the CI hooks job runs them regardless"; fi

test:
	$(PY) -m pytest

# --check, not a reformat: a gate that fixes what it finds cannot fail, and a target that
# silently rewrites files is the wrong thing to run in CI. ``make fmt`` is the one that writes.
lint:
	$(PY) -m ruff format --check .
	$(PY) -m ruff check .
	$(PY) -m mypy

fmt:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

# --all-files, not the staged set: an installed hook only ever sees what a commit touched, so a
# file that drifted before the hook existed stays drifted until something reads the whole tree.
hooks:
	$(PY) -m pre_commit run --all-files

# What CI runs, and the one target to run before pushing.
check: lint hooks test

# A runbook step is a hope; a prerequisite is a guarantee. Every failure this repository has
# shipped so far was a stack that started and was wrong: an unread .env, an init directory
# mounted from the wrong place, a login the image was never told to create. The doctor is that
# knowledge as a program, and it runs before the two targets that would otherwise hide it.
doctor:
	$(PY) -m preflight

# `up` builds too, so this target is not a prerequisite of anything; it exists so a build can be
# paid for outside a timed window. The integration tier bounds every compose call it makes, and a
# cold build plus a cold pull is minutes of that budget spent on work that is identical every time.
build:
	$(COMPOSE) --profile full build

# The image list comes from `supply.images`, not from `compose config --images`. The obvious tool
# reports the profiles it was given and has already left `apache/airflow` out of this list once;
# a cataloguer fed a short list writes an inventory short in the same way, which then reads as a
# clean bill of health. `supply.images` takes the `image` keys themselves, so it cannot omit a
# profiled service, it sorts and deduplicates, and it needs no daemon to answer.
#
# The digest is dropped from the filename and the tag kept, so a committed inventory is named
# after something a reader recognises; two images differing only by digest cannot both appear in
# one compose file, so nothing collides. Run `build` first: the one image built here has to exist
# locally before there is anything to catalogue.
sbom:
	@mkdir -p $(SBOM_DIR)
	@for image in $$($(PY) -m supply.images); do \
	  name=$$(echo "$$image" | sed 's/@.*//; s#[/:]#_#g'); \
	  echo "cataloguing $$image"; \
	  docker run --rm \
	    -v /var/run/docker.sock:/var/run/docker.sock \
	    -v "$$PWD/$(SBOM_DIR):/out" \
	    $(SYFT) "$$image" -o "spdx-json=/out/$$name.spdx.json" || exit 1; \
	  $(PY) -m supply.inventory \
	    "$(SBOM_DIR)/$$name.spdx.json" "$(SBOM_DIR)/$$name.packages.txt" || exit 1; \
	done

# `scan-report` scans and says what it found. `scan` is the same work plus the gate, which is why it
# depends on it rather than repeating it, and `scan-accept` is the same work plus the opposite of the
# gate. One place where a document is scanned, three things to do with the answer.
#
# Reading the SBOM rather than the image is what makes a finding traceable to a committed line. Two
# outputs from one pass: `table` for a person reading the log, `json` for the gate, because parsing the
# table would mean owning a column layout nobody promised.
scan-report:
	@ls $(SBOM_DIR)/*.spdx.json >/dev/null 2>&1 || \
	  { echo "no SBOMs in $(SBOM_DIR); run 'make sbom' first"; exit 1; }
	@docker run --rm -v $(GRYPE_DB_VOLUME):/db -e GRYPE_DB_CACHE_DIR=/db \
	  $(GRYPE) db update || \
	  { echo "the vulnerability database could not be fetched; see docs/decisions/020"; exit 1; }
	@docker run --rm -v $(GRYPE_DB_VOLUME):/db -e GRYPE_DB_CACHE_DIR=/db \
	  $(GRYPE) db status || \
	  { echo "the vulnerability database will not load; see docs/decisions/020"; exit 1; }
	@for document in $(SBOM_DIR)/*.spdx.json; do \
	  name=$$(basename $$document .spdx.json); \
	  echo "scanning $$name"; \
	  docker run --rm -v "$$PWD/$(SBOM_DIR):/sbom" \
	    -v $(GRYPE_DB_VOLUME):/db -e GRYPE_DB_CACHE_DIR=/db \
	    $(GRYPE) "sbom:/sbom/$$name.spdx.json" \
	    -o table -o "json=/sbom/$$name.findings.json" || exit 1; \
	done

# The gate is `supply.findings`, not `--fail-on`. After record 021 the residue is 138 Critical and 870
# High with no fix inside the current major line, so a severity threshold fails identically every run
# and says nothing. What fails a build here is an advisory *identifier* absent from the committed
# baseline for that image, which is a thing somebody can act on. Record 022 argues it.
#
# Every document is compared before anything fails, so one new advisory in the first image does not
# hide three in the last.
scan: scan-report
	@failed=""; \
	for document in $(SBOM_DIR)/*.spdx.json; do \
	  name=$$(basename $$document .spdx.json); \
	  $(PY) -m supply.findings \
	    "$(SBOM_DIR)/$$name.known.txt" "$(SBOM_DIR)/$$name.findings.json" \
	    || failed="$$failed $$name"; \
	done; \
	if [ -n "$$failed" ]; then \
	  echo "unbaselined advisories in:$$failed"; exit 1; \
	fi

# Deliberate, and a separate target for that reason: it rewrites every baseline from the current scan,
# so the record of what changed is the git diff and the review is reading it. A `--force` on `scan`
# would have been one keystroke from accepting whatever appeared.
scan-accept: sbom scan-report
	@for document in $(SBOM_DIR)/*.spdx.json; do \
	  name=$$(basename $$document .spdx.json); \
	  $(PY) -m supply.findings --accept \
	    "$(SBOM_DIR)/$$name.known.txt" "$(SBOM_DIR)/$$name.findings.json" || exit 1; \
	done
	@echo "review the diff in $(SBOM_DIR)/*.known.txt before committing it"

# Pushes exactly one image: the one this repository builds. The other five are somebody else's, and
# copying them under this account would republish artifacts this project did not make and cannot
# vouch for -- while also making the spine depend on a mirror of a mirror.
#
# `build` first, declared rather than assumed, because pushing a tag no build produced is the one way
# this target can publish something other than what it claims. Login is deliberately not handled here:
# a credential belongs in the operator's session, never in a file this repository could read, and
# `docker push` failing on an anonymous session is a clear enough message.
#
# The digest is printed afterwards because that is the thing worth recording. A tag says what to pull
# and a digest says what arrived, and record 023 keeps them together with the commit.
push: build
	@docker image inspect mlops-platform/mlflow:$(MLFLOW_TAG) >/dev/null 2>&1 || \
	  { echo "mlops-platform/mlflow:$(MLFLOW_TAG) is not built; run 'make build'"; exit 1; }
	docker tag mlops-platform/mlflow:$(MLFLOW_TAG) $(GHCR_IMAGE):$(MLFLOW_TAG)
	docker push $(GHCR_IMAGE):$(MLFLOW_TAG)
	@echo ''
	@echo 'pushed, at this digest -- record it against the commit, see docs/decisions/023:'
	@docker image inspect --format '{{index .RepoDigests 0}}' $(GHCR_IMAGE):$(MLFLOW_TAG)

# Everything about the chart that does not need a cluster. `helm lint` reads the chart; `helm template`
# renders it and is the stronger check of the two, because lint accepts a template that renders to
# nothing. The rendered output goes to a file so a reader can look at what was actually produced.
#
# The contract tier asserts far more than this about the chart and needs no helm at all, which is why
# it runs on every machine and this runs where helm is.
chart-lint:
	helm lint $(CHART)
	helm lint $(CHART) --values $(CHART)/values-quickstart.yaml
	@mkdir -p .rendered
	helm template $(RELEASE) $(CHART) > .rendered/$(RELEASE).yaml
	@echo "rendered to .rendered/$(RELEASE).yaml"

# The cluster, plus the two things kind does not ship that this chart needs.
#
# metrics-server is what an HPA reads. Without it the autoscaler reports <unknown> forever, which looks
# like a broken HPA and is a missing component. `--kubelet-insecure-tls` is needed because kind's
# kubelet serving certificate is not signed by a CA the cluster trusts; it is a fact about kind, which
# is why it is here and not in the chart, and it is exactly what EKS does not need.
#
# ingress-nginx answers the Ingress. Its kind-specific manifest schedules onto the node labelled
# ingress-ready=true, which $(KIND_CONFIG) sets.
kind-up:
	@kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)" || \
	  kind create cluster --name $(KIND_CLUSTER) --config $(KIND_CONFIG) \
	    --image $(KIND_NODE_IMAGE)
	kubectl --context kind-$(KIND_CLUSTER) apply -f \
	  https://github.com/kubernetes-sigs/metrics-server/releases/download/$(METRICS_SERVER)/components.yaml
	kubectl --context kind-$(KIND_CLUSTER) -n kube-system patch deployment metrics-server \
	  --type=json -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl --context kind-$(KIND_CLUSTER) apply -f \
	  https://raw.githubusercontent.com/kubernetes/ingress-nginx/$(INGRESS_NGINX)/deploy/static/provider/kind/deploy.yaml
	kubectl --context kind-$(KIND_CLUSTER) -n ingress-nginx wait --for=condition=available \
	  deployment/ingress-nginx-controller --timeout=300s
	kubectl --context kind-$(KIND_CLUSTER) -n kube-system wait --for=condition=available \
	  deployment/metrics-server --timeout=300s

# The chart, on that cluster.
#
# `kind load` is not optional: the one image built here exists only in the local daemon, and a kind
# node is a separate container with its own image store that cannot pull `mlops-platform/mlflow` from
# anywhere. Without this the pod sits in ImagePullBackOff naming an image that `docker images` shows.
#
# The Secret is created from `.env`, the same file compose reads, and never from the chart. `--from-env-file`
# rather than repeated `--from-literal` so no credential reaches the command line, where it would be
# visible in the process table and in shell history. `--dry-run=client | apply` so re-running is safe.
kind-deploy: kind-up build
	@test -f .env || \
	  { echo ".env is missing; section 4 of docs/setup.md says how to write one"; exit 1; }
	kind load docker-image --name $(KIND_CLUSTER) mlops-platform/mlflow:$(MLFLOW_TAG)
	kubectl --context kind-$(KIND_CLUSTER) create namespace $(K8S_NAMESPACE) \
	  --dry-run=client -o yaml | kubectl --context kind-$(KIND_CLUSTER) apply -f -
	kubectl --context kind-$(KIND_CLUSTER) -n $(K8S_NAMESPACE) create secret generic \
	  mlops-platform-credentials --from-env-file=.env \
	  --dry-run=client -o yaml | kubectl --context kind-$(KIND_CLUSTER) apply -f -
	helm --kube-context kind-$(KIND_CLUSTER) upgrade --install $(RELEASE) $(CHART) \
	  --namespace $(K8S_NAMESPACE) --wait --timeout $(WAIT_TIMEOUT)s
	kubectl --context kind-$(KIND_CLUSTER) -n $(K8S_NAMESPACE) get pods

# Deletes the cluster and everything in it, which is the whole point: a kind cluster is disposable and
# nothing in it is state anybody should keep. The compose spine's volumes are the ones that matter and
# this does not touch them.
kind-down:
	kind delete cluster --name $(KIND_CLUSTER)

up: doctor
	$(COMPOSE) --profile full up -d --build --wait --wait-timeout $(WAIT_TIMEOUT)

up-quickstart: doctor
	$(COMPOSE_QS) up -d --build --wait --wait-timeout $(WAIT_TIMEOUT)

down:
	$(COMPOSE) --profile full down --remove-orphans

clean:
	$(COMPOSE) --profile full down --remove-orphans --volumes

# Two steps an operator was already running by hand, named once. Still explicitly asked for: the
# doctor refuses a mismatched volume and says to run this, which is not the same as a start that
# quietly destroys state to get itself going. `clean` first, so the recovery cannot half-happen.
reset: clean up

ps:
	$(COMPOSE) --profile full ps

logs:
	$(COMPOSE) --profile full logs --tail=100

config:
	$(COMPOSE) --profile full config
