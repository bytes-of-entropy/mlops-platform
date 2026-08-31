"""What an integration failure says about itself.

The integration tier runs on one machine and is read on another, so its assertion text is
the entire diagnosis. `compose up failed:` followed by nothing is a true statement and a
useless one: it was produced by reading only stderr, which Docker Compose does not
reliably use. These tests hold the report to naming the command, the exit code, and both
streams, including when a stream is empty, and to carrying whatever the caller gathered
afterwards, because the reason a stack refused to come up is normally in a container's log
and not in the output of the command that started it.
"""

from __future__ import annotations

import ast
import pathlib

from tests.conftest import MAX_REPORT_LINES, REPO_ROOT, describe_process

ARGV = ["docker", "compose", "up", "-d", "--wait"]


def test_the_report_names_the_command_that_failed() -> None:
    report = describe_process("compose up", ARGV, 1, "", "boom")
    assert "docker compose up -d --wait" in report


def test_the_report_gives_the_exit_code() -> None:
    """125 and 1 mean different things, and neither is visible in the streams."""
    assert "exit code 125" in describe_process("compose up", ARGV, 125, "", "boom")


def test_an_empty_stream_says_so_rather_than_printing_nothing() -> None:
    """The bug this file exists for: silence that reads as "no output was captured"."""
    report = describe_process("compose up", ARGV, 1, "", "")
    assert "stderr: empty" in report
    assert "stdout: empty" in report


def test_both_streams_are_reported_because_compose_uses_both() -> None:
    report = describe_process("compose up", ARGV, 1, "on stdout", "on stderr")
    assert "on stdout" in report
    assert "on stderr" in report


def test_a_long_stream_keeps_its_tail_where_the_error_is() -> None:
    lines = [f"line {index}" for index in range(MAX_REPORT_LINES + 10)]
    report = describe_process("compose up", ARGV, 1, "", "\n".join(lines))
    assert lines[-1] in report
    assert lines[0] not in report


def test_a_truncated_stream_admits_how_much_it_dropped() -> None:
    """Silent truncation reads as complete output, which is the same failure one level up."""
    total = MAX_REPORT_LINES + 10
    report = describe_process("compose up", ARGV, 1, "", "\n".join(["x"] * total))
    assert f"last {MAX_REPORT_LINES} of {total}" in report


def test_a_short_stream_is_not_labelled_as_truncated() -> None:
    assert "last" not in describe_process("compose up", ARGV, 1, "", "one line")


def test_gathered_sections_are_carried_into_the_report() -> None:
    """The postgres case: compose says "unhealthy", the service log says which role is missing."""
    report = describe_process(
        "compose up",
        ARGV,
        1,
        "container mlops-platform-postgres-1 is unhealthy",
        "",
        {"service logs": 'FATAL:  role "someone" does not exist'},
    )
    assert "service logs:" in report
    assert 'role "someone" does not exist' in report


def test_a_gathered_section_that_came_back_empty_says_so() -> None:
    report = describe_process("compose up", ARGV, 1, "", "", {"compose ps": ""})
    assert "compose ps: empty" in report


def test_a_long_gathered_section_is_truncated_like_the_streams() -> None:
    total = MAX_REPORT_LINES + 5
    report = describe_process(
        "compose up", ARGV, 1, "", "", {"service logs": "\n".join(["y"] * total)}
    )
    assert f"service logs (last {MAX_REPORT_LINES} of {total})" in report


def test_gathered_sections_keep_the_order_the_caller_gave_them() -> None:
    """State first, then logs: the reader wants to know which service before reading its log."""
    report = describe_process(
        "compose up", ARGV, 1, "", "", {"compose ps": "state here", "service logs": "log here"}
    )
    assert report.index("compose ps") < report.index("service logs")


def integration_modules() -> list[pathlib.Path]:
    """Every file that drives real infrastructure: the shared plumbing plus each integration module.

    Discovered rather than listed. A named list is a list someone has to remember to extend, and
    the module they forget is the one whose failure nobody can read. `stackops.py` was named here
    when it was the only plumbing there was, and `clusterops.py` arriving is exactly the case that
    argument was about, so the plumbing is globbed too.
    """
    tests = pathlib.Path(REPO_ROOT, "tests")
    found = sorted(tests.glob("*ops.py"))
    found.extend(
        path
        for path in sorted(tests.glob("test_*.py"))
        if "pytest.mark.integration" in path.read_text(encoding="utf-8")
    )
    return found


def test_no_integration_assertion_reads_a_stream_without_the_report() -> None:
    """The report is worth only as much as its call sites.

    A helper fixed everywhere except the two functions that start and stop the stack leaves
    the one failure that matters reporting stderr alone, which is the original bug, still
    present, behind eleven passing tests. So the constraint is on the modules, not the helper:
    nothing in the integration tier may assert on a return code itself.
    """
    modules = integration_modules()
    assert len(modules) > 1, "no integration module was discovered, so this test proves nothing"
    for path in modules:
        offenders = [
            node.lineno
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Assert) and "returncode" in ast.dump(node.test)
        ]
        assert not offenders, (
            f"tests/{path.name} asserts on a return code directly at line(s) "
            f"{offenders}; route it through Stack.check() so the failure reports itself"
        )
