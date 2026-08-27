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
    assert classify_docker_state(None, None, None) == DOCKER_ABSENT


def test_a_binary_that_answers_with_a_server_version_means_ready() -> None:
    assert classify_docker_state("/usr/bin/docker", 0, "27.1.1\n") == DOCKER_READY


@pytest.mark.parametrize("probe", [1, 125, None])
def test_a_binary_whose_daemon_does_not_answer_means_stopped(probe: int | None) -> None:
    """The case a presence check gets wrong.

    ``None`` is the probe failing to run or timing out; a nonzero code is the daemon refusing.
    Both are unusable, and neither is the same as not having Docker installed.
    """
    assert classify_docker_state("/usr/bin/docker", probe, None) == DOCKER_STOPPED


@pytest.mark.parametrize("printed", ["", "\n", "   ", None])
def test_a_zero_exit_with_no_server_version_means_stopped(printed: str | None) -> None:
    """The case an exit-code check gets wrong, observed on the build machine.

    A Docker Desktop stuck part-way up answered `docker info`, exited zero and printed an empty
    server version. The tier ran instead of skipping and all eight of its tests failed with
    `Error response from daemon: Docker Desktop is unable to start`, which reads as a broken stack
    rather than a stopped one. Only a running daemon can supply a version, so the version decides.
    """
    assert classify_docker_state("/usr/bin/docker", 0, printed) == DOCKER_STOPPED


def test_each_unusable_state_says_something_different_to_do_about_it() -> None:
    """ "Install Docker" and "start Docker" are different instructions."""
    assert set(SKIP_REASONS) == {DOCKER_ABSENT, DOCKER_STOPPED}
    assert SKIP_REASONS[DOCKER_ABSENT] != SKIP_REASONS[DOCKER_STOPPED]
