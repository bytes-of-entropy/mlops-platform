"""The reduction from SPDX document to committed inventory.

`tests/test_security_exceptions.py` checks the shape of an inventory that exists. This checks the
thing that produces it, which matters because the producer needs a container runtime and the
inventory it writes is reviewed by people who will not have run it. So the reduction is tested
against documents written here rather than against a real cataloguer's output: what is being
asserted is the contract this repository depends on, not what syft happens to emit today.

Every failure mode raises. That is the decision under test as much as the happy path is -- an
empty inventory committed in place of a failed catalogue would read as an image containing no
packages, which is a stronger and more wrong claim than a missing file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supply.inventory import NO_VERSION, InventoryError, inventory, main, write


def document(*packages: dict[str, object]) -> dict[str, object]:
    """An SPDX-shaped document carrying only the two fields the reduction reads."""
    return {"spdxVersion": "SPDX-2.3", "packages": list(packages)}


def test_a_document_reduces_to_name_and_version_lines() -> None:
    result = inventory(document({"name": "zlib", "versionInfo": "1.3.1"}))
    assert result == ["zlib==1.3.1"]


def test_the_output_is_sorted_regardless_of_document_order() -> None:
    """The cataloguer's ordering is not part of its contract, and readable diffs need ours fixed."""
    result = inventory(
        document(
            {"name": "zlib", "versionInfo": "1.3.1"},
            {"name": "apt", "versionInfo": "2.6.1"},
            {"name": "musl", "versionInfo": "1.2.5"},
        )
    )
    assert result == ["apt==2.6.1", "musl==1.2.5", "zlib==1.3.1"]


def test_one_package_catalogued_twice_appears_once() -> None:
    """A package found at two paths is one package; listing it twice makes the count meaningless."""
    result = inventory(
        document(
            {"name": "zlib", "versionInfo": "1.3.1"},
            {"name": "zlib", "versionInfo": "1.3.1"},
        )
    )
    assert result == ["zlib==1.3.1"]


def test_two_versions_of_one_package_both_appear() -> None:
    """Not the same case as above, and collapsing it would hide the more interesting one."""
    result = inventory(
        document(
            {"name": "openssl", "versionInfo": "3.0.13"},
            {"name": "openssl", "versionInfo": "1.1.1w"},
        )
    )
    assert result == ["openssl==1.1.1w", "openssl==3.0.13"]


@pytest.mark.parametrize("version", [None, "", 3, {"major": 1}])
def test_an_unusable_version_is_carried_rather_than_dropped(version: object) -> None:
    """A package whose version could not be established is still in the image.

    Dropping it would make the inventory quietly incomplete, which is the one thing it cannot be:
    the reviewer has no second copy to compare against and no way to notice the omission.
    """
    result = inventory(document({"name": "vendored-thing", "versionInfo": version}))
    assert result == [f"vendored-thing=={NO_VERSION}"]


def test_a_missing_version_key_is_carried_too() -> None:
    assert inventory(document({"name": "vendored-thing"})) == [f"vendored-thing=={NO_VERSION}"]


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        pytest.param([], "SPDX document object", id="a-list"),
        pytest.param("error: no such image", "SPDX document object", id="an-error-string"),
        pytest.param({"spdxVersion": "SPDX-2.3"}, "no `packages` key", id="no-packages-key"),
        pytest.param({"packages": []}, "lists no packages", id="empty-packages"),
        pytest.param({"packages": "zlib"}, "lists no packages", id="packages-not-a-list"),
    ],
)
def test_a_document_that_is_not_a_package_list_is_refused(bad: object, expected: str) -> None:
    with pytest.raises(InventoryError, match=expected):
        inventory(bad)


@pytest.mark.parametrize("name", [None, "", 42])
def test_a_package_with_no_usable_name_is_refused(name: object) -> None:
    """There is nothing to write and nothing to review, so this cannot be papered over."""
    with pytest.raises(InventoryError, match="no usable `name`"):
        inventory(document({"name": name, "versionInfo": "1.0"}))


def test_a_package_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(InventoryError, match="not an object"):
        inventory(document("zlib"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "package",
    [
        {"name": "od==d", "versionInfo": "1.0"},
        {"name": "odd", "versionInfo": "1==0"},
    ],
)
def test_a_field_carrying_the_separator_is_refused(package: dict[str, object]) -> None:
    """Written out, its line could not be split back apart.

    Refused here, where the offending package can be named, rather than left to the committed-shape
    check, which can only report that some line has the wrong number of separators in it.
    """
    with pytest.raises(InventoryError, match="could not be"):
        inventory(document(package))


def test_write_produces_lf_terminated_text_and_reports_the_count(tmp_path: Path) -> None:
    """LF specifically: the file is committed, and a CRLF copy makes the tree look rewritten."""
    source = tmp_path / "image.spdx.json"
    source.write_text(
        json.dumps(document({"name": "zlib", "versionInfo": "1.3.1"}, {"name": "apt"})),
        encoding="utf-8",
    )
    destination = tmp_path / "image.packages.txt"

    assert write(source, destination) == 2
    raw = destination.read_bytes()
    assert raw == f"apt=={NO_VERSION}\nzlib==1.3.1\n".encode()


def test_the_entrypoint_reports_a_bad_document_without_writing_one(tmp_path: Path) -> None:
    """Exit nonzero and leave nothing behind: a truncated inventory is worse than none."""
    source = tmp_path / "image.spdx.json"
    source.write_text('{"packages": []}', encoding="utf-8")
    destination = tmp_path / "image.packages.txt"

    assert main([str(source), str(destination)]) == 1
    assert not destination.exists()


def test_the_entrypoint_reports_a_missing_document(tmp_path: Path) -> None:
    assert main([str(tmp_path / "absent.spdx.json"), str(tmp_path / "out.txt")]) == 1


def test_the_entrypoint_refuses_the_wrong_number_of_arguments() -> None:
    """2, not 1: the destination is explicit so the runner decides where committed files land."""
    assert main([]) == 2
    assert main(["only-a-source.spdx.json"]) == 2
