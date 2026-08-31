"""The chart as helm actually renders it, which is the only place absence can be proved.

`test_chart_templates.py` states its own sharpest limitation: it drops control lines, so a field
guarded by `{{- if }}` looks unconditionally present, and no assertion it makes about a field being
*absent* can be sound. Every check here is one of those — the ones that were unavailable until
something produced a real render.

The render is `make chart-lint`'s output, `.rendered/<release>.yaml`, which until now was a file
written so a person could look at it and which nothing read. CI's chart job produces it and so does
the build machine's runner, so these run in both places; on a laptop with no helm the render-backed
tests skip by name, the way `requires_docker` and `requires_cluster` do.

**Every check is a pure function over parsed documents, and each one is tested against synthetic
input in this same file.** That split is deliberate and it is the lesson of the run that produced
this file: an assertion whose first execution is on the build machine is an assertion nobody has
checked, and two of the cluster tier's seven failed on their own text rather than on the thing they
were inspecting. The functions run on every machine; only the real render waits for helm.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

RENDER = REPO_ROOT / ".rendered" / "mlops-platform.yaml"

#: Skips by name when nothing has rendered the chart, rather than passing vacuously.
requires_rendered_chart = pytest.mark.skipif(
    not RENDER.is_file(),
    reason="no rendered chart; run `make chart-lint` (needs helm)",
)

#: What the chart is expected to render, with counts. Counts rather than a set, because "renders one
#: HPA" and "renders three" are different charts and a set cannot tell them apart.
EXPECTED_KINDS = {
    "Deployment": 3,
    "Service": 3,
    "PersistentVolumeClaim": 2,
    "Ingress": 1,
    "HorizontalPodAutoscaler": 1,
}

#: Kinds this chart must never produce. `Secret` is the one that matters: credentials arrive from a
#: Secret the operator creates from `.env`, so a chart rendering its own would be a second place for
#: them to live. This is the assertion the pseudo-render cannot make in either direction.
FORBIDDEN_KINDS = ("Secret", "ConfigMap")

#: Variable names whose value must never be a literal in a manifest.
CREDENTIAL_WORDS = ("PASSWORD", "SECRET", "KEY", "TOKEN")

SHARED_LABELS = (
    "app.kubernetes.io/name",
    "app.kubernetes.io/instance",
    "app.kubernetes.io/component",
)

Document = dict[str, Any]


# --------------------------------------------------------------------------------------------------
# The checks, as functions of parsed documents. Tested twice: against synthetic input below, and
# against the real render above.
# --------------------------------------------------------------------------------------------------


def containers_of(deployment: Document) -> list[Document]:
    spec = deployment["spec"]["template"]["spec"]
    return list(spec.get("initContainers") or []) + list(spec["containers"])


def kind_counts(documents: list[Document]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        counts[document["kind"]] = counts.get(document["kind"], 0) + 1
    return counts


def objects_of_kind(documents: list[Document], kind: str) -> list[str]:
    return [d["metadata"]["name"] for d in documents if d["kind"] == kind]


def literal_credentials(documents: list[Document]) -> list[str]:
    """Credential-shaped variables carrying a `value:` instead of a `secretKeyRef`."""
    found = []
    for document in documents:
        if document["kind"] != "Deployment":
            continue
        for container in containers_of(document):
            for entry in container.get("env") or []:
                name = str(entry.get("name", ""))
                if any(word in name for word in CREDENTIAL_WORDS) and "value" in entry:
                    found.append(f"{document['metadata']['name']}/{name}")
    return found


def autoscaled_with_a_replica_count(documents: list[Document]) -> list[str]:
    """Deployments an HPA targets that still declare `replicas`."""
    targets = {
        d["spec"]["scaleTargetRef"]["name"]
        for d in documents
        if d["kind"] == "HorizontalPodAutoscaler"
    }
    return [
        d["metadata"]["name"]
        for d in documents
        if d["kind"] == "Deployment"
        and d["metadata"]["name"] in targets
        and "replicas" in d["spec"]
    ]


def always_pullers(documents: list[Document]) -> list[str]:
    return [
        f"{d['metadata']['name']}/{c['name']}"
        for d in documents
        if d["kind"] == "Deployment"
        for c in containers_of(d)
        if c.get("imagePullPolicy") == "Always"
    ]


def objects_missing_shared_labels(documents: list[Document]) -> list[str]:
    return [
        f"{d['kind']}/{d['metadata']['name']}: {label}"
        for d in documents
        for label in SHARED_LABELS
        if label not in (d["metadata"].get("labels") or {})
    ]


def values_appearing_alone(values: set[str], text: str, minimum: int = 8) -> list[str]:
    """Which of `values` appear in `text` as whole tokens.

    Whole-token rather than substring, for the reason the cluster tier's version of this learned on
    a real cluster: `POSTGRES_DB=platform` is eight characters and a substring of `mlops-platform`,
    so a substring test reported the release name as a leaked credential.
    """
    return sorted(
        value
        for value in values
        if len(value) >= minimum
        and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9_-])", text)
    )


def deferred_references(deployment: Document) -> str:
    """The last container's args, where a `$(VAR)` reference has to survive rendering verbatim."""
    return " ".join(str(a) for a in containers_of(deployment)[-1].get("args", []))


# --------------------------------------------------------------------------------------------------
# The checks against synthetic documents. These run everywhere, including a laptop with no helm.
# --------------------------------------------------------------------------------------------------


def workload(
    name: str = "rel-mlflow",
    *,
    env: list[Document] | None = None,
    replicas: int | None = None,
    pull: str = "IfNotPresent",
    labels: dict[str, str] | None = None,
    args: list[str] | None = None,
) -> Document:
    spec: Document = {
        "template": {
            "spec": {
                "containers": [
                    {
                        "name": "main",
                        "imagePullPolicy": pull,
                        "env": env or [],
                        "args": args or [],
                    }
                ]
            }
        }
    }
    if replicas is not None:
        spec["replicas"] = replicas
    return {
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "labels": labels if labels is not None else dict.fromkeys(SHARED_LABELS, "x"),
        },
        "spec": spec,
    }


def autoscaler(target: str = "rel-mlflow") -> Document:
    return {
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": target, "labels": dict.fromkeys(SHARED_LABELS, "x")},
        "spec": {"scaleTargetRef": {"name": target}},
    }


def test_a_literal_credential_is_found_and_a_reference_is_not() -> None:
    """Both directions, because a check that never fires is indistinguishable from a passing one."""
    referenced = workload(env=[{"name": "POSTGRES_PASSWORD", "valueFrom": {"secretKeyRef": {}}}])
    literal = workload(env=[{"name": "POSTGRES_PASSWORD", "value": "hunter2hunter2"}])
    assert literal_credentials([referenced]) == []
    assert literal_credentials([literal]) == ["rel-mlflow/POSTGRES_PASSWORD"]


def test_a_credential_in_an_init_container_is_found_too() -> None:
    """The failure mode is a `value:` wherever it was easiest to write, not just the main one."""
    document = workload()
    document["spec"]["template"]["spec"]["initContainers"] = [
        {"name": "init", "env": [{"name": "AWS_SECRET_ACCESS_KEY", "value": "aaaaaaaaaaaa"}]}
    ]
    assert literal_credentials([document]) == ["rel-mlflow/AWS_SECRET_ACCESS_KEY"]


def test_an_autoscaled_deployment_declaring_replicas_is_found() -> None:
    assert autoscaled_with_a_replica_count([workload(replicas=1), autoscaler()]) == ["rel-mlflow"]
    assert autoscaled_with_a_replica_count([workload(), autoscaler()]) == []


def test_a_deployment_no_hpa_targets_may_declare_replicas() -> None:
    """Postgres and MinIO do exactly this, so the check must not flag them."""
    assert autoscaled_with_a_replica_count([workload("rel-postgres", replicas=1)]) == []


def test_an_always_puller_is_found_in_either_container_list() -> None:
    assert always_pullers([workload(pull="Always")]) == ["rel-mlflow/main"]
    assert always_pullers([workload()]) == []


def test_a_missing_shared_label_is_named_with_its_object() -> None:
    assert objects_missing_shared_labels([workload(labels={})]) == [
        f"Deployment/rel-mlflow: {label}" for label in SHARED_LABELS
    ]
    assert objects_missing_shared_labels([workload()]) == []


def test_whole_token_matching_finds_a_credential_and_not_a_release_name() -> None:
    """The exact false positive the cluster tier hit, as a test rather than as a comment."""
    text = "name: mlops-platform\nvalue: s3cr3t-p4ssw0rd\n"
    assert values_appearing_alone({"s3cr3t-p4ssw0rd"}, text) == ["s3cr3t-p4ssw0rd"]
    assert values_appearing_alone({"platform"}, text) == []


def test_a_short_value_is_not_matched_at_all() -> None:
    """`POSTGRES_DB=mlflow` would otherwise match the bucket name and the image name."""
    assert values_appearing_alone({"mlflow"}, "image: mlops-platform/mlflow:2.22.4") == []


def test_kind_counts_distinguish_a_duplicate_from_a_match() -> None:
    documents = [workload(), workload("rel-postgres"), autoscaler()]
    assert kind_counts(documents) == {"Deployment": 2, "HorizontalPodAutoscaler": 1}


def test_deferred_references_reads_the_last_containers_args() -> None:
    """The main container is last; an initContainer's args must not be mistaken for it."""
    document = workload(args=["--backend-store-uri", "postgresql://$(POSTGRES_USER)@host/db"])
    document["spec"]["template"]["spec"]["initContainers"] = [{"name": "init", "args": ["nothing"]}]
    assert "$(POSTGRES_USER)" in deferred_references(document)


# --------------------------------------------------------------------------------------------------
# The same checks against what helm produced. These need the render and skip without it.
# --------------------------------------------------------------------------------------------------


def documents() -> list[Document]:
    loaded = [d for d in yaml.safe_load_all(RENDER.read_text(encoding="utf-8")) if d]
    assert loaded, f"{RENDER} parsed to nothing, so every assertion here would be vacuous"
    return loaded


@requires_rendered_chart
def test_the_render_holds_the_objects_expected() -> None:
    counts = kind_counts(documents())
    assert counts == EXPECTED_KINDS, f"rendered {counts}, expected {EXPECTED_KINDS}"


@requires_rendered_chart
@pytest.mark.parametrize("kind", FORBIDDEN_KINDS)
def test_the_chart_renders_no_object_of_a_kind_it_must_not(kind: str) -> None:
    """The absence claim, which is the whole reason this file exists."""
    found = objects_of_kind(documents(), kind)
    assert not found, (
        f"the chart renders {len(found)} {kind}(s): {found}. Credentials reach a container from a "
        f"Secret the operator makes from .env, so a chart rendering one is a second place for them"
    )


@requires_rendered_chart
def test_no_value_from_the_local_env_survives_into_the_render() -> None:
    """The credential check, made a whole cluster earlier than the tier can make it."""
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        pytest.skip("no .env here, so there are no real values to look for")
    values = {
        line.partition("=")[2].strip().strip("'\"")
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    leaked = values_appearing_alone(values, RENDER.read_text(encoding="utf-8"))
    assert not leaked, f"{len(leaked)} value(s) from .env appear in the render: {leaked}"


@requires_rendered_chart
def test_the_credential_reaches_the_container_as_a_deferred_reference() -> None:
    """`$(POSTGRES_PASSWORD)` has to survive rendering as those exact characters.

    That literal is Kubernetes' own substitution, resolved in the container at start. Had helm
    resolved it instead, the password would be in the manifest and `kubectl get deploy -o yaml`
    would print it. The pseudo-render cannot tell the two apart, because it replaces every inline
    expression alike.
    """
    mlflow = next(
        d
        for d in documents()
        if d["kind"] == "Deployment" and d["metadata"]["name"].endswith("-mlflow")
    )
    args = deferred_references(mlflow)
    for reference in ("$(POSTGRES_USER)", "$(POSTGRES_PASSWORD)", "$(POSTGRES_DB)"):
        assert reference in args, (
            f"{reference} is not in MLflow's rendered args: {args[:200]}. If helm resolved it, the "
            f"credential is now in the manifest"
        )


@requires_rendered_chart
def test_the_render_carries_no_literal_credential() -> None:
    assert literal_credentials(documents()) == []


@requires_rendered_chart
def test_the_autoscaled_deployment_renders_no_replica_count() -> None:
    """The absence claim `test_chart_templates.py` documents itself as unable to make."""
    assert autoscaled_with_a_replica_count(documents()) == []


@requires_rendered_chart
def test_no_container_anywhere_pulls_always() -> None:
    assert always_pullers(documents()) == []


@requires_rendered_chart
def test_every_object_carries_the_shared_labels() -> None:
    assert objects_missing_shared_labels(documents()) == []
