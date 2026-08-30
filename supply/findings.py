"""The advisories already known against an image, and whether a scan found a new one.

`--fail-on high` is not a gate this spine can pass and never will be. After record 021 bumped
every base to the newest release in its major line, what remained was 138 Critical and 870 High
findings, overwhelmingly in operating-system packages with no fix available inside the current
major. A threshold on severity therefore fails every run and says the same thing every time,
which is the same as saying nothing.

So the gate is on *identity* rather than on count or severity. The advisories present when
measurement started are committed, per image, one identifier per line, and a scan fails only on
an identifier that is not in that list. Three properties follow, and they are why this shape was
chosen over a count:

* **The alert names what changed.** A rising count tells you a number; a new identifier tells you
  which advisory in which image, and the scan table beside it names the package and the fixed
  version. A gate nobody can act on gets switched off.
* **It cannot hide a swap.** Two findings, one fixed and one new, leave a count unmoved. A set
  notices.
* **It is not an accepted risk.** `security/exceptions.toml` is for a finding somebody read and
  argued for, and record 019 requires a reason and an expiry for each. A line here claims
  something weaker: this advisory was already present when the baseline was taken. That is why it
  needs no prose, and why the two files must not be confused.

The cost is worth stating plainly: a database update that adds an advisory against an unchanged
image fires this gate. That is not a false alarm, since a newly disclosed advisory against an
image you run *is* news, but it does mean the gate moves on somebody else's schedule. Record 019
records the same fact from the other side -- a scan result is a function of the SBOM, the scanner
and the database, and only the first two are pinned here.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

#: The severities the gate covers. Medium and below are reported by the scan and not gated: at
#: 1,483 Medium findings a baseline over everything would be four times the size and would fire
#: constantly on advisories nobody would act on, which is how a gate stops being read.
GATED = ("Critical", "High")

#: An advisory identifier, in any namespace grype reports: CVE, GHSA, GO, ELSA and others. Strict
#: on shape so a malformed line in a committed baseline is caught rather than silently matching
#: nothing -- an entry that matches no finding makes a baseline quietly more permissive.
ADVISORY = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Za-z0-9]+)+$")


class FindingsError(Exception):
    """Not a grype report, or a baseline that is not a list of advisory identifiers."""


def advisories(document: Any, severities: tuple[str, ...] = GATED) -> list[str]:
    """Sorted, deduplicated advisory identifiers at the gated severities.

    Deduplicated because one advisory routinely matches several packages in one image: a Debian
    source package split into a library and a binary yields two rows for one identifier. The
    question here is whether the advisory is known, not how many packages it touched.
    """
    if not isinstance(document, dict):
        raise FindingsError(
            f"expected a grype report object, read a {type(document).__name__}; the scanner "
            f"probably wrote an error to this path instead of a report"
        )
    matches = document.get("matches")
    if matches is None:
        raise FindingsError(
            "the report has no `matches` key, so it is not a grype JSON report; check the "
            "scanner was asked for `-o json` and exited without error"
        )
    if not isinstance(matches, list):
        raise FindingsError(f"`matches` is a {type(matches).__name__}, not a list")

    found: set[str] = set()
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise FindingsError(f"match {index} is a {type(match).__name__}, not an object")
        vulnerability = match.get("vulnerability")
        if not isinstance(vulnerability, dict):
            raise FindingsError(f"match {index} carries no vulnerability object")
        identifier = vulnerability.get("id")
        severity = vulnerability.get("severity")
        if not isinstance(identifier, str) or not identifier:
            raise FindingsError(f"match {index} has no usable vulnerability id: {identifier!r}")
        if not isinstance(severity, str):
            raise FindingsError(f"{identifier}: severity is {severity!r}, not a string")
        if severity in severities:
            found.add(identifier)
    return sorted(found)


def baseline(path: Path) -> set[str]:
    """The advisory identifiers a baseline file names.

    A missing file raises rather than reading as an empty set. Empty would make every advisory
    unknown and fail loudly, which sounds safe and is not: the message would be hundreds of lines
    of "new advisory" rather than "this image has no baseline", and the second is the real problem.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FindingsError(
            f"{path} could not be read: {error}. If this image has never been scanned, "
            f"`make scan-accept` writes the first baseline, which is a deliberate act and lands "
            f"as a reviewable diff."
        ) from error

    found: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not ADVISORY.match(entry):
            raise FindingsError(
                f"{path}:{number}: {entry!r} is not an advisory identifier. An entry that "
                f"matches no finding makes this baseline more permissive than it looks."
            )
        found.add(entry)
    return found


#: Prepended to every generated baseline. Not decoration: this file and
#: `security/exceptions.toml` look alike and mean different things, and the difference matters the
#: first time somebody reaches for one of them.
HEADER = """# Advisories already present against this image when the baseline was taken.
#
# NOT accepted risks. An entry here claims only that the advisory was already there. It carries
# no judgement, needs no reason, and grants no exception. Accepted findings live in
# security/exceptions.toml, need a reason and an expiry, and are reviewed. See record 022.
#
# Generated by `make scan-accept`. Gated severities: {severities}.
"""


def write(path: Path, identifiers: list[str]) -> int:
    """Write a baseline: header, then one sorted identifier per line, LF-terminated."""
    header = HEADER.format(severities=", ".join(GATED))
    path.write_text(header + "\n".join(identifiers) + "\n", encoding="utf-8", newline="\n")
    return len(identifiers)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    accept = "--accept" in arguments
    positional = [item for item in arguments if item != "--accept"]
    if len(positional) != 2:
        print(
            "usage: -m supply.findings [--accept] <baseline.known.txt> <report.findings.json>",
            file=sys.stderr,
        )
        return 2

    known_path, report_path = Path(positional[0]), Path(positional[1])
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        current = advisories(report)
    except (FindingsError, json.JSONDecodeError, OSError) as error:
        print(f"{report_path}: {error}", file=sys.stderr)
        return 1

    if accept:
        count = write(known_path, current)
        print(f"{known_path}: {count} advisories written as the baseline")
        return 0

    try:
        known = baseline(known_path)
    except FindingsError as error:
        print(f"{error}", file=sys.stderr)
        return 1

    unknown = sorted(set(current) - known)
    gone = sorted(known - set(current))

    if gone:
        # Information, never a failure. A disappeared advisory is good news, and the next
        # `scan-accept` records it as a diff; failing here would make good news cost a commit.
        shown = ", ".join(gone[:8]) + (" ..." if len(gone) > 8 else "")
        print(f"{known_path}: {len(gone)} baselined, no longer found: {shown}")

    if unknown:
        print(
            f"{known_path}: {len(unknown)} advisories above the gate are not baselined:",
            file=sys.stderr,
        )
        for identifier in unknown:
            print(f"  {identifier}", file=sys.stderr)
        print(
            "  The scan table above names the package and the fixed version for each. Fix them, "
            "or accept them deliberately with `make scan-accept` and let the diff be reviewed.",
            file=sys.stderr,
        )
        return 1

    print(f"{known_path}: {len(current)} advisories, all baselined")
    return 0


if __name__ == "__main__":
    sys.exit(main())
