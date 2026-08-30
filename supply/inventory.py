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


class InventoryError(Exception):
    """The input is not an SPDX package list this can reduce.

    Raised rather than recovered from. An empty or unreadable document here means the cataloguer
    failed, and an empty inventory committed in its place would read as an image containing no
    packages, which is a stronger and more wrong claim than a missing file.
    """


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
    lines: set[str] = set()
    for index, entry in enumerate(_entries(document)):
        if not isinstance(entry, dict):
            raise InventoryError(f"package {index} is a {type(entry).__name__}, not an object")
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
    print(f"{destination}: {count} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
