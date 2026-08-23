"""The skip decision itself, because a wrong skip is invisible.

A test that skips when it should run looks exactly like a test that ran, and the whole
integration tier of this repository hangs off one boolean.
"""

from __future__ import annotations

import pytest

from preflight.runtime import (
    DOCKER_ABSENT,
    DOCKER_READY,
    DOCKER_STOPPED,
    SKIP_REASONS,
    classify_docker_state,
)


def test_no_binary_means_absent() -> None:
    assert classify_docker_state(None, None) == DOCKER_ABSENT


def test_a_binary_that_answers_means_ready() -> None:
    assert classify_docker_state("/usr/bin/docker", 0) == DOCKER_READY


@pytest.mark.parametrize("probe", [1, 125, None])
def test_a_binary_whose_daemon_does_not_answer_means_stopped(probe: int | None) -> None:
    """The case a presence check gets wrong.

    ``None`` is the probe failing to run or timing out; a nonzero code is the daemon refusing.
    Both are unusable, and neither is the same as not having Docker installed.
    """
    assert classify_docker_state("/usr/bin/docker", probe) == DOCKER_STOPPED


def test_each_unusable_state_says_something_different_to_do_about_it() -> None:
    """ "Install Docker" and "start Docker" are different instructions."""
    assert set(SKIP_REASONS) == {DOCKER_ABSENT, DOCKER_STOPPED}
    assert SKIP_REASONS[DOCKER_ABSENT] != SKIP_REASONS[DOCKER_STOPPED]
