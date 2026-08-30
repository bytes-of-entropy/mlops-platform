"""Every Makefile recipe is valid shell, checked without running any of it.

The Makefile is canonical and nothing executes it. CI calls the tools directly, in the same order,
rather than through `make`; the build machine is Windows and uses `make.ps1`. So the recipes are
authored and never run, and a quoting mistake in one would sit there until the first person on Linux
tried the documented command -- which, for a repository whose whole subject is that the documented
command works, is the wrong person to find it.

`sh -n` parses without executing: no container starts, no file is written, no network is touched. It
catches what actually goes wrong in a recipe written by hand -- an unbalanced quote, a `do` with no
`done`, a brace group missing its semicolon -- and nothing else. It says nothing about whether the
commands are correct, only that a shell would accept them, which is precisely the gap between a
recipe that has been read and one that has been run.

Make expands its own variables before the shell sees anything, so that expansion is done here first:
`$(VAR)` from the simple assignments at the top of the file, `$$` to a single `$` for the shell.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tests.conftest import REPO_ROOT

MAKEFILE = REPO_ROOT / "Makefile"

#: `NAME := value` and `NAME ?= value`, the two assignment forms this Makefile uses. Recursive `=`
#: would need a real expander; a test asserts none appears, so this stays a substitution rather than
#: an interpreter. A `?=` default is substituted as written, which is what a run with no environment
#: override would see, and is the case worth checking.
ASSIGNMENT = re.compile(r"^(?P<name>[A-Z_][A-Z0-9_]*)\s*[:?]=\s*(?P<value>.*)$", re.MULTILINE)

#: A target line: a name, a colon, and optional prerequisites. Excludes `.PHONY` and pattern rules.
TARGET = re.compile(r"^(?P<name>[a-z][a-z0-9-]*):(?!=)")

#: Prefixes make strips before handing a line to the shell: `@` silences, `-` ignores failure.
RECIPE_PREFIX = re.compile(r"^[@-]+")

SH_TIMEOUT_SECONDS = 30

requires_sh = pytest.mark.skipif(
    shutil.which("sh") is None, reason="no POSIX shell on this machine"
)


def assignments() -> dict[str, str]:
    return {
        match.group("name"): match.group("value").strip()
        for match in ASSIGNMENT.finditer(MAKEFILE.read_text(encoding="utf-8"))
    }


def expand(text: str, variables: dict[str, str]) -> str:
    """Make's expansion, to the extent these recipes use it.

    Two passes, because `COMPOSE_QS` is defined in terms of nothing but literals today and a future
    variable built from another would otherwise reach the shell as `$(...)`. Anything still
    unexpanded after that is replaced with a harmless word: an unexpanded `$(` is a syntax error in
    `sh` and would be reported as a quoting fault in a recipe that has none.
    """
    for _ in range(2):
        for name, value in variables.items():
            text = text.replace(f"$({name})", value)
    text = re.sub(r"(?<!\$)\$\([A-Z_][A-Z0-9_]*\)", "UNEXPANDED", text)
    return text.replace("$$", "$")


def recipes() -> dict[str, str]:
    """Each target's recipe, joined as make would hand it to one shell per logical line."""
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            if current is not None:
                found[current].append(RECIPE_PREFIX.sub("", line[1:]))
            continue
        match = TARGET.match(line)
        current = match.group("name") if match else None
        if current is not None:
            found.setdefault(current, [])
    variables = assignments()
    return {name: expand("\n".join(body), variables) for name, body in found.items() if body}


def test_the_makefile_uses_only_simple_assignment() -> None:
    """`expand` above is a substitution, not an expander, and recursive `=` would outrun it.

    Asserted rather than assumed, because the failure would be silent: a recursively assigned
    variable reaches the shell as the literal `$(NAME)`, the placeholder rule swallows it, and the
    recipe passes this file's checks while being unrunnable.
    """
    recursive = [
        line
        for line in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if re.match(r"^[A-Z_][A-Z0-9_]*\s*=[^=]", line)
    ]
    assert not recursive, f"recursively assigned variables this test cannot expand: {recursive}"


def test_every_target_has_a_recipe_or_prerequisites() -> None:
    """A target with neither is a name that silently does nothing when asked for."""
    text = MAKEFILE.read_text(encoding="utf-8")
    bodied = set(recipes())
    for match in TARGET.finditer(text):
        name = match.group("name")
        line = text[match.start() : text.index("\n", match.start())]
        prerequisites = line.split(":", 1)[1].split()
        assert name in bodied or prerequisites, f"target {name} has no recipe and no prerequisites"


@requires_sh
@pytest.mark.parametrize("target", sorted(recipes()))
def test_each_recipe_parses_as_posix_shell(target: str) -> None:
    """`sh -n` reads and does not run: nothing here starts a container or writes a file."""
    body = recipes()[target]
    result = subprocess.run(
        ["sh", "-n"],  # noqa: S607
        input=body,
        capture_output=True,
        text=True,
        timeout=SH_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, (
        f"make {target} is not valid shell:\n{result.stderr.strip()}\n--- recipe ---\n{body}"
    )


@requires_sh
def test_the_check_would_catch_a_broken_recipe() -> None:
    """A parser that accepts everything passes every recipe, including the ones it should reject.

    So the check is shown failing on a fault of the shape this file exists to catch -- a `for` with
    no `done`, which is exactly what a mistyped line continuation in the sbom target would produce.
    """
    result = subprocess.run(
        ["sh", "-n"],  # noqa: S607
        input='for image in a b; do echo "$image";\n',
        capture_output=True,
        text=True,
        timeout=SH_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode != 0, "sh -n accepted an unterminated for loop, so it proves nothing"
