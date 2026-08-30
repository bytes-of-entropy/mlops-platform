"""The Makefile is canonical and make.ps1 is its Windows mirror.

Two entrypoints means two places to forget. This test makes forgetting a red build
rather than a support question from the one reviewer running Windows.
"""

from __future__ import annotations

import re

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


def test_no_wait_is_left_unbounded() -> None:
    """``--wait`` with no ``--wait-timeout`` waits forever.

    A service that never reports healthy then hangs the job until something outside this
    repository kills it, and whatever kills it takes the compose logs with it, so the one
    artefact that would have said which service failed is the one that goes missing.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            # Comments in both files discuss the flag; only invocations can hang.
            if line.lstrip().startswith("#"):
                continue
            if WAIT_WITHOUT_TIMEOUT.search(line):
                assert "--wait-timeout" in line, f"{name}: unbounded --wait: {line.strip()}"


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
        r"^(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON)\s*\?=\s*(?P<value>\S+)$", re.MULTILINE
    ),
    "make.ps1": re.compile(
        r"^\$(?P<name>Syft|Grype|SbomDir|ScanFailOn)\s*=\s*'(?P<value>[^']+)'$", re.MULTILINE
    ),
}

#: Same four settings, spelled for each file. Makefile names are canonical.
PIN_ALIASES = {
    "Syft": "SYFT",
    "Grype": "GRYPE",
    "SbomDir": "SBOM_DIR",
    "ScanFailOn": "SCAN_FAIL_ON",
}


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
    expected = {"SYFT", "GRYPE", "SBOM_DIR", "SCAN_FAIL_ON"}
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


def test_the_cataloguers_are_pinned_to_an_exact_version() -> None:
    """A moving tag would make the committed inventory a function of the day it was regenerated.

    Not a digest pin, and record 019 records that as owed rather than done: these two references
    live in the entrypoints rather than in compose, so the digest assertion in
    tests/test_image_supply.py does not reach them. An exact tag is the weaker claim this can make
    honestly today.
    """
    for name, pins in (
        ("Makefile", cataloguer_pins("Makefile")),
        ("make.ps1", cataloguer_pins("make.ps1")),
    ):
        for tool in ("SYFT", "GRYPE"):
            reference = pins[tool]
            assert ":" in reference, f"{name}: {tool} names no tag: {reference}"
            tag = reference.rsplit(":", 1)[1].removeprefix("v")
            assert tag not in {"latest", "edge", "stable"}, f"{name}: {tool} rides {tag}"
            assert tag[0].isdigit(), f"{name}: {tool} tag is not a version: {tag}"


def test_the_scan_reads_the_sbom_rather_than_the_image() -> None:
    """Otherwise the thing scanned and the thing inventoried are two different reads of the image.

    A finding then cannot be traced to a committed line, which is most of what committing the
    inventory was for.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        body = re.search(
            r"^(?:scan:|    'scan' \{).*?(?=^(?:\S|    \}))", text, re.MULTILINE | re.DOTALL
        )
        assert body, f"{name} has no scan target for this test to look inside"
        assert "sbom:/sbom/" in body.group(0), (
            f"{name}'s scan does not point the scanner at a generated SBOM"
        )


#: An environment override, in each entrypoint's own syntax.
MAKE_OVERRIDABLE = re.compile(r"^(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON)\s*\?=", re.MULTILINE)
PS_OVERRIDABLE = re.compile(
    r"^if \(\$env:(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON)\)\s*\{", re.MULTILINE
)


def test_both_entrypoints_take_the_same_four_settings_from_the_environment() -> None:
    """An exploratory scan needs `SCAN_FAIL_ON=none`, and needing it on one platform only is a trap.

    The first scan of an image nobody has scanned wants the whole finding table rather than a gate
    that stops at the first High. If that is reachable from the Makefile and not from make.ps1, the
    person on Windows edits a tracked file to get it and the override is not what they used.
    """
    expected = {"SYFT", "GRYPE", "SBOM_DIR", "SCAN_FAIL_ON"}
    makefile = set(MAKE_OVERRIDABLE.findall((REPO_ROOT / "Makefile").read_text(encoding="utf-8")))
    powershell = set(PS_OVERRIDABLE.findall((REPO_ROOT / "make.ps1").read_text(encoding="utf-8")))
    assert makefile == expected, f"the Makefile pins these with `:=`: {sorted(expected - makefile)}"
    assert powershell == expected, f"make.ps1 ignores: {sorted(expected - powershell)}"


def test_both_entrypoints_spell_a_report_only_scan_the_same_way() -> None:
    """`--fail-on none` is not a grype value; a report-only run omits the flag.

    So both files need the same escape hatch, and it has to be the same word in both, or the one
    documented in `docs/setup.md` works on one platform and is a no-op on the other.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        body = re.search(
            r"^(?:scan:|    'scan' \{).*?(?=^(?:\S|    \}))", text, re.MULTILINE | re.DOTALL
        )
        assert body, f"{name} has no scan target"
        assert "none" in body.group(0), (
            f"{name}'s scan has no report-only path, so an exploratory scan needs a file edit"
        )
