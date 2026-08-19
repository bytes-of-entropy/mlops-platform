# Canonical entrypoint. CI runs these targets; make.ps1 mirrors them on Windows and a
# test asserts the two do not drift.

COMPOSE      := docker compose -f compose/docker-compose.yml
COMPOSE_QS   := docker compose -f compose/docker-compose.yml -f compose/docker-compose.quickstart.yml
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

.PHONY: help setup test lint fmt check up up-quickstart down clean ps logs config

help:
	@echo "setup           create .venv and install dev dependencies"
	@echo "test            run the test suite"
	@echo "lint            formatting, ruff and mypy, changing nothing"
	@echo "check           everything the gate requires: lint then test"
	@echo "up              start the full spine (all services)"
	@echo "up-quickstart   start the 4 GB / 2 CPU reviewer profile"
	@echo "down            stop and remove containers, KEEP volumes"
	@echo "clean           stop and remove containers AND volumes"

setup:
	$(BOOTSTRAP_PY) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

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

# What CI runs, and the one target to run before pushing.
check: lint test

up:
	$(COMPOSE) --profile full up -d --wait --wait-timeout $(WAIT_TIMEOUT)

up-quickstart:
	$(COMPOSE_QS) up -d --wait --wait-timeout $(WAIT_TIMEOUT)

down:
	$(COMPOSE) --profile full down --remove-orphans

clean:
	$(COMPOSE) --profile full down --remove-orphans --volumes

ps:
	$(COMPOSE) --profile full ps

logs:
	$(COMPOSE) --profile full logs --tail=100

config:
	$(COMPOSE) --profile full config
