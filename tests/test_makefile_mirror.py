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
        r"^(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON|GRYPE_DB_VOLUME)\s*\?=\s*(?P<value>\S+)$",
        re.MULTILINE,
    ),
    "make.ps1": re.compile(
        r"^\$(?P<name>Syft|Grype|SbomDir|ScanFailOn|GrypeDbVolume)\s*=\s*'(?P<value>[^']+)'$",
        re.MULTILINE,
    ),
}

#: Same four settings, spelled for each file. Makefile names are canonical.
PIN_ALIASES = {
    "Syft": "SYFT",
    "Grype": "GRYPE",
    "SbomDir": "SBOM_DIR",
    "ScanFailOn": "SCAN_FAIL_ON",
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
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        body = re.search(
            r"^(?:scan:|    'scan' \{).*?(?=^(?:\S|    \}))", text, re.MULTILINE | re.DOTALL
        )
        assert body, f"{name} has no scan target for this test to look inside"
        assert "sbom:/sbom/" in body.group(0), (
            f"{name}'s scan does not point the scanner at a generated SBOM"
        )


#: An environment override, in each entrypoint's own syntax.
MAKE_OVERRIDABLE = re.compile(
    r"^(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON|GRYPE_DB_VOLUME)\s*\?=", re.MULTILINE
)
PS_OVERRIDABLE = re.compile(
    r"^if \(\$env:(?P<name>SYFT|GRYPE|SBOM_DIR|SCAN_FAIL_ON|GRYPE_DB_VOLUME)\)\s*\{",
    re.MULTILINE,
)


def test_both_entrypoints_take_the_same_four_settings_from_the_environment() -> None:
    """An exploratory scan needs `SCAN_FAIL_ON=none`, and needing it on one platform only is a trap.

    The first scan of an image nobody has scanned wants the whole finding table rather than a gate
    that stops at the first High. If that is reachable from the Makefile and not from make.ps1, the
    person on Windows edits a tracked file to get it and the override is not what they used.
    """
    expected = set(SUPPLY_SETTINGS)
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


def test_the_scan_reports_the_database_before_it_reports_a_finding() -> None:
    """A scan result is a function of the scanner, the database and the SBOM.

    Only the third is visible in the output, and the second is the one that goes wrong: a database
    too old to load stops the scan; one merely old enough to be useless does not. Printing
    its build date beside the findings is what makes a pasted result attributable months later.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        body = re.search(
            r"^(?:scan:|    'scan' \{).*?(?=^(?:\S|    \}))", text, re.MULTILINE | re.DOTALL
        )
        assert body, f"{name} has no scan target"
        assert "db" in body.group(0) and "status" in body.group(0), (
            f"{name}'s scan does not report the vulnerability database it used"
        )
        # `db status` reports on a database and does not fetch one. Asserted because the first
        # version of this target had the report and not the fetch, so on a fresh cache the check
        # meant to observe the database was what stopped it existing, and no scan ever ran.
        assert "update" in body.group(0), (
            f"{name}'s scan reports the database without fetching it, so a fresh cache reports "
            f"`database does not exist` and the scan is never reached"
        )


def test_the_database_cache_is_shared_across_documents() -> None:
    """`--rm` discards the container filesystem, so an uncached scan re-downloads the database.

    Six documents, six downloads of a database measured in hundreds of megabytes. Asserted rather
    than left to review because the failure is invisible in the result: the scan is correct but
    slow,
    and slow is what stops it being run.
    """
    for name in ("Makefile", "make.ps1"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        body = re.search(
            r"^(?:scan:|    'scan' \{).*?(?=^(?:\S|    \}))", text, re.MULTILINE | re.DOTALL
        )
        assert body, f"{name} has no scan target"
        assert "GRYPE_DB_CACHE_DIR" in body.group(0), (
            f"{name}'s scan names no database cache, so every document pays for its own download"
        )
