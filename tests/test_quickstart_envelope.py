"""The quickstart claims 4 GB and 2 CPUs. That claim is checked here, not trusted.

The envelope is computed from the declared limits of exactly the services the quickstart
starts (the base file minus everything gated behind the `full` profile) with the
override applied the way `docker compose -f a -f b` would apply it.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import FULL_PROFILE

MEMORY_BUDGET_MIB = 4096
CPU_BUDGET = 2.0

_UNITS = {"b": 1 / (1024 * 1024), "k": 1 / 1024, "m": 1.0, "g": 1024.0}


def parse_memory_mib(value: str) -> float:
    text = str(value).strip().lower().rstrip("b")
    suffix = text[-1]
    if suffix in _UNITS:
        return float(text[:-1]) * _UNITS[suffix]
    return float(text) / (1024 * 1024)


def quickstart_services(
    compose: dict[str, Any], quickstart: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for name, service in compose["services"].items():
        if FULL_PROFILE in (service.get("profiles") or []):
            continue
        limits = dict(((service.get("deploy") or {}).get("resources") or {}).get("limits") or {})
        override = quickstart["services"].get(name, {})
        limits.update(((override.get("deploy") or {}).get("resources") or {}).get("limits") or {})
        merged[name] = limits
    return merged


def test_every_quickstart_service_is_capped(
    compose: dict[str, Any], quickstart: dict[str, Any]
) -> None:
    for name, limits in quickstart_services(compose, quickstart).items():
        assert "memory" in limits and "cpus" in limits, (
            f"{name} runs uncapped in the quickstart, so the envelope is unenforced"
        )


def test_quickstart_fits_in_four_gigabytes(
    compose: dict[str, Any], quickstart: dict[str, Any]
) -> None:
    limits = quickstart_services(compose, quickstart)
    total = sum(parse_memory_mib(spec["memory"]) for spec in limits.values())
    assert total <= MEMORY_BUDGET_MIB, (
        f"quickstart declares {total:.0f} MiB against a {MEMORY_BUDGET_MIB} MiB budget: "
        + ", ".join(f"{n}={s['memory']}" for n, s in sorted(limits.items()))
    )


def test_quickstart_fits_in_two_cpus(compose: dict[str, Any], quickstart: dict[str, Any]) -> None:
    limits = quickstart_services(compose, quickstart)
    total = sum(float(spec["cpus"]) for spec in limits.values())
    assert total <= CPU_BUDGET, (
        f"quickstart declares {total:.2f} CPUs against a {CPU_BUDGET} CPU budget: "
        + ", ".join(f"{n}={s['cpus']}" for n, s in sorted(limits.items()))
    )


def test_quickstart_only_overrides_services_that_exist(
    compose: dict[str, Any], quickstart: dict[str, Any]
) -> None:
    unknown = set(quickstart["services"]) - set(compose["services"])
    assert not unknown, f"quickstart overrides services absent from the spine: {sorted(unknown)}"


def test_spark_worker_heap_fits_its_container(quickstart: dict[str, Any]) -> None:
    """A worker told to use more heap than its cgroup allows is an OOM kill, not a warning."""
    worker = quickstart["services"]["spark-worker-1"]
    declared_heap = parse_memory_mib(worker["environment"]["SPARK_WORKER_MEMORY"])
    container = parse_memory_mib(worker["deploy"]["resources"]["limits"]["memory"])
    assert declared_heap < container, (
        f"SPARK_WORKER_MEMORY {declared_heap:.0f} MiB >= container limit {container:.0f} MiB"
    )
