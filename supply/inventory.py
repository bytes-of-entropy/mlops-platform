"""Reduce an SPDX document to the sorted `name==version` inventory committed beside it.

The SPDX document is the machine-readable artefact: it is what the scanner reads, and it is not
committed, because it carries a document UUID and a creation timestamp and therefore produces a
diff on every regeneration whether the image changed or not. The inventory is the reviewable one --
sorted, deduplicated, one package per line -- so a rebuild that changed nothing produces no diff
and a rebuild that pulled a new libc produces exactly one. Record 019 argues the trade.

Reducing rather than reformatting: this drops the document's structure and keeps its claims. That
makes the output a lossy view, which is the point, and is why the SPDX document is generated at the
same time rather than replaced by this.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: What SPDX writes when a package's version could not be established. Carried into the inventory
#: rather than dropped: an unversioned package is still a package present in the image, and the one
#: thing an inventory must never do is omit something quietly. A reviewer seeing `zlib==NOASSERTION`
#: knows the cataloguer could not name a version; a reviewer seeing nothing learns nothing.
NO_VERSION = "NOASSERTION"

#: Separates name from version. A package carrying it in either field would produce a line that
#: cannot be split back apart, so such a package is refused rather than written.
SEPARATOR = "=="

#: The SPDX relationship that names what a document is about. Syft emits the image itself as a
#: package and points this at it, so `mlops-platform/mlflow==2.13.0` appeared inside
#: `mlops-platform/mlflow`'s own inventory and `ghcr.io/mlflow/mlflow==v2.13.0` inside its base's.
#: Left in, the two show up in a diff of one against the other as a spurious added line and a
#: spurious removed line, which is precisely the noise a reviewable inventory exists to not have --
#: and worse, an image tag bump would produce that pair every time while changing no package.
DESCRIBES = "DESCRIBES"


class InventoryError(Exception):
    """The input is not an SPDX package list this can reduce.

    Raised rather than recovered from. An empty or unreadable document here means the cataloguer
    failed, and an empty inventory committed in its place would read as an image containing no
    packages, which is a stronger and more wrong claim than a missing file.
    """


def _described(document: dict[str, Any]) -> set[str]:
    """The SPDX identifiers of what this document is *about*, rather than what is in it.

    Read from the document's own structure rather than by matching names against the image being
    catalogued. A name match would be a guess that happens to work, and would silently drop a real
    package one day if a package were ever named after the image. Both spellings are honoured
    because SPDX 2.x allows either, and an absent one is not an error: a document that declares
    nothing about its subject simply has no entry to remove.
    """
    found: set[str] = set()
    describes = document.get("documentDescribes")
    if isinstance(describes, list):
        found |= {item for item in describes if isinstance(item, str)}
    relationships = document.get("relationships")
    if isinstance(relationships, list):
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            if relationship.get("relationshipType") != DESCRIBES:
                continue
            related = relationship.get("relatedSpdxElement")
            if isinstance(related, str):
                found.add(related)
    return found


def _entries(document: Any) -> list[Any]:
    if not isinstance(document, dict):
        raise InventoryError(
            f"expected an SPDX document object, read a {type(document).__name__}; the cataloguer "
            f"probably wrote an error to this path instead of a document"
        )
    packages = document.get("packages")
    if packages is None:
        raise InventoryError(
            "the document has no `packages` key, so it is not an SPDX package list; check the "
            "cataloguer was asked for spdx-json and that it exited zero"
        )
    if not isinstance(packages, list) or not packages:
        raise InventoryError(
            "the document lists no packages; an image with nothing in it is not a result worth "
            "committing, so this fails rather than writing an empty inventory"
        )
    return packages


def inventory(document: Any) -> list[str]:
    """The sorted, deduplicated `name==version` lines for one SPDX document.

    Sorted here rather than left to the cataloguer, whose ordering is not part of its contract: an
    inventory whose line order can change between runs produces diffs that say nothing, which is
    the failure this file exists to prevent.
    """
    entries = _entries(document)
    described = _described(document) if isinstance(document, dict) else set()
    lines: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InventoryError(f"package {index} is a {type(entry).__name__}, not an object")
        if entry.get("SPDXID") in described:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise InventoryError(f"package {index} has no usable `name`: {entry.get('name')!r}")
        version = entry.get("versionInfo")
        if not isinstance(version, str) or not version:
            version = NO_VERSION
        if SEPARATOR in name or SEPARATOR in version:
            raise InventoryError(
                f"package {index} carries {SEPARATOR!r} in a field, so its line could not be "
                f"split back apart: name={name!r} version={version!r}"
            )
        lines.add(f"{name}{SEPARATOR}{version}")
    if not lines:
        raise InventoryError(
            "every package in the document is the document's own subject, which cannot be right: "
            "an image containing nothing is not a result worth committing"
        )
    return sorted(lines)


def write(source: Path, destination: Path) -> int:
    """Reduce `source` to `destination`, returning the number of lines written.

    Newlines are forced to LF and the encoding is explicit. This file is committed, so a runner
    that wrote CRLF on one machine would make the whole inventory look rewritten on the next, and
    the readable diff the format exists for would be the first thing lost.
    """
    document = json.loads(source.read_text(encoding="utf-8"))
    lines = inventory(document)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(lines)


def subject_count(source: Path) -> int:
    """How many entries `write` dropped as the document's own subject.

    Reported by the runner rather than asserted, because the number is the evidence: one per image
    means the structural read above found what it expected to, and zero means the cataloguer does
    not describe its subject the way this assumes and nothing was removed. Either way the inventory
    is correct; only the diff noise differs.
    """
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return 0
    described = _described(document)
    packages = document.get("packages")
    if not isinstance(packages, list):
        return 0
    return sum(
        1 for entry in packages if isinstance(entry, dict) and entry.get("SPDXID") in described
    )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print(
            "usage: -m supply.inventory <document.spdx.json> <inventory.packages.txt>",
            file=sys.stderr,
        )
        return 2
    source, destination = Path(arguments[0]), Path(arguments[1])
    try:
        count = write(source, destination)
    except (InventoryError, json.JSONDecodeError, OSError) as error:
        print(f"{source}: {error}", file=sys.stderr)
        return 1
    dropped = subject_count(source)
    suffix = f", {dropped} document subject entr{'y' if dropped == 1 else 'ies'} dropped"
    print(f"{destination}: {count} packages{suffix if dropped else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
