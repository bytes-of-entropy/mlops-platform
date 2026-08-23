"""The other skip decision, and the data it reads.

The Docker probe next door exists because installed is not the same as usable. This is the
same shape one layer along: a runtime that answers is not the same as a spine that can start,
because compose refuses to render a file with an unset interpolation. Both preconditions are
legitimate states for a fresh machine to be in, and each has to say which one it is.

The variable list is not written here. It is read from .env.example, so most of what follows
is about whether that file is a trustworthy source -- which is the only thing the guard
depends on.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import (
    COMPOSE_FILE,
    ENV_EXAMPLE_FILE,
    QUICKSTART_FILE,
    credentials_skip_reason,
    missing_credentials,
    parse_env_pairs,
)

#: The three interpolation forms compose accepts all name the variable the same way.
INTERPOLATION = re.compile(r"\$\{([A-Z0-9_]+)")

EXAMPLE_TEXT = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")


def interpolated_names() -> set[str]:
    names: set[str] = set()
    for path in (COMPOSE_FILE, QUICKSTART_FILE):
        names |= set(INTERPOLATION.findall(path.read_text(encoding="utf-8")))
    return names


def test_the_example_file_names_variables_at_all() -> None:
    """The guard reads its required set from this file, so an empty parse disarms it silently."""
    assert parse_env_pairs(EXAMPLE_TEXT), ".env.example parsed to nothing; the guard has no input"


def test_every_variable_the_compose_files_interpolate_is_in_the_example() -> None:
    """A variable the spine needs and the example omits is one the guard cannot ask for."""
    assert interpolated_names() <= set(parse_env_pairs(EXAMPLE_TEXT))


def test_the_example_names_nothing_the_compose_files_do_not_use() -> None:
    """The other direction: a leftover name would skip the tier over a variable nobody reads."""
    assert set(parse_env_pairs(EXAMPLE_TEXT)) <= interpolated_names()


def test_comments_and_blank_lines_are_not_variables() -> None:
    parsed = parse_env_pairs("# a comment\n\n  \nREAL=value\n")
    assert parsed == {"REAL": "value"}


def test_a_name_with_no_value_parses_as_empty_rather_than_being_dropped() -> None:
    """.env.example ships every name with an empty value, which is how required is discovered."""
    assert parse_env_pairs("EMPTY=\n") == {"EMPTY": ""}


def test_a_variable_written_in_the_env_file_counts_as_satisfied() -> None:
    assert missing_credentials("NEEDED=\n", "NEEDED=set\n", {}) == frozenset()


def test_a_variable_exported_in_the_environment_counts_too() -> None:
    """Running with the variables exported instead of written down is a supported choice."""
    assert missing_credentials("NEEDED=\n", None, {"NEEDED": "set"}) == frozenset()


@pytest.mark.parametrize("value", ["", "   "])
def test_a_present_but_empty_value_does_not_count(value: str) -> None:
    """Compose treats an empty value as unset, and so must this."""
    assert missing_credentials("NEEDED=\n", f"NEEDED={value}\n", {}) == frozenset({"NEEDED"})


def test_a_default_already_filled_in_the_example_needs_nothing_added() -> None:
    """POSTGRES_DB ships with a value, so copying the file satisfies it."""
    assert missing_credentials("FILLED=platform\n", "FILLED=platform\n", {}) == frozenset()


def test_every_missing_variable_is_reported_not_just_the_first() -> None:
    """Fixing them one round-trip at a time is the failure mode this avoids."""
    missing = missing_credentials("ONE=\nTWO=\nTHREE=\n", "TWO=set\n", {})
    assert missing == frozenset({"ONE", "THREE"})


def test_the_reason_names_each_missing_variable_and_what_to_do_about_it() -> None:
    reason = credentials_skip_reason(frozenset({"MINIO_ROOT_PASSWORD", "POSTGRES_PASSWORD"}))
    assert "MINIO_ROOT_PASSWORD" in reason
    assert "POSTGRES_PASSWORD" in reason
    assert ".env.example" in reason
