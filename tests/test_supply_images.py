"""The list the cataloguer walks, and the guarantee that it is the whole list.

This is the assertion the SBOM rests on. Everything downstream -- the committed inventory, the
scan, any accepted finding -- describes the images that appear here, and an image missing from this
list is absent from all of it without anything going red. That failure has a precedent in this
repository: `docker compose config --images` reported the default profile only and left
`apache/airflow` out, which is why the list is read from the `image` keys instead.

So the test that matters is not that the function returns something plausible. It is that what it
returns and what `tests/test_image_supply.py` independently reads out of the same file are the same
set, checked here so the two readers cannot drift apart quietly.

That set is every `image` key *and* the `FROM` of everything the spine builds. The base was missing
from the first version of this list, which is the same short-list defect one level down, and the one
that made record 019's third prediction unscorable: the inventory of the image built here cannot be
diffed against a base nobody catalogued.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from supply.images import COMPOSE_FILE, ComposeError, references
from tests.test_image_supply import BUILT_BASES, SERVICES


def test_the_reference_list_is_every_image_key_and_every_base() -> None:
    """The other reader of this file is the pinning suite; the two have to agree exactly.

    Compared as sets against comprehensions written here rather than against a literal list, which
    would be a third copy needing its own maintenance and would go stale on the first version bump.

    Bases are in the list, and were not in the first version of it. A base is not needed for the
    scan, since the built image contains it and scanning one covers both. What it buys is the diff:
    without it, the two packages this repository installs are two lines somewhere in 177 and
    nothing says which two.
    """
    expected = {service["image"] for service in SERVICES.values()} | set(BUILT_BASES)
    assert set(references()) == expected


def test_the_base_of_the_built_image_is_in_the_list() -> None:
    """Asserted on its own, because it is the omission the set comparison above would inherit.

    If `built_bases()` ever came back empty, the comparison would still pass -- both sides would be
    short by the same amount. This one fails.
    """
    assert BUILT_BASES, "no service builds, so this assertion proves nothing"
    missing = [base for base in BUILT_BASES if base not in references()]
    assert not missing, f"bases the cataloguer would never walk: {missing}"


def test_no_service_is_left_out_however_it_is_profiled() -> None:
    """The documented failure, asserted directly rather than trusted to the set comparison above."""
    profiled = {
        name: service["image"]
        for name, service in SERVICES.items()
        if service.get("profiles") is not None
    }
    assert profiled, "no service in this compose file is profiled, so this test proves nothing"
    listed = set(references())
    missing = {name: image for name, image in profiled.items() if image not in listed}
    assert not missing, f"profiled services absent from the cataloguer's list: {missing}"


def test_the_list_is_sorted_and_carries_no_duplicates() -> None:
    """Three Spark services name one image; cataloguing the largest image twice buys nothing."""
    listed = references()
    assert listed == sorted(listed)
    assert len(listed) == len(set(listed))


def test_the_built_image_is_catalogued_too() -> None:
    """It is the one image in the spine this repository is responsible for.

    Its absence would be the easiest omission to rationalise -- no registry has heard of it -- and
    the least defensible, since it is the only one whose contents are a decision made here.
    """
    assert any(reference.startswith("mlops-platform/") for reference in references())


def _write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "docker-compose.yml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param(["services"], "does not parse to a mapping", id="a-list"),
        pytest.param({"version": "3"}, "declares no services", id="no-services"),
        pytest.param({"services": {}}, "declares no services", id="empty-services"),
        pytest.param({"services": {"a": None}}, "is not a mapping", id="service-is-null"),
        pytest.param({"services": {"a": {"build": "."}}}, "names no image", id="build-only"),
        pytest.param({"services": {"a": {"image": " "}}}, "non-string image", id="blank-image"),
        pytest.param({"services": {"a": {"image": 3}}}, "non-string image", id="numeric-image"),
    ],
)
def test_a_compose_file_it_cannot_account_for_is_refused(
    tmp_path: Path, document: object, expected: str
) -> None:
    """Refused, not partially read.

    A build-only service is the interesting case: compose accepts it, it produces an unnamed local
    image, and returning the rest of the list would be a silently short answer -- the exact shape of
    the failure this module exists to prevent.
    """
    with pytest.raises(ComposeError, match=expected):
        references(_write(tmp_path, document))


def test_the_module_points_at_the_repository_compose_file() -> None:
    """A default argument resolved from `__file__` breaks quietly if the package is moved."""
    assert COMPOSE_FILE.is_file(), f"{COMPOSE_FILE} does not exist"
