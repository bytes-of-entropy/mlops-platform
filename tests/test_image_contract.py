"""The built image's hardening properties, asserted by reading the Dockerfile.

Three of M1's four hardening items need a daemon and a registry. One needs only a text file, and
that one is checkable everywhere: which user the image ends as, whether any base names a moving tag,
whether the pip installs pin, and whether a wheel cache is left in a layer. Record 017 argues each.

The reason to read rather than to run is the same reason Repo 1 asserts its dependency direction by
parsing an AST: a property checked only by the machine that has Docker is unchecked on every machine
that does not, and this suite is designed so the contract tier runs anywhere.

**Digests are deliberately absent from this file.** A digest cannot be resolved without a registry,
and a test accepting a bare tag in their place would pass without looking. Record 017 says where
they land and what lands with them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

IMAGES = Path(__file__).resolve().parent.parent / "images"

#: Anything that would leave the container running as uid 0.
ROOT_USERS = frozenset({"root", "0"})

#: `pip install` lines must pin. A package named with no `==` is a floating dependency inside an
#: artifact whose entire claim is that it is reproducible.
PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+-]*$")


def dockerfiles() -> list[Path]:
    """Every Dockerfile under images/, found by walking rather than by listing."""
    return sorted(IMAGES.rglob("Dockerfile"))


def instructions(path: Path) -> list[tuple[str, str, int]]:
    """(directive, argument, line) per instruction, with continuations joined and comments dropped.

    Joining continuations is the part worth doing carefully: a `RUN` split over four lines with
    backslashes is one instruction, and a checker reading it as four would miss lines two to four,
    which is where anything interesting tends to be.
    """
    joined: list[tuple[str, str, int]] = []
    pending = ""
    start = 0
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not pending:
            start = number
        pending += line[:-1].rstrip() + " " if line.endswith("\\") else line
        if line.endswith("\\"):
            continue
        directive, _, argument = pending.partition(" ")
        joined.append((directive.upper(), argument.strip(), start))
        pending = ""
    return joined


def test_there_are_dockerfiles_to_check() -> None:
    """Guards against a vacuous suite: every test below passes on an empty list."""
    assert dockerfiles(), "no Dockerfile found under images/, so every check here proves nothing"


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_the_image_ends_as_a_non_root_user(path: Path) -> None:
    """The last USER wins, so the last one is the one that matters.

    A Dockerfile that switches to root for an install and never switches back runs as root, and it
    reads as though it does not.
    """
    users = [argument for directive, argument, _ in instructions(path) if directive == "USER"]
    assert users, (
        f"{path.parent.name} declares no USER, so it runs as whatever its base does, which for "
        f"every base here is root"
    )
    final = users[-1].split(":")[0]
    assert final not in ROOT_USERS, f"{path.parent.name} ends as {final!r}"


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_the_user_it_ends_as_is_an_account_the_image_creates(path: Path) -> None:
    """A uid with no passwd entry confuses anything that looks up its own identity."""
    parsed = instructions(path)
    final = [a for directive, a, _ in parsed if directive == "USER"][-1].split(":")[0]
    created = " ".join(a for directive, a, _ in parsed if directive == "RUN")
    assert "useradd" in created and final in created, (
        f"{path.parent.name} ends as {final!r} but never creates it; a bare numeric USER works and "
        f"says what the account happens to be rather than what it is"
    )


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_no_base_image_names_a_moving_tag(path: Path) -> None:
    """`latest` is not a version, and an image built from it is not the image that was tested."""
    bases = [argument for directive, argument, _ in instructions(path) if directive == "FROM"]
    assert bases, f"{path.parent.name} has no FROM"
    moving = [base for base in bases if base.split(" ")[0].endswith(":latest") or ":" not in base]
    assert not moving, f"{path.parent.name} builds from {moving}, which can change under it"


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_every_pip_install_pins_every_package(path: Path) -> None:
    """An unpinned package in an artifact claiming reproducibility is that claim being false."""
    unpinned: list[str] = []
    for directive, argument, line in instructions(path):
        if directive != "RUN" or "pip install" not in argument:
            continue
        after = argument.split("pip install", 1)[1]
        for token in after.split():
            if token.startswith("-") or token in {"pip", "&&"}:
                continue
            if not PINNED.match(token):
                unpinned.append(f"{token} (line {line})")
    assert not unpinned, f"{path.parent.name} installs {', '.join(unpinned)} without an == pin"


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_every_pip_install_leaves_no_wheel_cache_behind(path: Path) -> None:
    """A cache in a layer is bytes shipped to every puller for the benefit of nobody."""
    missing = [
        line
        for directive, argument, line in instructions(path)
        if directive == "RUN" and "pip install" in argument and "--no-cache-dir" not in argument
    ]
    assert not missing, f"{path.parent.name} pip installs without --no-cache-dir at line {missing}"


@pytest.mark.parametrize("path", dockerfiles(), ids=lambda p: p.parent.name)
def test_a_copied_script_is_not_writable_by_the_user_that_runs_it(path: Path) -> None:
    """A one-shot that can rewrite itself has more privilege than its job needs."""
    copies = [
        (argument, line)
        for directive, argument, line in instructions(path)
        if directive == "COPY" and ".py" in argument
    ]
    unprotected = [f"line {line}" for argument, line in copies if "--chmod=" not in argument]
    assert not unprotected, (
        f"{path.parent.name} copies a script without a --chmod at {', '.join(unprotected)}; the "
        f"default is writable by its owner"
    )
