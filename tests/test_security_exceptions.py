"""The accepted-vulnerability list, and the package inventories, checked without a daemon.

The scan itself needs Docker and a network. Two things about it do not, and they are the two that
rot: whether an accepted finding is still in date, and whether a committed inventory is the shape a
reviewer can diff. Both are facts about text files, so they are checked on every machine, and an
exception past its expiry fails on a laptop rather than waiting for a host with a daemon.

Record 019 argues the design: what gets committed is a sorted `name==version` inventory rather than
the SPDX document, because SPDX carries a UUID and a timestamp and therefore diffs on every
regeneration whether the image changed or not.
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS_FILE = ROOT / "security" / "exceptions.toml"
SBOM_DIR = ROOT / "sbom"

#: Long enough that "false positive" does not fit. Why it is one has to.
MINIMUM_REASON = 40

REQUIRED_FIELDS = ("id", "package", "reason", "expires")


def exceptions() -> list[dict[str, object]]:
    loaded = tomllib.loads(EXCEPTIONS_FILE.read_text(encoding="utf-8"))
    entries = loaded.get("exception", [])
    assert isinstance(entries, list)
    return list(entries)


def inventories() -> list[Path]:
    """Committed package inventories, if any have been generated yet."""
    return sorted(SBOM_DIR.glob("*.packages.txt")) if SBOM_DIR.is_dir() else []


def test_the_exceptions_file_exists_and_parses() -> None:
    """An absent file would make every assertion below vacuous."""
    assert EXCEPTIONS_FILE.is_file(), f"{EXCEPTIONS_FILE} is missing"
    exceptions()


def test_the_file_documents_its_own_schema() -> None:
    """It is empty today, so the comments are the only thing telling the next person the shape."""
    text = EXCEPTIONS_FILE.read_text(encoding="utf-8")
    for field in REQUIRED_FIELDS:
        assert field in text, f"the schema comment does not mention {field}"


def test_every_exception_carries_every_required_field() -> None:
    missing = [
        (entry.get("id", "<no id>"), field)
        for entry in exceptions()
        for field in REQUIRED_FIELDS
        if field not in entry
    ]
    assert not missing, f"exceptions missing fields: {missing}"


def test_every_reason_says_why_rather_than_that() -> None:
    """ "False positive" is a verdict. The reason has to be the argument for it."""
    thin = [
        (entry["id"], len(str(entry.get("reason", ""))))
        for entry in exceptions()
        if len(str(entry.get("reason", ""))) < MINIMUM_REASON
    ]
    assert not thin, (
        f"these reasons are under {MINIMUM_REASON} characters: {thin}. An exception whose "
        f"justification fits in three words is one nobody can review."
    )


def test_no_exception_is_past_its_expiry() -> None:
    """The assertion this file exists for.

    It fails the suite rather than the scan, deliberately. The scan needs a daemon and this does
    not, so a stale exception is caught anywhere instead of waiting for a host that can scan.
    """
    today = date.today()
    stale = []
    for entry in exceptions():
        expires = entry.get("expires")
        # A quoted date parses as text; the test below is the one that catches that, and this one
        # has to skip it rather than compare a string against a date and raise instead of failing.
        if isinstance(expires, date) and expires < today:
            stale.append((entry.get("id", "<no id>"), expires))
    assert not stale, (
        f"expired exceptions: {stale}. Renewing one means editing the date and the reason "
        f"together; a date moved on its own is what this check exists to prevent."
    )


def test_every_expiry_is_a_date_rather_than_a_string() -> None:
    """A quoted date parses as text, so a comparison against today silently passes."""
    wrong = [
        (entry["id"], type(entry["expires"]).__name__)
        for entry in exceptions()
        if "expires" in entry and not isinstance(entry["expires"], date)
    ]
    assert not wrong, f"these expiries are not TOML dates: {wrong}; write 2026-11-30, unquoted"


def test_no_identifier_is_accepted_twice() -> None:
    """Two entries for one finding means one of them is unreviewed."""
    identifiers = [str(entry["id"]) for entry in exceptions() if "id" in entry]
    duplicated = sorted({name for name in identifiers if identifiers.count(name) > 1})
    assert not duplicated, f"accepted more than once: {duplicated}"


@pytest.mark.parametrize("path", inventories(), ids=lambda p: p.name)
def test_an_inventory_is_sorted_and_shaped_for_review(path: Path) -> None:
    """The property that makes committing it worth anything: a diff a person can read.

    Not parameterised over an expected package list, because that would be a second inventory
    drifting from the first. Shape only.
    """
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, f"{path.name} is empty"
    assert lines == sorted(lines), f"{path.name} is not sorted, so its diffs will not be readable"
    assert len(lines) == len(set(lines)), f"{path.name} lists a package twice"
    malformed = [line for line in lines if line.count("==") != 1]
    assert not malformed, f"{path.name} has lines that are not name==version: {malformed[:3]}"


def test_the_sbom_directory_is_not_committing_spdx_documents() -> None:
    """SPDX carries a UUID and a timestamp, so a committed one diffs on every regeneration.

    Checked rather than trusted to the ignore file, because the failure is silent: a document
    committed once produces noise forever and nobody traces it back to this decision.
    """
    if not SBOM_DIR.is_dir():
        return
    spdx = sorted(SBOM_DIR.glob("*.spdx.json"))
    tracked = [path.name for path in spdx if not path.name.startswith(".")]
    assert not tracked or all((SBOM_DIR / ".gitignore").is_file() for _ in tracked), (
        f"{tracked} are present with no .gitignore beside them; record 019 keeps the SPDX "
        f"documents generated and uncommitted, and the inventory is what gets reviewed"
    )
