"""What the cluster tier and the make targets have to agree about, checked without a cluster.

`test_compose_paths.py` exists because `stackops` builds its own compose invocations rather than
calling `make up`, so the two can drift. `clusterops` makes the same trade for the same reason and
this is its analogue: the tier drives kind, kubectl and helm itself, so nothing here would notice if
the Makefile were pointing at a different chart.

It also holds the one assertion that would have saved a build-machine run. The load generator is a
Python program built as a string and executed inside a pod, and the first version was assembled with
semicolons around a `def`, which is a `SyntaxError`. Every generator pod crashed on start, the HPA
read 0% for four minutes, and the test reported that the autoscaler had not scaled -- a true
sentence about the wrong subject. `compile()` costs nothing and runs on a laptop.
"""

from __future__ import annotations

import re

from tests.clusterops import (
    CHART,
    KIND_CONFIG,
    LOAD_BODY,
    LOAD_PATH,
    TEST_CLUSTER,
    load_script,
    settings,
)
from tests.conftest import REPO_ROOT

MAKEFILE = REPO_ROOT / "Makefile"


def test_the_load_generator_is_valid_python() -> None:
    """The defect this file was written for: a program that never ran and was never syntax-checked.

    Compiled rather than executed, because executing it starts an unbounded request loop. Compiling
    catches the whole class -- a `def` after a semicolon, an unbalanced quote, a stray f-string
    brace -- every one of which presents on a cluster as a CrashLoopBackOff and an HPA that reads
    zero.
    """
    script = load_script("some-service", 5000, 4)
    compile(script, "<load generator>", "exec")


def test_the_load_generator_targets_the_service_and_port_it_is_given() -> None:
    """An anti-vacuity guard: a script that compiles and asks the wrong host makes no load."""
    script = load_script("mlflow-service", 5000, 2)
    assert "http://mlflow-service:5000" in script
    assert str(LOAD_PATH) in script
    assert "range(2)" in script, "the thread count did not reach the program"


def test_the_load_endpoint_is_posted_to_rather_than_queried() -> None:
    """MLflow's search API is POST-only, so a GET is answered 405 out of the router.

    A 405 loop still makes requests and would look like load in a graph, while never reaching the
    connection pool or Postgres -- which is the work the HPA is supposed to notice. The first
    version of this used a query string, which is what a GET looks like.
    """
    assert "?" not in LOAD_PATH, f"{LOAD_PATH} carries a query string, so it was written as a GET"
    assert LOAD_BODY, "the generator posts no body, so MLflow's search has nothing to search on"
    assert "data=body" in load_script("service", 1, 1), "the request sends no body"


def test_the_tier_installs_the_chart_the_makefile_installs() -> None:
    """Two names for one chart is how a tier passes against something nobody ships."""
    declared = settings()
    assert declared["CHART"] == CHART, (
        f"the Makefile installs {declared['CHART']} and the tier installs {CHART}"
    )
    assert declared["KIND_CONFIG"] == KIND_CONFIG, (
        f"the Makefile creates its cluster from {declared['KIND_CONFIG']} and the tier from "
        f"{KIND_CONFIG}, so the two clusters are not the same shape"
    )


def test_the_tier_uses_a_different_cluster_name_from_the_make_target() -> None:
    """The separation record 025 argues for, asserted so a later tidy-up cannot collapse it.

    If both used one name, a cluster left running by hand would decide whether the suite passes, and
    the tier's `refuse_a_port_conflict` guard would fire on every run instead of never.
    """
    assert settings()["KIND_CLUSTER"] != TEST_CLUSTER, (
        f"the Makefile and the tier both use the cluster name {TEST_CLUSTER}"
    )


def test_the_makefile_reads_its_versions_from_one_place_the_tier_can_find() -> None:
    """`settings()` parses the Makefile, so a change of assignment style silently empties it.

    The tier would then create a cluster with an empty `--image`, which fails in a way that reads as
    a kind problem. Four keys, because those are the ones `clusterops` indexes by name.
    """
    declared = settings()
    for key in ("KIND_NODE_IMAGE", "METRICS_SERVER", "INGRESS_NGINX", "MLFLOW_TAG"):
        assert declared.get(key), f"{key} did not parse out of the Makefile"
    assert re.match(r"^kindest/node:v\d", declared["KIND_NODE_IMAGE"]), declared["KIND_NODE_IMAGE"]
