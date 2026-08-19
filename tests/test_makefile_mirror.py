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
    repository kills it, and whatever kills it takes the compose logs with it -- so the one
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
