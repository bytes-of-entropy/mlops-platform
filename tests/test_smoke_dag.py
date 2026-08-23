"""The smoke DAG, checked without an Airflow to run it.

The DAG file is the one piece of Python in this repository that executes somewhere the suite
cannot follow: inside a pinned image, imported by a scheduler, on a machine that has Docker. So
everything checkable from the outside is checked here -- that it parses, that the name the
integration tier triggers is the name it declares, that the variable it reads is the variable
compose sets, and that it imports nothing the image does not already contain.

That last one is the rule worth having. `import mlflow` in this file would pass the formatter, pass
the linter, pass review, and fail at task-run time inside a container whose image has no install
step -- a dependency that exists only in the mind of whoever wrote the DAG. The check is a parse and
a name comparison, so it costs nothing and runs everywhere.
"""

from __future__ import annotations

import sys
from typing import Any

from tests.dagfile import DAG_FILE, declared, imported_roots, source, tree

AIRFLOW_SERVICE = "airflow"
DAGS_MOUNT = "./airflow/dags"

#: The image ships Airflow and its own dependencies, and nothing this repository chose. Anything
#: outside these two sets would need an install step, and there is not one.
ALLOWED_ROOTS = frozenset({"airflow"}) | frozenset(sys.stdlib_module_names)


def test_the_dag_file_parses() -> None:
    assert tree().body, "the smoke DAG parsed to an empty module"


def test_the_dag_imports_nothing_the_image_does_not_ship() -> None:
    """A DAG may only import what is already inside the container it runs in.

    The image is pinned and has no install step, so an import outside these roots is a task that
    fails at run time on the build machine having passed every check on the authoring one.
    """
    unavailable = sorted(imported_roots() - ALLOWED_ROOTS)
    assert not unavailable, (
        f"the smoke DAG imports {unavailable}, which the pinned Airflow image does not ship; "
        f"either use the standard library or add an install step and decide that deliberately"
    )


def test_the_decorator_uses_the_dag_id_the_module_declares() -> None:
    """The integration tier triggers this DAG by string, so the string lives in one place.

    Declared once and read by both tiers, a rename stays consistent. Written out a second time in
    the decorator, a rename breaks nothing here and everything on the machine that has Docker.
    """
    assert declared("DAG_ID")
    assert "dag_id=DAG_ID" in source(), (
        f"{DAG_FILE.name} passes a literal dag_id to @dag instead of the DAG_ID it declares, so "
        f"the name the integration tier triggers and the name Airflow registers can drift apart"
    )


def test_the_dag_reads_the_tracking_variable_that_compose_sets(
    services: dict[str, dict[str, Any]],
) -> None:
    """One name, set on one side and read on the other, checked against each other.

    The failure this rules out is silent in the worst way: a DAG reading a variable nobody sets
    would take whatever default it was given and log its run somewhere no reviewer looks.
    """
    variable = declared("TRACKING_URI_VARIABLE")
    environment = services[AIRFLOW_SERVICE]["environment"]
    assert variable in environment, (
        f"the smoke DAG reads {variable}, which the {AIRFLOW_SERVICE} service does not set, so the "
        f"task would refuse at run time"
    )
    assert str(environment[variable]).startswith("http"), (
        f"{variable} is set to {environment[variable]!r}, which is not an address"
    )


def test_the_dag_has_no_default_tracking_address() -> None:
    """Keeps the variable load-bearing rather than merely read.

    A fallback address is how a task talks to something nobody configured and still reports
    success, which is the exact shape of every defect this milestone was spent on.
    """
    assert 'os.environ.get(TRACKING_URI_VARIABLE, "")' in source(), (
        "the smoke DAG no longer reads the tracking address without a default; a fallback here "
        "would let the task appear to work against an address nobody set"
    )


def test_the_dag_directory_is_mounted_into_the_scheduler(
    services: dict[str, dict[str, Any]],
) -> None:
    """A DAG the scheduler cannot see is a file, not a DAG."""
    mounts = [str(mount) for mount in services[AIRFLOW_SERVICE]["volumes"]]
    matching = [mount for mount in mounts if mount.startswith(f"{DAGS_MOUNT}:")]
    assert matching, f"the {AIRFLOW_SERVICE} service does not mount {DAGS_MOUNT}: {mounts}"
    assert matching[0].endswith(":ro"), (
        f"{matching[0]} is writable, so the scheduler could change the checkout it was started "
        f"from and the second up would run different code than the first"
    )


def test_the_dag_is_triggered_rather_than_scheduled() -> None:
    """A smoke test on a timer fills the metadata database with proof of nothing."""
    assert "schedule=None" in source(), (
        "the smoke DAG has a schedule; it exists to be run deliberately, by a reviewer or by the "
        "integration tier, not on a clock"
    )
