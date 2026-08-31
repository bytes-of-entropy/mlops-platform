"""The Makefile is canonical and make.ps1 is its Windows mirror.

Two entrypoints means two places to forget. This test makes forgetting a red build
rather than a support question from the one reviewer running Windows.
"""

from __future__ import annotations

import re
from datetime import date

from tests.conftest import REPO_ROOT

PHONY = re.compile(r"^\.PHONY:\s*(?P<targets>.+)$", re.MULTILINE)
PS_CASE = re.compile(r"^\s{4}'(?P<target>[a-z-]+)'\s*\{", re.MULTILINE)


def makefile_targets() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = PHONY.search(text)
    assert match, "Makefile declares no .PHONY line, so its target list is implicit"
    return set(match.group("targets").split())


def powershell_targets() -> set[str]:
    text = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    return set(PS_CASE.findall(text))


def test_no_target_exists_in_only_one_entrypoint() -> None:
    make_only = makefile_targets() - powershell_targets()
    ps_only = powershell_targets() - makefile_targets()
    assert not make_only, f"targets missing from make.ps1: {sorted(make_only)}"
    assert not ps_only, f"targets missing from the Makefile: {sorted(ps_only)}"


def test_down_keeps_volumes_and_clean_removes_them() -> None:
    """`make down` must be safe to run mid-session; only `make clean` destroys state.

    If `down` removed volumes, the idempotency this repository advertises would be
    indistinguishable from starting over, and MLflow history would vanish with it.
    """
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    down = text.split("\ndown:", 1)[1].split("\n\n", 1)[0]
    clean = text.split("\nclean:", 1)[1].split("\n\n", 1)[0]
    assert "--volumes" not in down, "make down removes volumes; that is make clean's job"
    assert "--volumes" in clean, "make clean does not remove volumes, so nothing does"


WAIT_WITHOUT_TIMEOUT = re.compile(r"--wait(?!-timeout)")
MAKE_TIMEOUT = re.compile(r"^WAIT_TIMEOUT\s*:=\s*(\d+)$", re.MULTILINE)
PS_TIMEOUT = re.compile(r"^\$WaitTimeout\s*=\s*'(\d+)'$", re.MULTILINE)


#: The flags that bound a wait. Two, because two tools here wait and they spell it differently:
#: compose takes `--wait-timeout`, helm takes `--timeout`. The property is that a wait is bounded,
#: and
#: this list is what knowing a second tool cost -- it was one entry until the chart arrived.
BOUNDING_FLAGS = ("--wait-timeout", "--timeout")


def test_no_wait_is_left_unbounded() -> None:
    """A ``--wait`` with nothing bounding it waits forever.

    Something that never reports healthy then hangs the job until an outside force kills it, and
    whatever kills it takes the logs with it, so the one artefact that would have said what failed
    is the one that goes missing. True of `compose up --wait` and of `helm upgrade --wait` alike,
    which is why the flag list has two entries rather than one.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            # Comments in both files discuss the flag; only invocations can hang.
            if line.lstrip().startswith("#"):
                continue
            if WAIT_WITHOUT_TIMEOUT.search(line):
                assert any(flag in line for flag in BOUNDING_FLAGS), (
                    f"{name}: unbounded --wait: {line.strip()}"
                )


def test_both_entrypoints_wait_the_same_length_of_time() -> None:
    """Two entrypoints means two timeouts, and a reviewer on Windows would never know."""
    make = MAKE_TIMEOUT.search((REPO_ROOT / "Makefile").read_text(encoding="utf-8"))
    powershell = PS_TIMEOUT.search((REPO_ROOT / "make.ps1").read_text(encoding="utf-8"))
    assert make, "the Makefile has no WAIT_TIMEOUT variable to check"
    assert powershell, "make.ps1 has no $WaitTimeout variable to check"
    assert int(make.group(1)) == int(powershell.group(1))
    assert int(make.group(1)) > 0, "a zero timeout is how compose spells 'wait forever'"


#: The setup body of each entrypoint, isolated so a check can look inside one rather than only at
#: the list of target names. A make target ends at the next unindented line; the PowerShell switch
#: branch ends at its closing brace, which is the only one at four-space indentation.
SETUP_BODY = {
    "Makefile": re.compile(r"^setup:.*?(?=^\S)", re.MULTILINE | re.DOTALL),
    "make.ps1": re.compile(r"^    'setup' \{.*?^    \}", re.MULTILINE | re.DOTALL),
}


def test_both_entrypoints_install_the_git_hooks_during_setup() -> None:
    """The parity test compares target *names*, so a divergence inside one body is invisible to it.

    Worth naming because the hook config was committed long before anything ran it: a
    ``.pre-commit-config.yaml`` that no installed hook and no CI job executes reads as a guarantee
    and is not one. If one entrypoint stops installing the hook, the machine that used that
    entrypoint is the one whose commits quietly stop being checked.
    """
    for name, pattern in SETUP_BODY.items():
        body = pattern.search((REPO_ROOT / name).read_text(encoding="utf-8"))
        assert body, f"{name} has no setup target for this test to look inside"
        assert "pre_commit" in body.group(0), (
            f"{name}'s setup does not install the git hooks, so a clone set up with it commits "
            f"without them"
        )


def test_the_gate_runs_the_hooks_in_both_entrypoints_and_in_ci() -> None:
    """Three places, because a hook set that runs in only some of them is a gate with a hole.

    An installed hook covers a commit made on a machine that ran setup. CI covers the clone that
    did not, and the commit made with ``--no-verify``. The gate target covers the tree as it stands
    rather than only what the last commit touched. Dropping any one of the three leaves a route
    that reaches main unchecked.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    gate = re.search(r"^check:\s*(.+)$", makefile, re.MULTILINE)
    assert gate, "the Makefile has no check target"
    assert "hooks" in gate.group(1).split(), f"make check does not run the hooks: {gate.group(1)}"

    powershell = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    ps_check = re.search(r"^    'check' \{.*?^    \}", powershell, re.MULTILINE | re.DOTALL)
    assert ps_check, "make.ps1 has no check branch"
    assert "pre_commit" in ps_check.group(0), "make.ps1's check does not run the hooks"

    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pre_commit run --all-files" in workflow, "CI does not run the hooks"


START_TARGETS = ("up", "up-quickstart")
MAKE_PREREQUISITES = re.compile(
    r"^(?P<target>up|up-quickstart):\s*(?P<prerequisites>.*)$", re.MULTILINE
)
PS_BRANCH = r"^    '{target}' \{{.*?^    \}}"


def test_both_entrypoints_run_the_doctor_before_starting_the_stack() -> None:
    """The preflight is only worth having where it cannot be skipped.

    A `make doctor` a reviewer has to remember to run is a runbook step wearing a target's clothes,
    and every failure this repository has shipped so far was a stack that started and was wrong
    rather than one that refused. Both start targets have to depend on it, in both entrypoints,
    because a reviewer on Windows uses the other file and would never see the difference.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    found = {
        match.group("target"): match.group("prerequisites")
        for match in MAKE_PREREQUISITES.finditer(makefile)
    }
    for target in START_TARGETS:
        assert target in found, f"the Makefile has no {target} target"
        assert "doctor" in found[target].split(), (
            f"make {target} does not depend on doctor, so it starts without checking: "
            f"{found[target]!r}"
        )

    powershell = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    for target in START_TARGETS:
        branch = re.search(PS_BRANCH.format(target=target), powershell, re.MULTILINE | re.DOTALL)
        assert branch, f"make.ps1 has no {target} branch"
        assert "preflight" in branch.group(0), (
            f"make.ps1's {target} starts the stack without running the doctor first"
        )


#: The supply-chain tool pins, in each entrypoint's own syntax. Compared by value rather than by
#: name, because the failure is two machines cataloguing the same image with different cataloguers:
#: both runs succeed, both write an inventory, and only one of them is the one in the diff.
CATALOGUER_PINS = {
    "Makefile": re.compile(
        r"^(?P<name>SYFT|GRYPE|SBOM_DIR|GRYPE_DB_VOLUME)\s*\?=\s*(?P<value>\S+)$",
        re.MULTILINE,
    ),
    "make.ps1": re.compile(
        r"^\$(?P<name>Syft|Grype|SbomDir|GrypeDbVolume)\s*=\s*'(?P<value>[^']+)'$",
        re.MULTILINE,
    ),
}

#: Same four settings, spelled for each file. Makefile names are canonical.
PIN_ALIASES = {
    "Syft": "SYFT",
    "Grype": "GRYPE",
    "SbomDir": "SBOM_DIR",
    "GrypeDbVolume": "GRYPE_DB_VOLUME",
}

#: Every supply setting both entrypoints must name, and name identically.
SUPPLY_SETTINGS = frozenset(PIN_ALIASES.values())


def cataloguer_pins(name: str) -> dict[str, str]:
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    found = CATALOGUER_PINS[name].finditer(text)
    return {
        PIN_ALIASES.get(match.group("name"), match.group("name")): match.group("value")
        for match in found
    }


def test_both_entrypoints_catalogue_with_the_same_tools_and_settings() -> None:
    """A pinned cataloguer is only pinned if both entrypoints name the same one.

    The inventory this repository commits is the output of a specific syft version. A Windows
    reviewer running a different one regenerates the file, sees a diff that is about the tool
    rather than about the image, and has no way to tell which it is looking at.
    """
    makefile = cataloguer_pins("Makefile")
    powershell = cataloguer_pins("make.ps1")
    expected = set(SUPPLY_SETTINGS)
    assert set(makefile) == expected, (
        f"the Makefile is missing pins: {sorted(expected - set(makefile))}"
    )
    assert set(powershell) == expected, (
        f"make.ps1 is missing pins: {sorted(expected - set(powershell))}"
    )
    differing = {
        key: (makefile[key], powershell[key])
        for key in expected
        if makefile[key] != powershell[key]
    }
    assert not differing, f"the two entrypoints disagree (Makefile, make.ps1): {differing}"


#: A reference pinned the way record 018 requires: a tag a reader recognises, then the bytes. Same
#: shape as the one in tests/test_image_supply.py, which cannot reach these two because they live in
#: the entrypoints rather than in compose.
TOOL_PINNED = re.compile(r"^[^\s@]+:v?[0-9][^\s@:]*@sha256:[0-9a-f]{64}$")


def test_the_cataloguers_are_pinned_by_tag_and_digest() -> None:
    """The tag is what a reader recognises; the digest is what actually runs.

    Record 019 recorded these two digests as owed and record 020 pays it. Worth its own assertion
    rather than folded into the compose one, because that suite reads `image` keys and would never
    see a reference that lives in a Makefile.
    """
    for name in ("Makefile", "make.ps1"):
        pins = cataloguer_pins(name)
        for tool in ("SYFT", "GRYPE"):
            reference = pins[tool]
            assert TOOL_PINNED.match(reference), (
                f"{name}: {tool} is not pinned as name:tag@sha256:<64 hex>: {reference}"
            )


#: The date past which the supply tools are presumed stale. One line, same token in both files.
EXPIRY = re.compile(r"^#\s*SUPPLY_TOOLS_EXPIRE:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def expiry(name: str) -> date:
    match = EXPIRY.search((REPO_ROOT / name).read_text(encoding="utf-8"))
    assert match, f"{name} carries no SUPPLY_TOOLS_EXPIRE line"
    return date.fromisoformat(match.group("date"))


def test_both_entrypoints_carry_the_same_supply_tool_expiry() -> None:
    """Two dates would mean one of them is the one nobody is watching."""
    assert expiry("Makefile") == expiry("make.ps1")


def test_the_supply_tools_are_not_past_their_expiry() -> None:
    """The assertion this repository learned the hard way, and the only one of its kind here.

    Every other pin ages harmlessly: an image pinned to old bytes is old and still runs. A scanner
    does not age, it stops working -- it is only as good as a vulnerability database that must be
    fresh by definition, and its publisher retires the database schema old versions speak. This
    repository's first grype pin was on the wrong side of such a retirement, and the tool refused to
    load a database 24 weeks old. That refusal was correct and it was only visible on a machine with
    a daemon, which is the worst place for a fact about a text file to hide.

    So this fails, on any machine, with no daemon, and it fails rather than warns for the reason
    record 019 gives about expired exceptions: a warning in a log is an expiry that never arrives.
    Renewing means the version, the digest and the date, edited together. Dependabot cannot do it
    for us: these two references live in a Makefile and a PowerShell script, neither of which it
    parses.
    """
    today = date.today()
    stale = {name: expiry(name) for name in ("Makefile", "make.ps1") if expiry(name) < today}
    assert not stale, (
        f"the supply tools are past their expiry: {stale}. Re-resolve both digests, bump both "
        f"versions, and move the date. A date moved on its own is what this check prevents."
    )


def test_the_scan_reads_the_sbom_rather_than_the_image() -> None:
    """Otherwise the thing scanned and the thing inventoried are two different reads of the image.

    A finding then cannot be traced to a committed line, which is most of what committing the
    inventory was for.
    """
    for name in ("Makefile", "make.ps1"):
        assert "sbom:/sbom/" in scan_body(name), (
            f"{name}'s scan does not point the scanner at a generated SBOM"
        )


#: The publishing settings, in each entrypoint's own syntax. Compared by value: two entrypoints
#: pushing to two places is one of them publishing somewhere nobody is looking.
PUBLISH_PINS = {
    "Makefile": re.compile(
        r"^(?P<name>GHCR_OWNER|GHCR_IMAGE|MLFLOW_TAG)\s*\?=\s*(?P<value>\S+)$", re.MULTILINE
    ),
    "make.ps1": re.compile(
        r"^\$(?P<name>GhcrOwner|GhcrImage|MlflowTag)\s*=\s*[\"'](?P<value>[^\"']+)[\"']$",
        re.MULTILINE,
    ),
}

PUBLISH_ALIASES = {
    "GhcrOwner": "GHCR_OWNER",
    "GhcrImage": "GHCR_IMAGE",
    "MlflowTag": "MLFLOW_TAG",
}


def publish_settings(name: str) -> dict[str, str]:
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    found = PUBLISH_PINS[name].finditer(text)
    return {
        PUBLISH_ALIASES.get(match.group("name"), match.group("name")): match.group("value")
        for match in found
    }


def push_body(name: str) -> str:
    flags = re.MULTILINE | re.DOTALL
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    pattern = r"^push:.*?(?=^\S)" if name == "Makefile" else r"^    'push' \{.*?^    \}"
    body = re.search(pattern, text, flags)
    assert body, f"{name} has no push target"
    return body.group(0)


def test_both_entrypoints_publish_the_same_image_to_the_same_place() -> None:
    """Two destinations would mean one of them is the one nobody checks.

    Compared after normalising the owner out of the image path, because the Makefile builds
    `GHCR_IMAGE` from `GHCR_OWNER` and make.ps1 interpolates it, so the literal strings differ by a
    variable reference while the value does not.
    """
    makefile = publish_settings("Makefile")
    powershell = publish_settings("make.ps1")
    expected = {"GHCR_OWNER", "GHCR_IMAGE", "MLFLOW_TAG"}
    assert set(makefile) == expected, f"the Makefile is missing: {sorted(expected - set(makefile))}"
    assert set(powershell) == expected, f"make.ps1 is missing: {sorted(expected - set(powershell))}"

    assert makefile["GHCR_OWNER"] == powershell["GHCR_OWNER"]
    assert makefile["MLFLOW_TAG"] == powershell["MLFLOW_TAG"]

    owner = makefile["GHCR_OWNER"]
    resolved = {
        makefile["GHCR_IMAGE"].replace("$(GHCR_OWNER)", owner),
        powershell["GHCR_IMAGE"].replace("$GhcrOwner", owner),
    }
    assert len(resolved) == 1, f"the two entrypoints push to different places: {sorted(resolved)}"


def test_push_publishes_the_built_image_and_nothing_else() -> None:
    """Only the image this repository builds is published, and the reason is a digest.

    Not propriety: those five images are Apache-2.0 or equivalent and mirroring public images is
    ordinary practice, which record 023 corrects itself on. The reason is that `docker tag` then
    `docker push` re-compresses layers and yields a *different* digest, so a mirror built that way
    would break record 018's invariant with the act meant to protect it -- the digest pinned in
    compose would not be the digest served. A real mirror copies manifests, with a tool this
    repository does not have and does not need for a milestone about its own image.
    """
    upstream = ("apache/", "minio/", "postgres:", "ghcr.io/mlflow/", "anchore/")
    for name in ("Makefile", "make.ps1"):
        body = push_body(name)
        offending = [
            line.strip()
            for line in body.splitlines()
            if not line.strip().startswith("#") and any(reference in line for reference in upstream)
        ]
        assert not offending, f"{name}'s push mentions an upstream image: {offending}"
        assert "mlops-platform/mlflow" in body, f"{name}'s push does not name the built image"


def test_push_depends_on_build_rather_than_hoping_for_it() -> None:
    """Pushing a tag no build produced is the one way this target can publish something else.

    A stale tag left from an earlier version of the Dockerfile would push happily and be wrong in a
    way nothing downstream could detect, since a digest is only ever compared against itself.
    """
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    declared = re.search(r"^push:\s*(.*)$", makefile, re.MULTILINE)
    assert declared, "the Makefile has no push target"
    assert "build" in declared.group(1).split(), (
        f"make push does not depend on build: {declared.group(1)!r}"
    )
    assert "build" in push_body("make.ps1"), "make.ps1's push does not build first"


def test_push_does_not_handle_a_credential() -> None:
    """A login belongs in the operator's session, never in something this repository can read.

    Asserted rather than trusted, because a `docker login` in a target is the natural next thing
    somebody adds when a push fails anonymously, and the token then has to come from somewhere.
    """
    for name in ("Makefile", "make.ps1"):
        body = push_body(name)
        for forbidden in ("docker login", "--password", "GITHUB_TOKEN", "GHCR_TOKEN", "CR_PAT"):
            assert forbidden not in body, f"{name}'s push handles a credential: {forbidden}"


def test_the_built_image_declares_where_it_came_from() -> None:
    """The label a registry reads to attach a published package to its repository.

    Without it a pushed image is an artifact under an account with nothing tying it to the source
    that produced it, and the visibility that should follow the repository has to be set by hand.
    Worth a test because it is invisible in normal use: nothing about running the spine cares.
    """
    dockerfile = (REPO_ROOT / "images/mlflow/Dockerfile").read_text(encoding="utf-8")
    assert "org.opencontainers.image.source" in dockerfile, (
        "the built image declares no source, so a published package cannot link to this repository"
    )


#: The cluster and chart settings, in each entrypoint's own syntax. Same reason as the cataloguer
#: pins: two entrypoints naming two node images, or two namespaces, is one of them deploying
#: somewhere
#: nobody is looking at.
CLUSTER_PINS = {
    "Makefile": re.compile(
        r"^(?P<name>KIND_CLUSTER|KIND_CONFIG|KIND_NODE_IMAGE|METRICS_SERVER|INGRESS_NGINX|CHART"
        r"|RELEASE|K8S_NAMESPACE)\s*\?=\s*(?P<value>\S+)$",
        re.MULTILINE,
    ),
    "make.ps1": re.compile(
        r"^\$(?P<name>KindCluster|KindConfig|KindNodeImage|MetricsServer|IngressNginx|Chart"
        r"|Release|K8sNamespace)\s*=\s*'(?P<value>[^']+)'$",
        re.MULTILINE,
    ),
}

CLUSTER_ALIASES = {
    "KindCluster": "KIND_CLUSTER",
    "KindConfig": "KIND_CONFIG",
    "KindNodeImage": "KIND_NODE_IMAGE",
    "MetricsServer": "METRICS_SERVER",
    "IngressNginx": "INGRESS_NGINX",
    "Chart": "CHART",
    "Release": "RELEASE",
    "K8sNamespace": "K8S_NAMESPACE",
}


def cluster_settings(name: str) -> dict[str, str]:
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    return {
        CLUSTER_ALIASES.get(match.group("name"), match.group("name")): match.group("value")
        for match in CLUSTER_PINS[name].finditer(text)
    }


def test_both_entrypoints_target_the_same_cluster_with_the_same_add_ons() -> None:
    """Two node images or two namespaces means one entrypoint deploys where nobody is looking.

    The node image matters most: it and the kind binary are a matched pair, so an entrypoint pinning
    a different one produces a cluster whose API server version differs from the other's, and a
    manifest that applies on one machine can be rejected on the other.
    """
    makefile = cluster_settings("Makefile")
    powershell = cluster_settings("make.ps1")
    expected = set(CLUSTER_ALIASES.values())
    assert set(makefile) == expected, f"the Makefile is missing: {sorted(expected - set(makefile))}"
    assert set(powershell) == expected, f"make.ps1 is missing: {sorted(expected - set(powershell))}"
    differing = {
        key: (makefile[key], powershell[key])
        for key in expected
        if makefile[key] != powershell[key]
    }
    assert not differing, f"the two entrypoints disagree (Makefile, make.ps1): {differing}"


def test_the_kind_node_image_is_pinned_by_digest() -> None:
    """A node image is where the cluster's Kubernetes version comes from.

    Unpinned, `kind create` follows whatever the installed kind defaults to, so the cluster the
    chart was tested against and the one a reviewer gets are different clusters. Pinned by digest as
    well as tag, for the reason record 018 gives about every other image here.
    """
    image = cluster_settings("Makefile")["KIND_NODE_IMAGE"]
    assert "@sha256:" in image, f"the kind node image is not digest-pinned: {image}"
    assert image.startswith("kindest/node:v"), f"unexpected node image: {image}"


def test_the_cluster_add_ons_are_pinned_to_a_release() -> None:
    """A manifest fetched from a moving ref is a cluster whose contents change without a commit."""
    settings = cluster_settings("Makefile")
    for key in ("METRICS_SERVER", "INGRESS_NGINX"):
        value = settings[key]
        assert value not in {"latest", "main", "master"}, f"{key} rides {value!r}"
        assert any(char.isdigit() for char in value), f"{key} names no version: {value!r}"


def test_kind_deploy_loads_the_locally_built_image() -> None:
    """A kind node has its own image store and cannot pull an image that exists only locally.

    Without `kind load` the MLflow pod sits in ImagePullBackOff naming an image `docker images`
    shows on the very same machine, which is among the more confusing failures kind produces.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        pattern = (
            r"^kind-deploy:.*?(?=^\S)" if name == "Makefile" else r"^    'kind-deploy' \{.*?^    \}"
        )
        body = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        assert body, f"{name} has no kind-deploy target"
        assert "load" in body.group(0) and "docker-image" in body.group(0), (
            f"{name}'s kind-deploy does not load the built image into the cluster, so the pod will "
            f"fail to pull an image that exists on the same machine"
        )


def test_the_chart_secret_is_never_built_from_a_literal() -> None:
    """`--from-literal` puts the credential in the command line, and so in the process table.

    `--from-env-file` reads the same `.env` compose reads and puts nothing in argv. Asserted because
    the literal form is the one every tutorial shows.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        offending = [
            line.strip()
            for line in text.splitlines()
            if "--from-literal" in line and not line.strip().startswith("#")
        ]
        assert not offending, f"{name} builds a Secret from a literal: {offending}"


#: An environment override, in each entrypoint's own syntax.
MAKE_OVERRIDABLE = re.compile(r"^(?P<name>SYFT|GRYPE|SBOM_DIR|GRYPE_DB_VOLUME)\s*\?=", re.MULTILINE)
PS_OVERRIDABLE = re.compile(
    r"^if \(\$env:(?P<name>SYFT|GRYPE|SBOM_DIR|GRYPE_DB_VOLUME)\)\s*\{",
    re.MULTILINE,
)


def test_both_entrypoints_take_the_same_settings_from_the_environment() -> None:
    """A setting honoured on one platform and ignored on the other is worse than no setting.

    The person who needs it edits a tracked file to get it, and what they ran is then not what is
    committed. `SBOM_DIR` and `GRYPE_DB_VOLUME` are the two reached for in practice; the cataloguer
    pins are here because a machine pinning a different syft writes a different inventory.
    """
    expected = set(SUPPLY_SETTINGS)
    makefile = set(MAKE_OVERRIDABLE.findall((REPO_ROOT / "Makefile").read_text(encoding="utf-8")))
    powershell = set(PS_OVERRIDABLE.findall((REPO_ROOT / "make.ps1").read_text(encoding="utf-8")))
    assert makefile == expected, f"the Makefile pins these with `:=`: {sorted(expected - makefile)}"
    assert powershell == expected, f"make.ps1 ignores: {sorted(expected - powershell)}"


#: A make recipe: the target line and everything indented under it, to the next unindented line.
MAKE_RECIPE = "^{target}:.*?(?=^\\S)"

#: A PowerShell switch arm, or a function body. Both end at the closing brace that sits at their own
#: indentation, which is the only one that does.
PS_ARM = "^    '{target}' \\{{.*?^    \\}}"
PS_FUNCTION = "^function {name} \\{{.*?^\\}}"


def scan_body(name: str) -> str:
    """Everything the `scan` target reaches, following delegation rather than stopping at it.

    Both entrypoints factored the scanning out of the gate once there were three things to do with
    one answer: the Makefile made `scan` depend on `scan-report`, and make.ps1 moved it into
    `Invoke-Scan`. A body-only search would then report a missing docker invocation that is one
    delegation away, which is a test failing for the wrong reason and the most expensive kind.

    So this walks what the target actually reaches. Named delegations only -- no general resolver --
    because the point is to assert the scan path's *content*, and a resolver clever enough to follow
    anything would also be clever enough to follow its way to a passing answer.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    flags = re.MULTILINE | re.DOTALL
    found = ""
    if name == "Makefile":
        for target in ("scan", "scan-report"):
            match = re.search(MAKE_RECIPE.format(target=target), text, flags)
            assert match, f"Makefile has no {target} target"
            found += match.group(0)
    else:
        match = re.search(PS_ARM.format(target="scan"), text, flags)
        assert match, "make.ps1 has no scan branch"
        found += match.group(0)
        for helper in ("Invoke-Scan", "Invoke-GrypeDb"):
            if helper in found:
                body = re.search(PS_FUNCTION.format(name=helper), text, flags)
                assert body, f"make.ps1 calls {helper} and does not define it"
                found += body.group(0)
    return found


def test_the_scan_fetches_the_database_and_then_reports_it() -> None:
    """A scan result is a function of the scanner, the database and the SBOM.

    Only the third is visible in the output, and the second is the one that goes wrong: a database
    too old to load stops the scan; one merely old enough to be useless does not. Printing its build
    date beside the findings is what makes a pasted result readable months later.

    Both verbs, in that order, because `db status` reports on a database and does not fetch one. The
    first version of this target had the report and not the fetch, so on a fresh cache the check
    written to observe the database was what stopped it existing, and no scan ever ran.
    """
    for name in ("Makefile", "make.ps1"):
        body = scan_body(name)
        assert "status" in body, f"{name}'s scan does not report the database it used"
        assert "update" in body, (
            f"{name}'s scan reports the database without fetching it, so a fresh cache reports "
            f"`database does not exist` and the scan is never reached"
        )


def test_neither_entrypoint_gates_on_severity_any_more() -> None:
    """`--fail-on` is the gate record 022 replaced, and leaving it in would gate twice.

    After record 021 the residue is 138 Critical and 870 High with no fix inside the current major
    line, so a severity threshold fails identically on every run and tells nobody anything. Worse,
    it would fail the build *before* the baseline comparison ran, so the useful message -- which
    advisory is new -- would never be printed.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        offending = [
            line.strip()
            for line in text.splitlines()
            if "--fail-on" in line and not line.strip().startswith("#")
        ]
        assert not offending, f"{name} still gates on severity: {offending}"


def test_both_entrypoints_gate_on_the_committed_baseline() -> None:
    """The gate itself, in both, because a scan that reports and never compares is a report.

    `supply.findings` is what turns a scan into a gate: it fails on an advisory identifier absent
    from that image's committed baseline. A run that produced the table and skipped the comparison
    would look identical in a log right up to the exit code.
    """
    for name in ("Makefile", "make.ps1"):
        body = scan_body(name)
        assert "supply.findings" in body, (
            f"{name}'s scan does not compare against a baseline, so it reports rather than gates"
        )
        assert ".known.txt" in body, f"{name}'s scan names no baseline file"


def test_a_baseline_moves_only_on_purpose() -> None:
    """Accepting has to be possible, separate, and impossible to do by accident.

    A `--force` on `scan` would have been one keystroke from silently accepting whatever appeared,
    which is the failure mode record 019 designed `security/exceptions.toml` around. A separate
    target means the record of what was accepted is a diff somebody reads.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "scan-accept" in text, f"{name} has no way to move a baseline"
        assert "--accept" in text, f"{name}'s scan-accept does not pass --accept"
        assert "--accept" not in scan_body(name), (
            f"{name}'s scan target can accept advisories, so the gate can be passed by running it"
        )


def test_the_database_cache_is_shared_across_documents() -> None:
    """`--rm` discards the container filesystem, so an uncached scan re-downloads the database.

    Six documents, six downloads of a database measured in hundreds of megabytes. Asserted rather
    than left to review because the failure is invisible in the result: the scan is correct but
    slow, and slow is what stops it being run.
    """
    for name in ("Makefile", "make.ps1"):
        assert "GRYPE_DB_CACHE_DIR" in scan_body(name), (
            f"{name}'s scan names no database cache, so every document pays for its own download"
        )
