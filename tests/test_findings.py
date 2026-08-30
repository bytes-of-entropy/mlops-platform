"""The advisory baseline: what a scan reports, what is already known, and what fails the gate.

Pure text and pure sets, so all of it runs on a laptop. That matters more here than in most of this
suite: the gate this implements only ever runs where a container runtime and a vulnerability
database are, which is one machine, and a gate whose logic is only exercised in the place it is
hardest to debug is a gate nobody will trust when it fires.

The cases worth being deliberate about are the asymmetric ones. An advisory that appears must fail;
an advisory that disappears must not. A baseline that is missing must be distinguishable from a
baseline that is empty. Both are decisions record 022 argues, and both are easy to get backwards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supply.findings import (
    GATED,
    FindingsError,
    advisories,
    baseline,
    main,
    write,
)


def report(*findings: tuple[str, str]) -> dict[str, object]:
    """A grype-shaped report carrying only the two fields the gate reads."""
    return {
        "matches": [
            {
                "vulnerability": {"id": identifier, "severity": severity},
                "artifact": {"name": "somepackage", "version": "1.0"},
            }
            for identifier, severity in findings
        ]
    }


def test_only_the_gated_severities_are_collected() -> None:
    """Medium and below are reported by the scan and deliberately not gated."""
    result = advisories(
        report(
            ("CVE-2024-0001", "Critical"),
            ("CVE-2024-0002", "High"),
            ("CVE-2024-0003", "Medium"),
            ("CVE-2024-0004", "Low"),
            ("CVE-2024-0005", "Negligible"),
            ("CVE-2024-0006", "Unknown"),
        )
    )
    assert result == ["CVE-2024-0001", "CVE-2024-0002"]


def test_one_advisory_matching_several_packages_appears_once() -> None:
    """A Debian source package split into a library and a binary yields two rows for one advisory.

    The gate asks whether the advisory is known, not how many packages it touched, so the count of
    rows is the wrong unit and would make a baseline churn on repackaging.
    """
    result = advisories(
        report(
            ("CVE-2023-50387", "High"),
            ("CVE-2023-50387", "High"),
            ("CVE-2023-50387", "High"),
        )
    )
    assert result == ["CVE-2023-50387"]


def test_the_output_is_sorted() -> None:
    result = advisories(report(("GHSA-zzz-1", "High"), ("CVE-2024-1", "Critical")))
    assert result == sorted(result)


def test_a_report_with_no_findings_is_an_empty_list_rather_than_an_error() -> None:
    """A clean image is a real result. Unlike an empty *inventory*, which cannot be right."""
    assert advisories(report()) == []


@pytest.mark.parametrize(
    ("bad", "expected"),
    [
        pytest.param([], "grype report object", id="a-list"),
        pytest.param("error: no such file", "grype report object", id="an-error-string"),
        pytest.param({"descriptor": {}}, "no `matches` key", id="no-matches"),
        pytest.param({"matches": "CVE-1"}, "not a list", id="matches-not-a-list"),
        pytest.param({"matches": ["CVE-1"]}, "not an object", id="match-not-an-object"),
        pytest.param({"matches": [{}]}, "no vulnerability object", id="no-vulnerability"),
    ],
)
def test_a_report_it_cannot_read_is_refused(bad: object, expected: str) -> None:
    with pytest.raises(FindingsError, match=expected):
        advisories(bad)


def test_a_finding_with_no_identifier_is_refused() -> None:
    """There is nothing to baseline and nothing to compare, so silence would be the wrong answer."""
    with pytest.raises(FindingsError, match="no usable vulnerability id"):
        advisories({"matches": [{"vulnerability": {"severity": "High"}}]})


def test_a_finding_with_a_non_string_severity_is_refused() -> None:
    """Rather than treated as ungated, which would drop a Critical because a field changed type."""
    with pytest.raises(FindingsError, match="severity is"):
        advisories({"matches": [{"vulnerability": {"id": "CVE-1-1", "severity": None}}]})


def test_a_baseline_reads_identifiers_and_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / "image.known.txt"
    path.write_text(
        "# a header\n#\nCVE-2024-6387\n\nGHSA-qccp-gfcp-xxvc\nGO-2026-4341\n",
        encoding="utf-8",
    )
    assert baseline(path) == {"CVE-2024-6387", "GHSA-qccp-gfcp-xxvc", "GO-2026-4341"}


def test_a_missing_baseline_says_so_rather_than_reading_as_empty(tmp_path: Path) -> None:
    """The decision this test exists for, because empty sounds safe and is not.

    An empty set makes every advisory unknown, so the gate fails with hundreds of lines of "new
    advisory" when the actual problem is one line long: this image has no baseline yet.
    """
    with pytest.raises(FindingsError, match="scan-accept"):
        baseline(tmp_path / "absent.known.txt")


@pytest.mark.parametrize("junk", ["not-an-advisory", "cve-2024-1", "1234", "CVE 2024 1", "-CVE-1"])
def test_a_baseline_line_that_is_not_an_identifier_is_refused(tmp_path: Path, junk: str) -> None:
    """An entry matching no finding makes the baseline quietly more permissive than it reads."""
    path = tmp_path / "image.known.txt"
    path.write_text(f"CVE-2024-6387\n{junk}\n", encoding="utf-8")
    with pytest.raises(FindingsError, match="not an advisory identifier"):
        baseline(path)


def test_a_written_baseline_reads_back_as_what_was_written(tmp_path: Path) -> None:
    """Round trip, because `write` adds a header and `baseline` has to skip exactly that."""
    path = tmp_path / "image.known.txt"
    identifiers = ["CVE-2024-6387", "GHSA-qccp-gfcp-xxvc", "GO-2026-4341"]
    assert write(path, identifiers) == 3
    assert baseline(path) == set(identifiers)


def test_a_written_baseline_says_it_is_not_an_exception_list(tmp_path: Path) -> None:
    """The two files look alike and mean different things; the header is where that is stated."""
    path = tmp_path / "image.known.txt"
    write(path, ["CVE-2024-6387"])
    text = path.read_text(encoding="utf-8")
    assert "NOT accepted risks" in text
    assert "security/exceptions.toml" in text
    for severity in GATED:
        assert severity in text


def test_a_written_baseline_uses_lf_and_no_crlf(tmp_path: Path) -> None:
    """It is committed, so a CRLF copy would make the file look rewritten on the next machine."""
    path = tmp_path / "image.known.txt"
    write(path, ["CVE-2024-6387"])
    assert b"\r" not in path.read_bytes()


def written(tmp_path: Path, *findings: tuple[str, str]) -> tuple[Path, Path]:
    known = tmp_path / "image.known.txt"
    report_path = tmp_path / "image.findings.json"
    report_path.write_text(json.dumps(report(*findings)), encoding="utf-8")
    return known, report_path


def test_a_scan_matching_its_baseline_passes(tmp_path: Path) -> None:
    known, report_path = written(tmp_path, ("CVE-1-1", "High"), ("CVE-1-2", "Critical"))
    write(known, ["CVE-1-1", "CVE-1-2"])
    assert main([str(known), str(report_path)]) == 0


def test_a_new_advisory_fails_the_gate(tmp_path: Path) -> None:
    """The whole point. A gate that cannot fail is decoration."""
    known, report_path = written(tmp_path, ("CVE-1-1", "High"), ("CVE-9-9", "Critical"))
    write(known, ["CVE-1-1"])
    assert main([str(known), str(report_path)]) == 1


def test_a_disappeared_advisory_does_not_fail_the_gate(tmp_path: Path) -> None:
    """The asymmetry, and the half that is easy to get backwards.

    A finding that went away is good news. Failing on it would mean a fix costs a commit before the
    build goes green again, which is how a gate teaches people not to fix things.
    """
    known, report_path = written(tmp_path, ("CVE-1-1", "High"))
    write(known, ["CVE-1-1", "CVE-1-2", "CVE-1-3"])
    assert main([str(known), str(report_path)]) == 0


def test_severity_dropping_below_the_gate_does_not_fail(tmp_path: Path) -> None:
    """A rescored advisory is the same case as a disappeared one, and must behave the same."""
    known, report_path = written(tmp_path, ("CVE-1-1", "Medium"))
    write(known, ["CVE-1-1"])
    assert main([str(known), str(report_path)]) == 0


def test_severity_rising_into_the_gate_fails(tmp_path: Path) -> None:
    """The mirror of the case above, and the one a count-based ratchet on Critical+High would miss
    only if the total happened not to move."""
    known, report_path = written(tmp_path, ("CVE-1-1", "High"), ("CVE-2-2", "Critical"))
    write(known, ["CVE-1-1"])
    assert main([str(known), str(report_path)]) == 1


def test_accept_writes_the_baseline_from_the_report(tmp_path: Path) -> None:
    known, report_path = written(tmp_path, ("CVE-1-1", "High"), ("CVE-1-2", "Medium"))
    assert main(["--accept", str(known), str(report_path)]) == 0
    assert baseline(known) == {"CVE-1-1"}


def test_accept_overwrites_rather_than_appends(tmp_path: Path) -> None:
    """Accepting is re-baselining, so a stale entry must not survive it and hide a regression."""
    known, report_path = written(tmp_path, ("CVE-2-2", "High"))
    write(known, ["CVE-1-1"])
    assert main(["--accept", str(known), str(report_path)]) == 0
    assert baseline(known) == {"CVE-2-2"}


def test_a_missing_report_is_reported_rather_than_treated_as_clean(tmp_path: Path) -> None:
    """A scan that did not run must never read as a scan that found nothing."""
    assert main([str(tmp_path / "k.txt"), str(tmp_path / "absent.json")]) == 1


def test_the_entrypoint_refuses_the_wrong_number_of_arguments() -> None:
    assert main([]) == 2
    assert main(["only-one"]) == 2
    assert main(["--accept", "only-one"]) == 2
