"""The chart's declared values are a contract, checked by reading them.

`helm lint` and `helm template` are the obvious tools and they are not available here: the authoring
machine has no helm, no kind and no docker, and the whole point of the contract tier is that it runs
on a laptop. So `Chart.yaml` and `values.yaml` are parsed as YAML — which they are, unlike the
templates — and asserted against the compose spine they have to agree with.

What this file can check is everything that is *declared*. What it cannot is whether the templates
render, which needs helm and lives in CI and on the build machine. `tests/test_chart_templates.py`
covers as much of the template text as text-level parsing honestly reaches.

The assertions worth having are the ones about agreement rather than about form. A chart naming an
image the spine does not run, or claiming an `appVersion` the images do not carry, is a document
describing a different system — and nothing about installing it would say so.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

CHART_DIR = REPO_ROOT / "charts" / "mlops-platform"
CHART_FILE = CHART_DIR / "Chart.yaml"
VALUES_FILE = CHART_DIR / "values.yaml"
QUICKSTART_VALUES = CHART_DIR / "values-quickstart.yaml"
KIND_CONFIG = REPO_ROOT / "charts" / "kind-cluster.yaml"

#: The components this chart deploys. Named rather than discovered: the point of the list is that it
#: is a decision, and record 024 argues why Spark and Airflow are not on it.
COMPONENTS = ("mlflow", "postgres", "minio")

#: Orderable SemVer, because record 014 requires a consumer be able to compare and range over it. A
#: pre-release suffix is allowed; build metadata is not, since it does not participate in ordering.
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")

#: A digest as a registry hands it over.
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def load(path: Any) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} does not parse to a mapping"
    return loaded


def chart() -> dict[str, Any]:
    return load(CHART_FILE)


def values() -> dict[str, Any]:
    return load(VALUES_FILE)


def compose_images() -> set[str]:
    """Every image reference the compose spine names, as written."""
    loaded = load(REPO_ROOT / "compose" / "docker-compose.yml")
    return {str(service["image"]) for service in loaded["services"].values()}


def reference(image: dict[str, Any]) -> str:
    """The reference a values image fragment resolves to, mirroring the chart's own helper."""
    base = f"{image['repository']}:{image['tag']}"
    return f"{base}@{image['digest']}" if image.get("digest") else base


def test_the_chart_exists_for_these_tests_to_check() -> None:
    """Guards against a vacuous file: every test below would pass on an absent chart."""
    assert CHART_FILE.is_file(), f"{CHART_FILE} is missing, so every check here proves nothing"
    assert VALUES_FILE.is_file(), f"{VALUES_FILE} is missing"
    assert list(CHART_DIR.glob("templates/*.yaml")), "the chart renders no manifests"


def test_the_chart_version_is_orderable() -> None:
    """Another repository pins this, so it has to be comparable rather than merely unique.

    Record 014 chose SemVer for exactly this: a consumer pinning a release needs something it can
    order and range over, which a milestone label is not.
    """
    version = str(chart()["version"])
    assert SEMVER.match(version), (
        f"chart version {version!r} is not orderable SemVer, so a consumer cannot range over it"
    )


def test_the_chart_version_is_not_the_repository_tag() -> None:
    """They answer different questions and coupling them forces pointless re-pinning.

    The repository tags milestones; the chart versions its own interface. If the chart's version
    tracked the repository's, a consumer would have to re-pin for every change to a test or a
    document — changes that cannot affect them.
    """
    assert "version" in chart(), "the chart declares no version"
    # Asserted as a property rather than by comparing to a tag, because the tag is not readable here
    # without git and the point is independence, not a particular value.
    assert str(chart()["version"]) != str(chart().get("appVersion")), (
        "the chart version equals its appVersion, which makes the chart's interface and MLflow's "
        "release the same claim; they are not"
    )


def test_the_declared_app_version_is_the_mlflow_the_spine_runs() -> None:
    """A chart claiming a version its images do not carry describes a different system."""
    declared = str(chart()["appVersion"])
    running = str(values()["mlflow"]["image"]["tag"])
    assert declared == running, (
        f"Chart.yaml says appVersion {declared!r} and values.yaml runs MLflow {running!r}"
    )


def test_every_image_matches_a_reference_the_compose_spine_runs() -> None:
    """The chart and compose deploy the same three images, or one of them is not this platform.

    This is the assertion that makes "the same spine, on Kubernetes" a fact rather than a claim. It
    compares fully reconstructed references, so a matching tag with a mismatched digest fails.
    """
    spine = compose_images()
    for component in COMPONENTS:
        ref = reference(values()[component]["image"])
        assert ref in spine, (
            f"{component} runs {ref}, which the compose spine does not. Either the chart is "
            f"behind a bump, or it deploys something this repository does not otherwise run."
        )


@pytest.mark.parametrize("component", COMPONENTS)
def test_a_pulled_image_is_pinned_by_digest_and_a_built_one_is_not(component: str) -> None:
    """Record 018's rule, applied to the chart rather than restated in it.

    A digest is a registry fact. The image built here has never been handed over by a registry, so
    it has no digest to pin, and pinning one would tie the chart to one machine's image store.
    """
    image = values()[component]["image"]
    built_here = str(image["repository"]).startswith("mlops-platform/")
    digest = image.get("digest") or ""
    if built_here:
        assert not digest, (
            f"{component} is built here and carries a digest. A local build has no registry "
            f"digest, so this pins the chart to one machine's image store"
        )
    else:
        assert DIGEST.match(digest), (
            f"{component} is pulled and its digest is {digest!r}; a tag alone is a pointer its "
            f"publisher can move"
        )


@pytest.mark.parametrize("component", COMPONENTS)
def test_no_image_rides_a_moving_tag(component: str) -> None:
    tag = str(values()[component]["image"]["tag"])
    assert tag not in {"latest", "edge", "stable", "main", ""}, (
        f"{component} rides {tag!r}, which is not a pin"
    )


@pytest.mark.parametrize("component", COMPONENTS)
def test_pull_policy_works_for_a_loaded_image_and_a_pulled_one(component: str) -> None:
    """`IfNotPresent` is the only policy that serves both clusters this chart targets.

    `Never` forbids the pull EKS depends on, making the chart kind-only. `Always` makes the locally
    built image unusable, because nothing can pull `mlops-platform/mlflow` from anywhere.
    """
    policy = str(values()[component]["image"]["pullPolicy"])
    assert policy == "IfNotPresent", (
        f"{component} uses pullPolicy {policy!r}; `Never` breaks EKS and `Always` breaks the image "
        f"kind was handed, so neither works in both places"
    )


@pytest.mark.parametrize("component", COMPONENTS)
def test_every_component_declares_both_requests_and_limits(component: str) -> None:
    """Requests are what an HPA divides by, and compose has none to inherit.

    Compose declares limits only, correctly: it has no scheduler to inform and no autoscaler
    reading utilisation. A chart with a limit and no request leaves the HPA reporting `<unknown>`
    and the
    scheduler guessing, so the requests are new information this chart has to supply.
    """
    resources = values()[component]["resources"]
    for half in ("requests", "limits"):
        assert half in resources, f"{component} declares no resource {half}"
        for dimension in ("cpu", "memory"):
            assert dimension in resources[half], f"{component} {half} does not name {dimension}"


def test_the_autoscaler_can_actually_scale() -> None:
    """An HPA whose bounds are equal is a Deployment with extra steps."""
    hpa = values()["mlflow"]["hpa"]
    assert hpa["maxReplicas"] > hpa["minReplicas"], (
        f"the HPA is bounded {hpa['minReplicas']}..{hpa['maxReplicas']}, so it cannot scale, and "
        f"the milestone's 'HPA scales under synthetic load' cannot be demonstrated"
    )
    assert 0 < hpa["targetCPUUtilizationPercentage"] <= 100, (
        f"a CPU target of {hpa['targetCPUUtilizationPercentage']} is not a percentage"
    )


def test_the_ingress_names_its_class() -> None:
    """An empty class lets whichever controller claims the default decide.

    That is how a chart works on one cluster and silently does nothing on another, and it is the one
    field EKS has to change, so it belongs in values where changing it is not a template edit.
    """
    ingress = values()["mlflow"]["ingress"]
    assert ingress["className"], (
        "the Ingress names no class, so the cluster's default decides and the chart's behaviour "
        "depends on which controller was installed first"
    )


def test_the_chart_names_the_secret_it_reads_and_creates_none() -> None:
    """The absolute rule, asserted from both directions.

    The chart must name the Secret it consumes — otherwise the credentials reach the pods some other
    way, and every other way puts them in a file. And it must render no Secret of its own, because a
    Secret built from values means the values hold the credential.
    """
    credentials = values()["credentials"]
    assert credentials["secretName"], "the chart names no credentials Secret"
    assert set(credentials["keys"]) == {
        "postgresUser",
        "postgresPassword",
        "postgresDatabase",
        "minioRootUser",
        "minioRootPassword",
    }, f"the credential key map is {sorted(credentials['keys'])}, which is not what the spine needs"

    rendering = [
        path.name
        for path in CHART_DIR.glob("templates/*")
        if "kind: Secret" in path.read_text(encoding="utf-8")
    ]
    assert not rendering, (
        f"{rendering} render a Secret. This chart consumes one created outside it, and a Secret "
        f"built from values means the values hold the credential"
    )


def test_the_credential_keys_are_ones_the_environment_actually_declares() -> None:
    """The Secret is created from `.env`, so a key not in `.env.example` can never be populated.

    A `secretKeyRef` to a missing key leaves the pod in `CreateContainerConfigError`, which names
    the Secret and not the key, so this is worth catching where the names are visible.
    """
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    missing = sorted(set(values()["credentials"]["keys"].values()) - declared)
    assert not missing, (
        f"the chart reads {missing} from the credentials Secret, and .env.example declares no such "
        f"variable, so the Secret built from .env cannot carry it"
    )


def test_the_quickstart_values_only_narrow_what_exists() -> None:
    """An override for a component the chart does not have is a typo that changes nothing.

    Same failure the compose quickstart envelope already guards against: the file looks like it caps
    something and does not.
    """
    override = load(QUICKSTART_VALUES)
    unknown = sorted(set(override) - set(values()))
    assert not unknown, (
        f"values-quickstart.yaml overrides {unknown}, which the chart does not define"
    )


def test_the_kind_config_publishes_the_ports_an_ingress_needs() -> None:
    """kind has no load balancer, so the node's own 80 has to reach the host or no Ingress answers.

    Kept out of the chart deliberately: it is a fact about kind, and `OFFLINE_FIRST.md` promises
    the same charts run on EKS. It still has to be true of the cluster the chart is developed on.
    """
    config = load(KIND_CONFIG)
    nodes = config.get("nodes") or []
    published = {
        mapping.get("containerPort")
        for node in nodes
        for mapping in (node.get("extraPortMappings") or [])
    }
    assert 80 in published, (
        "the kind cluster publishes no port 80, so an Ingress has nothing listening in front of it"
    )
    assert 443 in published, (
        "the kind cluster publishes no port 443, and the controller's manifest binds a hostPort "
        "for it, so a TLS Ingress would have nothing in front of it"
    )
    labels = "".join(patch for node in nodes for patch in (node.get("kubeadmConfigPatches") or []))
    assert "ingress-ready=true" in labels, (
        "no node carries ingress-ready=true. The pinned controller-v1.15.1 manifest does not "
        "select on it -- verified by reading that manifest rather than assumed -- so this is "
        "compatibility with the versions either side, not a requirement of this one. It costs one "
        "kubelet argument, and removing it couples this config to that pin"
    )
