"""Every image reference the spine names, for the cataloguer to walk.

Read out of the compose file rather than asked of `docker compose config --images`, which is the
obvious tool and is the wrong one here: it reports the services of the profiles it was given, and
it has already silently omitted `apache/airflow` from this repository's list once. A cataloguer fed
a short list produces an inventory that is short in exactly the same way, and an inventory nobody
can tell is incomplete is worse than no inventory, because it reads as a clean bill of health.

So the list comes from the `image` keys themselves, which is exhaustive by construction: a service
that names an image is in, whatever profile it belongs to and whether a daemon is running or not.
The cost is a second reader of the compose file beside the one in `tests/test_image_supply.py`, and
`tests/test_supply_images.py` pins the two together so neither can drift alone.

**And the `FROM` of everything this spine builds**, which the first version of this module left out
-- the same short-list defect it was written to avoid, one level down. The base is not a substitute
for the image built from it: the built image contains the base's packages, so a vulnerability scan
of one covers both. What the base buys is the diff. The whole argument for committing an inventory
is that a rebuild produces a readable one, and `mlflow`'s inventory is only readable against its
base's -- otherwise the two packages this repository installs are 2 lines somewhere in 177, and
nothing says which 2. Record 018 sorts references the same way and for a related reason: what a
registry answers for is the base, because that is the level the pin lives at.

The one image built here has to exist locally before it can be catalogued, so `build` comes first.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The compose file that defines the spine. The quickstart overlay changes resource limits and the
#: set of services started, not the images any of them run, so reading the base file is exhaustive.
COMPOSE_FILE = REPO_ROOT / "compose" / "docker-compose.yml"


class ComposeError(Exception):
    """The compose file is not the shape this can read image references out of."""


def _services(compose_file: Path) -> dict[str, Any]:
    loaded: Any = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ComposeError(f"{compose_file} does not parse to a mapping")
    services = loaded.get("services")
    if not isinstance(services, dict) or not services:
        raise ComposeError(f"{compose_file} declares no services")
    return dict(services)


def _context(service: dict[str, Any]) -> str | None:
    """The build context, or None for a service whose image is pulled rather than built."""
    build = service.get("build")
    if build is None:
        return None
    if isinstance(build, str):
        return build
    if isinstance(build, dict) and isinstance(build.get("context"), str):
        return str(build["context"])
    raise ComposeError(f"a build section names no usable context: {build!r}")


def _bases(root: Path, context: str) -> set[str]:
    dockerfile = root / context / "Dockerfile"
    try:
        text = dockerfile.read_text(encoding="utf-8")
    except OSError as error:
        raise ComposeError(f"{dockerfile} could not be read: {error}") from error
    found = {
        line.split()[1]
        for line in text.splitlines()
        if line.startswith("FROM ") and len(line.split()) > 1
    }
    if not found:
        raise ComposeError(f"{dockerfile} declares no FROM, so its base cannot be catalogued")
    return found


def references(compose_file: Path = COMPOSE_FILE) -> list[str]:
    """Sorted, deduplicated `image` values across every service, plus the `FROM` of each build.

    Deduplicated because three Spark services name one image, and cataloguing the largest image in
    the spine three times reads the same bytes twice for nothing.
    """
    root = compose_file.resolve().parent.parent
    found: set[str] = set()
    for name, service in _services(compose_file).items():
        if not isinstance(service, dict):
            raise ComposeError(f"service {name!r} is not a mapping")
        image = service.get("image")
        if image is None:
            # A service with a build and no image key is possible in compose and absent here; it
            # would produce an unnamed local image, so it is reported rather than skipped.
            raise ComposeError(
                f"service {name!r} names no image, so there is nothing to catalogue for it"
            )
        if not isinstance(image, str) or not image.strip():
            raise ComposeError(f"service {name!r} has a non-string image: {image!r}")
        found.add(image.strip())
        context = _context(service)
        if context is not None:
            found |= _bases(root, context)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print("usage: -m supply.images", file=sys.stderr)
        return 2
    try:
        for reference in references():
            print(reference)
    except (ComposeError, OSError, yaml.YAMLError) as error:
        print(f"{COMPOSE_FILE}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
