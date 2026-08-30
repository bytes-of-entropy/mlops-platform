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
SCAN_FAIL_ON    ?= high
GRYPE_DB_VOLUME ?= mlops-platform-grype-db

.PHONY: help setup test lint fmt hooks check doctor build sbom scan up up-quickstart down clean reset ps logs config

help:
	@echo "setup           create .venv and install dev dependencies"
	@echo "test            run the test suite"
	@echo "lint            formatting, ruff and mypy, changing nothing"
	@echo "hooks           run every pre-commit hook over the whole tree"
	@echo "check           everything the gate requires: lint, hooks, test"
	@echo "doctor          check the machine can start the stack, and say what is wrong"
	@echo "build           build the one image in the spine, without starting anything"
	@echo "sbom            catalogue every image and write the reviewable inventories"
	@echo "scan            report the database build date, then scan and fail on $(SCAN_FAIL_ON)+"
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

# Reads the SBOM rather than the image, so what is scanned is what was inventoried and a finding
# can be traced to a committed line. Accepted findings are not wired in yet: security/exceptions.toml
# is empty, and generating a scanner ignore file for zero entries would be a mechanism with nothing
# to mechanise. The expiry check in the contract tier runs today; the bridge is owed at the first
# accepted finding, and record 019 records that as an open limit rather than a done thing.
scan:
	@ls $(SBOM_DIR)/*.spdx.json >/dev/null 2>&1 || \
	  { echo "no SBOMs in $(SBOM_DIR); run 'make sbom' first"; exit 1; }
	@docker run --rm -v $(GRYPE_DB_VOLUME):/db -e GRYPE_DB_CACHE_DIR=/db \
	  $(GRYPE) db status || \
	  { echo "the vulnerability database would not load; see docs/decisions/020"; exit 1; }
	@gate="--fail-on $(SCAN_FAIL_ON)"; \
	if [ "$(SCAN_FAIL_ON)" = "none" ]; then gate=""; fi; \
	for document in $(SBOM_DIR)/*.spdx.json; do \
	  echo "scanning $$document"; \
	  docker run --rm -v "$$PWD/$(SBOM_DIR):/sbom" \
	    -v $(GRYPE_DB_VOLUME):/db -e GRYPE_DB_CACHE_DIR=/db \
	    $(GRYPE) "sbom:/sbom/$$(basename $$document)" $$gate || exit 1; \
	done

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
