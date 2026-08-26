"""The quickstart claims 4 GB and 2 CPUs. That claim is checked here, not trusted.

The envelope is computed from the declared limits of exactly the services the quickstart
starts (the base file minus everything gated behind the `full` profile) with the
override applied the way `docker compose -f a -f b` would apply it.

**It is a peak, not a sum.** Summing every declared limit assumes every service runs at once, and
a one-shot provisioner does not: the services gated on its completion cannot start until it has
exited, so it and they are never resident together. Charging the sum was a conservative
over-approximation, which was invisible while it happened to hold and became visible the moment it
did not, with the CPU total sitting at exactly the budget. What is charged instead is the peak: the
long-running services, plus whatever a one-shot costs *over and above* the cheapest thing it blocks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.conftest import FULL_PROFILE
from tests.test_compose_contract import completion_waiters

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


def peak(
    compose: dict[str, Any],
    quickstart: dict[str, Any],
    resource: str,
    amount: Callable[[Any], float],
) -> tuple[float, dict[str, float]]:
    """Peak concurrent use of one resource, with the per-service figures that produced it.

    A one-shot is charged ``max(0, its own limit - the smallest limit among the services waiting
    on it)``. While it runs, at least one of those waiters is necessarily absent, so it displaces
    that waiter rather than adding to it. When a provisioner is smaller than everything it gates,
    which is the ordinary case, it costs nothing at all.
    """
    limits = quickstart_services(compose, quickstart)
    sizes = {name: float(amount(spec[resource])) for name, spec in limits.items()}
    waiters = {
        name: gated & sizes.keys()
        for name, gated in completion_waiters(compose["services"]).items()
        if name in sizes
    }

    charged = {name: size for name, size in sizes.items() if name not in waiters}
    for name, gated in waiters.items():
        cheapest = min((sizes[other] for other in gated), default=0.0)
        charged[name] = max(0.0, sizes[name] - cheapest)
    return sum(charged.values()), charged


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
    total, charged = peak(compose, quickstart, "memory", parse_memory_mib)
    assert total <= MEMORY_BUDGET_MIB, (
        f"quickstart peaks at {total:.0f} MiB against a {MEMORY_BUDGET_MIB} MiB budget: "
        + ", ".join(f"{n}={v:.0f}" for n, v in sorted(charged.items()))
    )


def test_quickstart_fits_in_two_cpus(compose: dict[str, Any], quickstart: dict[str, Any]) -> None:
    total, charged = peak(compose, quickstart, "cpus", float)
    assert total <= CPU_BUDGET, (
        f"quickstart peaks at {total:.2f} CPUs against a {CPU_BUDGET} CPU budget: "
        + ", ".join(f"{n}={v:.2f}" for n, v in sorted(charged.items()))
    )


def test_a_provisioner_is_smaller_than_what_it_gates(
    compose: dict[str, Any], quickstart: dict[str, Any]
) -> None:
    """The condition under which the peak model above is not merely an accounting convenience.

    If a one-shot were larger than everything waiting on it, it would raise the peak rather than
    hide inside it, and the budget would have to absorb the difference. Asserting the ordinary case
    holds means a future provisioner that breaks it fails here, naming the reason, instead of
    quietly consuming the headroom the two budget tests are there to protect.
    """
    checks: tuple[tuple[str, Callable[[Any], float]], ...] = (
        ("memory", parse_memory_mib),
        ("cpus", float),
    )
    for resource, amount in checks:
        limits = quickstart_services(compose, quickstart)
        sizes = {name: float(amount(spec[resource])) for name, spec in limits.items()}
        for name, gated in completion_waiters(compose["services"]).items():
            if name not in sizes:
                continue
            for other in gated & sizes.keys():
                assert sizes[name] <= sizes[other], (
                    f"{name} declares more {resource} ({sizes[name]}) than {other} "
                    f"({sizes[other]}), which waits on it, so it adds to the quickstart peak "
                    "instead of displacing what it blocks"
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
