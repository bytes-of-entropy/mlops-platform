"""One place the cluster tier builds a kind, kubectl or helm invocation, and runs one.

The compose tier has `stackops.py` and this is its counterpart, built on the same two decisions.

**Its own cluster, not the one an operator made.** `stackops` runs under its own compose project
so a volume left behind by a by-hand session cannot decide whether the suite passes; the same
argument applies here with a cluster in place of a volume. `make kind-up` creates `mlops-platform`
and this creates `mlops-platform-tests`, so the two never meet. The cost is that the tier does not
exercise the make target, which is the cost the compose tier already pays and the reason
`test_compose_paths.py` exists — `test_cluster_paths` is its analogue.

**Every failure reports itself.** `Cluster.check` raises through `describe_process` with the
command, the exit code, both streams and the cluster state gathered afterwards. Nothing here or in
the tier may assert on a return code, and `test_failure_reports.py` enforces that on this file:
an integration failure is produced on one machine and read on another, and a bare "helm install
failed" costs a round trip to ask what it said.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from tests.conftest import REPO_ROOT, describe_process

#: The tier's own cluster, distinct from the one `make kind-up` creates for a person to look at.
TEST_CLUSTER = "mlops-platform-tests"
TEST_NAMESPACE = "mlops-tests"
TEST_RELEASE = "mlops-platform"

CONTEXT = f"kind-{TEST_CLUSTER}"

CHART = "charts/mlops-platform"
KIND_CONFIG = "charts/kind-cluster.yaml"
METRICS_PATCH = "charts/metrics-server-insecure-tls.json"

#: Creating a cluster pulls a node image and starts a control plane; installing waits on three
#: workloads. Generous, and bounded: an unbounded wait hangs the job until something outside this
#: repository kills it, and takes the logs with it.
TIMEOUT_S = 900
WAIT_S = 300

#: How much of a stream a failure keeps. The same shape `stackops` uses.
LOG_TAIL_LINES = 40

#: The load generator the HPA test starts, and the test that started it deletes.
LOAD_DEPLOYMENT = "loadgen"

#: How anything this file runs inside a pod is invoked. The built image's own interpreter, which is
#: the only one on that filesystem, so nothing here depends on a shell being present in it.
INTERPRETER = ("python", "-c")

#: What the load generator asks for. A search touches Postgres; `/health` returns a constant.
#: MLflow's search is POST-only, so the first version of this -- a GET with a query string -- would
#: have been answered with 405 out of the router, before anything reached a database.
LOAD_PATH = "/api/2.0/mlflow/experiments/search"
LOAD_BODY = {"max_results": 1000}

#: How often to re-ask a cluster a question whose answer it computes on its own schedule.
POLL_S = 5


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=False,
        env={**os.environ},
    )


def settings() -> dict[str, str]:
    """The four external versions, read out of the Makefile rather than repeated here.

    A second copy would be a second thing to bump, and the one that did not get bumped would be the
    one the tier used. `test_cluster_paths` asserts these resolve.
    """
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for line in text.splitlines():
        if "?=" not in line or line.lstrip().startswith("#"):
            continue
        name, _, value = line.partition("?=")
        found[name.strip()] = value.strip()
    return found


def load_script(target: str, port: int, threads: int) -> str:
    """The load generator's program, as its own function so a test can compile it.

    Joined with newlines rather than semicolons, and that is the whole reason this is not inline any
    more. The first version was `";".join(...)` with a `def` among the parts, which is a
    `SyntaxError` -- a compound statement cannot follow a semicolon. Every generator pod crashed on
    start, the HPA read 0% for four minutes, and the test reported that the autoscaler had not
    scaled: a true sentence about the wrong subject, costing a build-machine run to learn.

    `compile()` on this string is a laptop-checkable assertion, which is what
    `test_the_load_generator_is_valid_python` now is.
    """
    return "\n".join(
        (
            "import json, threading, urllib.request",
            f"url = 'http://{target}:{port}{LOAD_PATH}'",
            f"body = json.dumps({LOAD_BODY!r}).encode()",
            "headers = {'Content-Type': 'application/json'}",
            "def work():",
            "    while True:",
            "        try:",
            "            request = urllib.request.Request(url, data=body, headers=headers)",
            "            urllib.request.urlopen(request, timeout=5).read()",
            "        except Exception:",
            "            pass",
            f"threads = [threading.Thread(target=work, daemon=True) for _ in range({threads})]",
            "[thread.start() for thread in threads]",
            "[thread.join() for thread in threads]",
        )
    )


@dataclass(frozen=True)
class Cluster:
    """A kind cluster the tier owns for the length of a module."""

    name: str = TEST_CLUSTER
    namespace: str = TEST_NAMESPACE

    @property
    def context(self) -> str:
        return f"kind-{self.name}"

    def kubectl(self, *args: str) -> list[str]:
        return ["kubectl", "--context", self.context, "-n", self.namespace, *args]

    def diagnostics(self) -> dict[str, str]:
        """What a reader needs and `kubectl` will not volunteer.

        Events rather than only pod status: a pod that never schedules has no logs and no
        container state, and the reason it did not schedule is an event. Best effort throughout —
        this runs while something has failed, so it must never raise and mask what it describes.
        """
        gathered: dict[str, str] = {}
        for label, args in (
            ("pods", ("get", "pods", "-o", "wide")),
            ("events", ("get", "events", "--sort-by=.lastTimestamp")),
            ("deployments", ("get", "deploy")),
            ("hpa", ("get", "hpa")),
        ):
            try:
                result = run(self.kubectl(*args))
            except (OSError, subprocess.SubprocessError):
                continue
            text = (result.stdout or result.stderr or "").strip()
            if text:
                gathered[label] = "\n".join(text.splitlines()[-LOG_TAIL_LINES:])
        return gathered

    def check(self, label: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
        """Run something, and if it fails say everything about how it failed."""
        result = run(argv)
        if result.returncode != 0:
            raise AssertionError(
                describe_process(
                    label, argv, result.returncode, result.stdout, result.stderr, self.diagnostics()
                )
            )
        return result

    def exists(self) -> bool:
        try:
            listed = run(["kind", "get", "clusters"])
        except (OSError, subprocess.SubprocessError):
            return False
        return self.name in (listed.stdout or "").split()

    def clusters(self) -> list[str]:
        try:
            listed = run(["kind", "get", "clusters"])
        except (OSError, subprocess.SubprocessError):
            return []
        return [name for name in (listed.stdout or "").split() if name != "No"]

    def refuse_a_port_conflict(self) -> None:
        """One cluster at a time, because the kind config publishes host ports 80 and 443.

        Both this cluster and the one `make kind-up` creates use `charts/kind-cluster.yaml`, and the
        second `kind create` to ask for port 80 fails on the bind. That failure is real but reads as
        a broken cluster config rather than as two clusters wanting one port, so it is worth naming
        here: separate names keep the clusters from sharing *state*, and nothing can make them share
        a host port.
        """
        others = [name for name in self.clusters() if name != self.name]
        assert not others, (
            f"another kind cluster is running: {others}. Both it and {self.name} publish host "
            f"ports 80 and 443 from {KIND_CONFIG}, so the second to start cannot bind them. Run "
            f"`make kind-down` first — the tier's own cluster is disposable and so is that one."
        )

    def create(self) -> None:
        values = settings()
        self.refuse_a_port_conflict()
        if not self.exists():
            self.check(
                "kind create cluster",
                [
                    "kind",
                    "create",
                    "cluster",
                    "--name",
                    self.name,
                    "--config",
                    KIND_CONFIG,
                    "--image",
                    values["KIND_NODE_IMAGE"],
                ],
            )
        # metrics-server, because an HPA with nothing to read reports <unknown> rather than failing,
        # and a test that waited for a replica count would then time out for the wrong reason.
        metrics = (
            "https://github.com/kubernetes-sigs/metrics-server/releases/download/"
            f"{values['METRICS_SERVER']}/components.yaml"
        )
        self.check(
            "apply metrics-server",
            ["kubectl", "--context", self.context, "apply", "-f", metrics],
        )
        self.check(
            "patch metrics-server for kind",
            [
                "kubectl",
                "--context",
                self.context,
                "-n",
                "kube-system",
                "patch",
                "deployment",
                "metrics-server",
                "--type=json",
                # The same committed file both make targets pass. Inline JSON works from Python,
                # which builds argv directly, and does not work from PowerShell -- so a third copy
                # of the patch here would be a third thing to keep in step and the only one whose
                # shell tolerated it.
                "--patch-file",
                METRICS_PATCH,
            ],
        )
        ingress = (
            "https://raw.githubusercontent.com/kubernetes/ingress-nginx/"
            f"{values['INGRESS_NGINX']}/deploy/static/provider/kind/deploy.yaml"
        )
        self.check(
            "apply ingress-nginx",
            ["kubectl", "--context", self.context, "apply", "-f", ingress],
        )
        for namespace, deployment in (
            ("kube-system", "metrics-server"),
            ("ingress-nginx", "ingress-nginx-controller"),
        ):
            self.check(
                f"wait for {deployment}",
                [
                    "kubectl",
                    "--context",
                    self.context,
                    "-n",
                    namespace,
                    "wait",
                    "--for=condition=available",
                    f"deployment/{deployment}",
                    f"--timeout={WAIT_S}s",
                ],
            )

    def load_built_image(self) -> None:
        """A kind node has its own image store and cannot pull an image that exists only locally."""
        tag = settings()["MLFLOW_TAG"]
        self.check(
            "kind load",
            ["kind", "load", "docker-image", "--name", self.name, f"mlops-platform/mlflow:{tag}"],
        )

    def create_namespace_and_secret(self) -> None:
        """The credentials, from the same `.env` compose reads, never from the chart.

        Deleted first so re-running is safe, and created with `--from-env-file` so no credential
        reaches the command line, where it would be visible in the process table.
        """
        for args in (
            [
                "kubectl",
                "--context",
                self.context,
                "delete",
                "namespace",
                self.namespace,
                "--ignore-not-found",
            ],
            ["kubectl", "--context", self.context, "create", "namespace", self.namespace],
        ):
            self.check("namespace", args)
        self.check(
            "create credentials secret",
            [
                *self.kubectl("create", "secret", "generic", "mlops-platform-credentials"),
                "--from-env-file=.env",
            ],
        )

    def install(self) -> None:
        """The chart as `make kind-deploy` installs it: default values, no overrides.

        Not the quickstart values, even though they are lighter. The quickstart file exists for a
        reviewer's laptop; `kind-deploy` is the documented path and its HPA bounds, requests and
        probe thresholds are the ones a claim in the README rests on. A tier that only ever
        installed the lighter file would leave the shipped configuration installed nowhere.
        """
        self.check(
            "helm upgrade --install",
            [
                "helm",
                "--kube-context",
                self.context,
                "upgrade",
                "--install",
                TEST_RELEASE,
                CHART,
                "--namespace",
                self.namespace,
                "--wait",
                "--timeout",
                f"{WAIT_S}s",
            ],
        )

    def destroy(self) -> None:
        self.check("kind delete cluster", ["kind", "delete", "cluster", "--name", self.name])

    def available_deployments(self) -> set[str]:
        """Deployments reporting Available, which is the condition `--wait` waits on."""
        result = self.check("get deployments", self.kubectl("get", "deploy", "-o", "json"))
        listed = json.loads(result.stdout)
        found = set()
        for item in listed.get("items", []):
            conditions = {
                condition["type"]: condition["status"]
                for condition in item.get("status", {}).get("conditions", [])
            }
            if conditions.get("Available") == "True":
                found.add(item["metadata"]["name"])
        return found

    def rendered(self) -> list[dict[str, object]]:
        """What helm actually renders, which is the thing the contract tier can only approximate."""
        result = self.check(
            "helm template",
            ["helm", "template", TEST_RELEASE, CHART, "--namespace", self.namespace],
        )
        return [document for document in yaml.safe_load_all(result.stdout) if document]

    def replicas(self, deployment: str) -> int:
        result = self.check(
            "get replicas",
            self.kubectl("get", "deploy", deployment, "-o", "jsonpath={.status.replicas}"),
        )
        return int(result.stdout.strip() or 0)

    def logs(self, selector: str, container: str | None = None) -> str:
        args = ["logs", "-l", selector, "--tail", str(LOG_TAIL_LINES)]
        if container is not None:
            args += ["-c", container]
        return self.check("get logs", self.kubectl(*args)).stdout

    def exec_script(self, deployment: str, script: str) -> str:
        """Run a snippet inside a running pod, which is where the credentials already are.

        Checking MinIO from outside the cluster would mean either publishing its port or handing a
        credential to this process. The MLflow pod already holds both the client library and the
        Secret's values in its environment, so the check runs where the answer is.
        """
        return self.check(
            f"exec in {deployment}",
            self.kubectl("exec", f"deploy/{deployment}", "--", *INTERPRETER, script),
        ).stdout

    def ask_from_inside(self, deployment: str, url: str, payload: str | None = None) -> str:
        """Make one HTTP request from inside a pod, bypassing the Ingress entirely.

        This splits a question the first run could not answer. `/health` returned 200 through the
        Ingress and the API returned 503 seconds later, and 503 is what nginx says when it has no
        ready endpoint as well as something an application can say for itself. Asking the same URL
        from inside the cluster separates the two: if this succeeds and the Ingress does not, the
        Ingress or its endpoints are the subject; if both refuse, MLflow is.

        Prints the status and the start of the body rather than raising on an HTTP error, because
        the status is the finding here and a non-2xx is what the caller is investigating.
        """
        body = "None" if payload is None else repr(payload.encode())
        script = "\n".join(
            (
                "import urllib.error, urllib.request",
                f"request = urllib.request.Request({url!r}, data={body})",
                "request.add_header('Content-Type', 'application/json')",
                "try:",
                "    response = urllib.request.urlopen(request, timeout=20)",
                "    print('status', response.status)",
                "    print(response.read()[:400].decode('utf-8', 'replace'))",
                "except urllib.error.HTTPError as error:",
                "    print('status', error.code)",
                "    print('server', error.headers.get('Server', 'unnamed'))",
                "    print(error.read()[:400].decode('utf-8', 'replace'))",
                "except Exception as error:",
                "    print('no answer at all:', type(error).__name__, error)",
            )
        )
        return self.exec_script(deployment, script)

    def start_load(self, target: str, port: int, replicas: int, threads: int) -> None:
        """Enough CPU on the target to move an HPA, generated from inside the cluster.

        `kubectl create deployment` rather than a manifest, because a load generator is not part of
        the chart and should not live anywhere a reader might mistake for part of it. The image is
        the one already loaded onto the node: a generator needs an HTTP client and a loop, and a
        second image would be another reference to pin for six lines of code.

        The endpoint is a search rather than `/health`, because `/health` returns a constant and a
        server can answer it out of almost no CPU. A search reaches Postgres through the connection
        pool, which is the work the request path actually does, and MLflow's search is a POST with a
        JSON body rather than a GET.
        """
        script = load_script(target, port, threads)
        tag = settings()["MLFLOW_TAG"]
        self.check(
            "create load generator",
            [
                *self.kubectl("create", "deployment", LOAD_DEPLOYMENT),
                f"--image=mlops-platform/mlflow:{tag}",
                f"--replicas={replicas}",
                "--",
                *INTERPRETER,
                script,
            ],
        )

    def stop_load(self) -> None:
        self.check(
            "delete load generator",
            self.kubectl("delete", "deployment", LOAD_DEPLOYMENT, "--ignore-not-found"),
        )

    def hpa_utilisation(self, name: str) -> int | None:
        """The HPA's current CPU reading, or None while it still reports `<unknown>`.

        None and 0 are different answers, and conflating them hides the failure this exists to
        surface: an HPA with no metrics-server reads `<unknown>` forever and never scales, which
        from the outside looks exactly like a load generator that is not generating load.
        """
        path = "{.status.currentMetrics[0].resource.current.averageUtilization}"
        result = self.check(
            "get hpa utilisation", self.kubectl("get", "hpa", name, "-o", f"jsonpath={path}")
        )
        text = result.stdout.strip()
        return int(text) if text else None

    def poll(self, condition: Callable[[], bool], deadline_s: int) -> bool:
        """Wait for something the cluster decides on its own schedule.

        The unit tiers forbid sleeping and are right to: a sleep there is a guess standing in for a
        signal. Here the signal genuinely arrives late — an HPA recomputes on its own interval and
        no amount of asking sooner makes it decide sooner — so the wait is bounded, and this is the
        only place in the suite that does it.
        """
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(POLL_S)
        return condition()
