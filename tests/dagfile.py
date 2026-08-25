"""The smoke DAG read as text, because it cannot be imported here.

It imports Airflow, which is inside a pinned image and deliberately not in this repository's dev
dependencies; adding it would mean installing a scheduler to check a file. So both tiers read the
file instead: the contract tier to assert what it declares, and the integration tier to learn the
dag_id it has to trigger. One reader, so a rename cannot mean two different things in two places.
"""

from __future__ import annotations

import ast
from functools import cache
from typing import Any

from tests.conftest import REPO_ROOT

DAG_FILE = REPO_ROOT / "airflow" / "dags" / "m0_smoke.py"


@cache
def source() -> str:
    assert DAG_FILE.exists(), f"the smoke DAG is missing from {DAG_FILE}"
    return DAG_FILE.read_text(encoding="utf-8")


@cache
def tree() -> ast.Module:
    """A parse failure here is a DAG the scheduler would refuse, found without a scheduler."""
    return ast.parse(source(), filename=str(DAG_FILE))


def literals() -> dict[str, Any]:
    """Module-level `NAME = <literal>` pairs, which is how the DAG states its own contract."""
    found: dict[str, Any] = {}
    for node in tree().body:
        if not isinstance(node, ast.Assign):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = value
    return found


def declared(name: str) -> Any:
    """One declared literal, or an error naming the file that was supposed to declare it."""
    found = literals()
    assert name in found, f"{DAG_FILE.name} declares no module-level {name}"
    assert found[name], f"{DAG_FILE.name} declares {name} as an empty value"
    return found[name]


def imported_roots() -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots
