"""The chart's templates, checked as far as text can honestly be checked.

Helm templates are not YAML: `{{ include "x" . }}` is a function call to Helm and a flow mapping to
a
parser, so `yaml.safe_load` refuses every file here. `helm template` would resolve that and helm is
not installed on the authoring machine, which is the whole reason the contract tier exists.

So this file does two things. Most assertions run against a **pseudo-render**: control lines
dropped,
injected blocks dropped, inline expressions replaced by a placeholder. What survives parses as YAML
and
carries the document structure — kinds, containers, ports, probes, strategies — which is enough to
navigate rather than grep. The rest are text-level, for the blocks the pseudo-render necessarily
removes: `resources` and `securityContext` arrive through `toYaml` and are not visible to it.

**The pseudo-render is an approximation and is not rendering.** A template that parses here can
still fail `helm template`: a mis-scoped `.` inside a `define`, a `nindent` off by two, a `range`
over
the wrong collection. It catches structure and cannot catch semantics; `helm lint` in CI covers the
rest, and `test_the_pseudo_render_would_catch_a_broken_template` shows the class this does catch.

**One limit is sharp enough to name.** Dropping control lines means conditionals are not evaluated,
so
a field guarded by `{{- if }}` appears unconditionally present. Every assertion here about a field
being *present* is therefore sound, and no assertion about a field being *absent* can be: absence
has
to be argued from the guard, in text, which
`test_the_autoscaled_deployment_guards_its_replica_count` does. This was learned by writing the
absence assertion first and watching it fail against a template that was correct.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

CHART_DIR = REPO_ROOT / "charts" / "mlops-platform"
TEMPLATE_DIR = CHART_DIR / "templates"

#: A line that is only Helm control flow contributes no structure and is dropped.
CONTROL = re.compile(r"^\s*\{\{-?\s*(if|else|end|range|with|define)\b.*\}\}\s*$")

#: A line whose value is a block injected by `include` or `toYaml` is dropped rather than replaced:
#: what it injects is mapping keys, and a scalar placeholder in their place would parse as a string
#: value and misrepresent the shape. The blocks it removes are covered by the text-level tests
#: below.
INJECTED = re.compile(r"\{\{-?\s*(include|toYaml)\b.*nindent")

#: Any remaining inline expression stands in for a scalar, which is what it renders to.
INLINE = re.compile(r"\{\{-?.*?-?\}\}")

#: What each template is expected to render. Named rather than discovered, so a template that stops
#: producing an object fails here instead of quietly reducing what every other test looks at.
EXPECTED_KINDS = {
    "mlflow.yaml": {"Service", "Deployment", "Ingress", "HorizontalPodAutoscaler"},
    "postgres.yaml": {"PersistentVolumeClaim", "Service", "Deployment"},
    "minio.yaml": {"PersistentVolumeClaim", "Service", "Deployment"},
}

#: Words that name a credential. The same list the compose contract has used since M0.
CREDENTIAL = re.compile(r"(PASSWORD|SECRET|TOKEN|FERNET|ROOT_USER)")


def pseudo_render(text: str) -> str:
    """Helm template text reduced to something a YAML parser accepts. See the module docstring."""
    kept: list[str] = []
    for line in text.splitlines():
        if CONTROL.match(line) and not re.search(r":\s*\{\{", line):
            continue
        if INJECTED.search(line):
            continue
        kept.append(INLINE.sub("PLACEHOLDER", line))
    return "\n".join(kept)


def documents(path: Path) -> list[dict[str, Any]]:
    rendered = pseudo_render(path.read_text(encoding="utf-8"))
    try:
        loaded = list(yaml.safe_load_all(rendered))
    except yaml.YAMLError as error:
        pytest.fail(f"{path.name} does not survive a pseudo-render: {error}")
    return [document for document in loaded if isinstance(document, dict)]


def templates() -> list[Path]:
    return sorted(TEMPLATE_DIR.glob("*.yaml"))


def objects_of(kind: str) -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, document)
        for path in templates()
        for document in documents(path)
        if document.get("kind") == kind
    ]


def containers(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    spec = deployment["spec"]["template"]["spec"]
    return list(spec.get("containers") or []) + list(spec.get("initContainers") or [])


def test_there_are_templates_to_check() -> None:
    """Guards against a vacuous file: every test below passes on an empty directory."""
    assert templates(), "no templates under charts/mlops-platform/templates/"
    assert (TEMPLATE_DIR / "_helpers.tpl").is_file(), "the chart defines no helpers"


@pytest.mark.parametrize("path", templates(), ids=lambda p: p.name)
def test_every_template_renders_the_objects_it_is_expected_to(path: Path) -> None:
    """The anti-vacuity guard for the pseudo-render itself.

    Every other test here navigates parsed documents, so a template that stopped producing one would
    quietly shrink what they look at rather than fail. This is what notices.
    """
    expected = EXPECTED_KINDS.get(path.name)
    assert expected is not None, f"{path.name} is not in EXPECTED_KINDS; add it or remove the file"
    rendered = {str(document.get("kind")) for document in documents(path)}
    assert rendered == expected, (
        f"{path.name} renders {sorted(rendered)}, expected {sorted(expected)}"
    )


@pytest.mark.parametrize(
    ("path", "deployment"), objects_of("Deployment"), ids=lambda x: getattr(x, "name", "")
)
def test_every_workload_has_a_readiness_and_a_liveness_probe(
    path: Path, deployment: dict[str, Any]
) -> None:
    """Two probes because they answer different questions, and a missing one fails silently.

    Without readiness, a Service sends traffic to a pod that is still starting. Without liveness, a
    wedged process stays in the endpoints list forever. Neither absence produces an error anywhere;
    both produce a service that is intermittently wrong.
    """
    for container in deployment["spec"]["template"]["spec"]["containers"]:
        name = container["name"]
        for probe in ("readinessProbe", "livenessProbe"):
            assert probe in container, f"{path.name}: container {name} has no {probe}"


def test_the_slow_starter_has_a_startup_probe() -> None:
    """MLflow migrates its schema before serving, and one probe cannot cover both phases.

    A liveness timeout generous enough for a cold Alembic run is too slow to notice a wedged server;
    one tight enough to notice restarts the pod mid-migration forever. `startupProbe` is what lets
    liveness stay aggressive without that trade.
    """
    found = [
        container
        for path, deployment in objects_of("Deployment")
        if path.name == "mlflow.yaml"
        for container in deployment["spec"]["template"]["spec"]["containers"]
    ]
    assert found, "no mlflow container found to check"
    for container in found:
        assert "startupProbe" in container, (
            f"mlflow container {container['name']} has no startupProbe, so its liveness "
            f"timeout has to cover a cold schema migration and cannot also be aggressive"
        )


@pytest.mark.parametrize(
    ("path", "deployment"), objects_of("Deployment"), ids=lambda x: getattr(x, "name", "")
)
def test_a_single_replica_on_one_volume_replaces_rather_than_rolls(
    path: Path, deployment: dict[str, Any]
) -> None:
    """A rolling update over a ReadWriteOnce volume deadlocks on itself.

    The new pod cannot mount a volume the old one still holds, and the old one is not asked to leave
    until the new one is Ready. The symptom is a Pending pod and an unchanged Deployment, with
    nothing
    in either object saying why.
    """
    mounts_a_claim = any(
        (volume.get("persistentVolumeClaim") or {}).get("claimName")
        for volume in (deployment["spec"]["template"]["spec"].get("volumes") or [])
    )
    if not mounts_a_claim:
        pytest.skip("no PersistentVolumeClaim mounted, so a rolling update cannot deadlock")
    strategy = (deployment["spec"].get("strategy") or {}).get("type")
    assert strategy == "Recreate", (
        f"{path.name} mounts a claim and uses strategy {strategy!r}; a rolling update would wait "
        f"forever on a volume the outgoing pod still holds"
    )


def test_the_autoscaled_deployment_guards_its_replica_count() -> None:
    """A Deployment with a fixed `replicas` and an HPA fight on every reconcile.

    Helm reapplies the chart's number, the autoscaler reapplies its own, and the pod count
    oscillates
    for reasons neither object explains. The field has to be *absent* when the HPA is on, not merely
    equal to minReplicas.

    Argued from the guard rather than from the pseudo-render, and that is a limitation rather than a
    preference: dropping control lines means a conditional field looks unconditionally present, so
    this technique can never show a field absent. The first version of this test asserted absence
    and
    failed against a template that was correct.
    """
    autoscaled = [path for path, _ in objects_of("HorizontalPodAutoscaler")]
    assert autoscaled, "no HorizontalPodAutoscaler found, so this test proves nothing"
    for path in set(autoscaled):
        lines = path.read_text(encoding="utf-8").splitlines()
        replicas = [n for n, line in enumerate(lines) if line.strip().startswith("replicas:")]
        for number in replicas:
            # The guard is the line above, or near enough that a reader sees them together.
            window = "\n".join(lines[max(0, number - 3) : number])
            assert "hpa.enabled" in window, (
                f"{path.name}:{number + 1} sets replicas in a template that also renders an HPA, "
                f"without a nearby guard on hpa.enabled. Helm and the autoscaler would then "
                f"overwrite each other on every reconcile."
            )


def test_every_service_targets_a_port_its_workload_defines() -> None:
    """A `targetPort` naming a port no container declares produces a Service with no endpoints.

    Nothing errors: `kubectl get svc` looks correct, and every request fails. This is the cross-
    object
    check the pseudo-render exists to make possible — a grep cannot relate two documents.
    """
    declared: dict[str, set[str]] = {}
    for _, deployment in objects_of("Deployment"):
        names = {
            port["name"]
            for container in containers(deployment)
            for port in (container.get("ports") or [])
            if "name" in port
        }
        declared[deployment["metadata"]["name"]] = names

    assert declared, "no Deployment ports found, so this test proves nothing"
    for path, service in objects_of("Service"):
        # Every object in this chart is named for its component, so the Service and the Deployment
        # it
        # fronts share a name. That is a property of the chart rather than of Kubernetes, and it is
        # what lets the two be related without rendering the selector.
        name = service["metadata"]["name"]
        assert name in declared, f"{path.name}: Service {name} fronts no Deployment of that name"
        for port in service["spec"]["ports"]:
            target = port.get("targetPort")
            if isinstance(target, str):
                assert target in declared[name], (
                    f"{path.name}: Service {name} targets port {target!r}, which its Deployment "
                    f"does "
                    f"not declare, so the Service would have no endpoints and every request would "
                    f"fail"
                )


def test_the_ingress_sends_traffic_to_a_service_that_exists() -> None:
    services = {service["metadata"]["name"] for _, service in objects_of("Service")}
    ingresses = objects_of("Ingress")
    assert ingresses, "no Ingress found, so this test proves nothing"
    for path, ingress in ingresses:
        for rule in ingress["spec"]["rules"]:
            for entry in rule["http"]["paths"]:
                backend = entry["backend"]["service"]["name"]
                assert backend in services, (
                    f"{path.name}: the Ingress routes to Service {backend!r}, which this "
                    f"chart does not render"
                )


def test_the_autoscaler_targets_a_deployment_that_exists() -> None:
    deployments = {deployment["metadata"]["name"] for _, deployment in objects_of("Deployment")}
    for path, hpa in objects_of("HorizontalPodAutoscaler"):
        target = hpa["spec"]["scaleTargetRef"]
        assert target["kind"] == "Deployment", f"{path.name}: the HPA targets a {target['kind']}"
        assert target["name"] in deployments, (
            f"{path.name}: the HPA targets {target['name']!r}, which this chart does not "
            f"render, so it would report a scaling error and never act"
        )


@pytest.mark.parametrize("path", templates(), ids=lambda p: p.name)
def test_no_template_names_a_credential_inline(path: Path) -> None:
    """Every credential arrives by `secretKeyRef`, so a literal is either a leak or a default.

    The same assertion the compose spine has carried since M0. A line mentioning a credential is
    allowed only where it names a Secret key rather than a value.
    """
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not CREDENTIAL.search(line):
            continue
        # `$(POSTGRES_PASSWORD)` is Kubernetes' own substitution, resolved in the container from
        # its environment. It is the *safe* form -- the rendered manifest carries the placeholder
        # and
        # not the value -- so a reference is what this test wants to find rather than what it
        # forbids.
        # Only a literal is a leak.
        acceptable = (
            "secretKeyRef" in line
            or ".Values.credentials" in line
            or re.search(r"\$\([A-Z_]+\)", line) is not None
            or line.strip().startswith(("#", "- name:", "key:", "name:"))
        )
        assert acceptable, f"{path.name}:{number} may name a credential inline: {line.strip()}"


@pytest.mark.parametrize("path", templates(), ids=lambda p: p.name)
def test_every_container_declares_resources_and_a_security_context(path: Path) -> None:
    """Text-level, because both arrive through `toYaml` and the pseudo-render drops what it injects.

    Weaker than the structural checks above and worth having anyway: a container with no resources
    is
    unschedulable in a namespace with a quota and invisible to an autoscaler, and one with no
    securityContext runs as whatever its image chose.
    """
    text = path.read_text(encoding="utf-8")
    if "kind: Deployment" not in text:
        pytest.skip("no Deployment in this template")
    for field in ("resources:", "securityContext:"):
        assert field in text, f"{path.name} renders a Deployment with no {field}"
    assert "runAsNonRoot" in text or "securityContext" in text, f"{path.name} sets no user"


@pytest.mark.parametrize("path", templates(), ids=lambda p: p.name)
def test_no_template_hardcodes_an_image_or_a_pull_policy(path: Path) -> None:
    """Both come from values, because both are what EKS has to change.

    A literal image reference in a template is the thing that makes "same charts on EKS" false, and
    it
    is invisible until somebody tries.
    """
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("image:"):
            assert "{{" in stripped, f"{path.name}:{number} hardcodes an image: {stripped}"
        if stripped.startswith("imagePullPolicy:"):
            assert "{{" in stripped, f"{path.name}:{number} hardcodes a pull policy: {stripped}"


def test_the_selector_holds_nothing_that_changes_between_releases() -> None:
    """A Deployment's selector is immutable, so a version in it breaks the next upgrade.

    `helm upgrade` would fail on a field the API server will not let it change, and the error names
    the selector rather than the label that moved. Asserted on the helper, since that is where a
    selector's contents are decided.
    """
    helpers = (TEMPLATE_DIR / "_helpers.tpl").read_text(encoding="utf-8")
    block = helpers.split('define "mlops-platform.selectorLabels"', 1)
    assert len(block) == 2, "the chart defines no selectorLabels helper"
    selector = block[1].split("end", 1)[0]
    for forbidden in ("helm.sh/chart", "app.kubernetes.io/version", ".Chart.Version"):
        assert forbidden not in selector, (
            f"the selector includes {forbidden}, which changes between releases; a Deployment's "
            f"selector is immutable, so the next upgrade would be rejected"
        )


def test_the_pseudo_render_would_catch_a_broken_template() -> None:
    """A parser that accepts everything proves nothing about the templates it accepted.

    The fault shown is the shape this technique exists to catch: a value indented under a key that
    already has one, which is what a mistyped `nindent` produces.
    """
    broken = (
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: {{ .Release.Name }}\n   bad: indent\n"
    )
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(pseudo_render(broken))
