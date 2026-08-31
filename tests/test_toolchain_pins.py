"""A pinned tool version must be the same version in every place that names one.

Pinning buys reproducibility only if the pin is single-valued. Ruff's version is named in three
places: the dev extra that installs it, the pre-commit rev that runs it on commit, and the
environment actually executing this suite, and none of the three reads the others. A bump that
updates one of them produces a hook that reformats what the gate then rejects, or a green local run
against a version CI does not install.

This file is a deliberate copy of the same test in the graph repository rather than a shared import.
The two repositories share a lint policy but not a package, and a library existing only to hold two
test files would be a dependency for each of them to install, pin, and keep current.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

#: Hook repositories whose ``rev`` is a release of a tool this project also installs from PyPI, and
#: the PyPI name of that tool. A hook repository absent from this mapping pins something with no
#: PyPI counterpart (``pre-commit-hooks`` is the example) and has nothing to agree with.
HOOK_REPO_TO_DISTRIBUTION = {
    "https://github.com/astral-sh/ruff-pre-commit": "ruff",
    "https://github.com/pre-commit/mirrors-mypy": "mypy",
}
#: ``- repo: <url>`` followed, at any distance, by that block's ``rev: <version>``. Non-greedy so a
#: rev is attributed to the nearest preceding repo rather than the first one in the file.
HOOK_BLOCK = re.compile(r"-\s+repo:\s*(\S+).*?\n\s*rev:\s*(\S+)", re.DOTALL)
DISTRIBUTION_PIN = re.compile(r"^([A-Za-z0-9._-]+)==(.+)$")


def pinned_versions() -> dict[str, str]:
    """The dev extra, as ``{distribution: exact version}``. Unpinned entries are skipped."""
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pins = {}
    for requirement in config["project"]["optional-dependencies"]["dev"]:
        matched = DISTRIBUTION_PIN.match(requirement.strip())
        if matched:
            pins[matched.group(1).lower()] = matched.group(2)
    return pins


def hook_revisions() -> dict[str, str]:
    """The pre-commit config, as ``{repo url: rev}``."""
    text = PRE_COMMIT.read_text(encoding="utf-8")
    return dict(HOOK_BLOCK.findall(text))


def test_every_hook_that_mirrors_a_pinned_tool_runs_the_pinned_version() -> None:
    pins = pinned_versions()
    revisions = hook_revisions()
    compared = 0
    for url, distribution in HOOK_REPO_TO_DISTRIBUTION.items():
        if url not in revisions or distribution not in pins:
            continue
        # pre-commit tags releases as ``vX.Y.Z``; PyPI does not carry the ``v``.
        assert revisions[url] == f"v{pins[distribution]}", (
            f"{distribution} is pinned at {pins[distribution]} but the hook runs "
            f"{revisions[url]}: the hook would reformat what the gate rejects"
        )
        compared += 1
    assert compared, (
        "no hook was compared against a pin, so this test asserted nothing. Either the config "
        "parsers stopped matching, or a hook repository was renamed and HOOK_REPO_TO_DISTRIBUTION "
        "needs the new URL"
    )


def test_the_interpreter_running_this_suite_has_the_pinned_ruff() -> None:
    """Catches the stale virtual environment, which passes every other check in the gate.

    A venv created before a bump keeps running the old ruff. Its formatting differs from the pinned
    version's, so the local gate goes green on a style CI will reject, and the failure surfaces as
    a formatting diff in CI with no local reproduction, which is the expensive way to find it.
    """
    # Fixed argv, this interpreter, no shell. No `noqa` for S603: this version of ruff does not
    # flag a subprocess call whose argument list is a literal, so a directive here would be dead.
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    installed = completed.stdout.split()[-1]
    expected = pinned_versions()["ruff"]
    assert installed == expected, (
        f"pyproject pins ruff {expected}, this environment has {installed}. "
        f"Re-run the setup target to reinstall the dev extra"
    )


#: A commit SHA is 40 hex characters. A tag -- `v4`, `v7.0.1` -- is a pointer its publisher can
#: move, which is the same objection record 018 makes to an image tag.
ACTION_SHA = re.compile(r"^uses:\s+[\w.-]+/[\w.-]+@[0-9a-f]{40}\s*(#.*)?$")

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def workflow_uses() -> list[tuple[str, int, str]]:
    """Every `uses:` line in every workflow, with its file and line number."""
    found = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # A step is a list item, so most of these read `- uses: ...`. Dropping the marker is
            # what makes the pattern below match; the first version of this found one line in ten.
            stripped = line.strip().removeprefix("- ").strip()
            if stripped.startswith("uses:"):
                found.append((path.name, number, stripped))
    return found


def test_there_are_workflow_actions_to_check() -> None:
    """The anti-vacuity guard: this rule is worthless against zero actions."""
    assert len(workflow_uses()) >= 4, "no workflow actions found, so the pin rule proves nothing"


def test_every_workflow_action_is_pinned_to_a_commit() -> None:
    """Record 018's rule, applied to the other third-party code this repository pulls.

    An action is not a passive dependency. It runs on the runner with the workflow's token and can
    read anything the job can, so `@v4` is a promise by a publisher that code behind a moving tag
    will stay trustworthy -- exactly the promise record 018 declines to accept from a registry. The
    argument does not weaken because the artefact is JavaScript rather than a layer.

    The version stays in a trailing comment, because a bare SHA tells a reader nothing about how old
    it is and a bump has to be legible in review.
    """
    unpinned = [
        f"{name}:{number}: {line}"
        for name, number, line in workflow_uses()
        if not ACTION_SHA.match(line)
    ]
    assert not unpinned, (
        f"{len(unpinned)} action(s) ride a tag rather than a commit: {unpinned}. A tag is a "
        f"pointer its publisher can move, and an action runs with the job's credentials"
    )


def test_every_pinned_action_says_which_version_it_is() -> None:
    """A forty-character hex string with no comment is unreviewable and unbumpable."""
    without = [
        f"{name}:{number}"
        for name, number, line in workflow_uses()
        if "#" not in line or not line.split("#", 1)[1].strip()
    ]
    assert not without, f"pinned action(s) with no version comment: {without}"
