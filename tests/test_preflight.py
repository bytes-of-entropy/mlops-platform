"""The preflight checks, exercised in every state including the ones this machine cannot reach.

`make doctor` runs before every `up`, so it is the one piece of code here that fails closed: a
check that reports OK when it could not tell would hand a reviewer a stack that starts and then
misbehaves for a reason nothing printed. That makes the interesting cases the negative ones: a
volume built with other credentials, a volume that predates the record, a probe that came back
unreadable, and every one of them is reachable here because the checks read what they are given
rather than gathering it themselves.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from preflight.checks import (
    CREDENTIALS,
    FAIL,
    OK,
    ORDER,
    POSTGRES_VOLUME,
    RUNTIME,
    UNKNOWN,
    Inputs,
    check_credentials,
    check_postgres_volume,
    check_runtime,
    first_init_variables,
    run,
)
from preflight.credentials import (
    EVERY_START,
    FIRST_INIT,
    READ_TIMING,
    effective_value,
    fingerprint,
    parse_env_pairs,
)
from preflight.locations import ENV_EXAMPLE_FILE, REPO_ROOT
from preflight.runtime import (
    DOCKER_ABSENT,
    DOCKER_READY,
    DOCKER_STOPPED,
    VOLUME_EMPTY,
    VOLUME_FINGERPRINTED,
    VOLUME_UNFINGERPRINTED,
    VOLUME_UNREADABLE,
    VolumeState,
    parse_volume_report,
)

EXAMPLE_TEXT = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")
INIT_SCRIPT = REPO_ROOT / "postgres" / "init" / "00-record-init-credentials.sh"

USER = "platform"
PASSWORD = "1f4c9b2e7a"  # noqa: S105 (an invented value to digest, not a credential)
SALT = "0123456789abcdef0123456789abcdef"


def filled_env() -> str:
    """An `.env` that satisfies the example, so a test can vary one thing at a time."""
    return "\n".join(f"{name}=value-for-{name.lower()}" for name in parse_env_pairs(EXAMPLE_TEXT))


def no_volume_read() -> VolumeState:
    raise AssertionError("the volume was probed after an earlier check had already failed")


# --- the classification table ------------------------------------------------------------------


def test_every_variable_the_example_declares_is_classified() -> None:
    """An unclassified credential is one whose failure mode nobody has worked out yet.

    The table is what the volume check acts on and what the docs quote, so a variable added to
    .env.example without a row here would be a credential with no stated read timing, which is
    exactly the state Airflow's admin password was in when its login existed only on paper.
    """
    declared = set(parse_env_pairs(EXAMPLE_TEXT))
    unclassified = declared - set(READ_TIMING)
    assert not unclassified, f"declared in .env.example but not classified: {sorted(unclassified)}"


def test_the_table_classifies_nothing_the_example_does_not_declare() -> None:
    """A row for a variable nobody sets is a claim about a credential that is not in the file."""
    stale = set(READ_TIMING) - set(parse_env_pairs(EXAMPLE_TEXT))
    assert not stale, f"classified but no longer declared in .env.example: {sorted(stale)}"


def test_each_entry_uses_one_of_the_two_timings_and_explains_the_cost() -> None:
    for name, entry in READ_TIMING.items():
        assert entry.timing in (FIRST_INIT, EVERY_START), f"{name} has timing {entry.timing!r}"
        assert len(entry.consequence.split()) >= 8, (
            f"{name}'s consequence is too short to tell anyone what a mismatch costs"
        )


def test_the_postgres_pair_is_pinned_by_the_volume() -> None:
    """If this ever reads every-start, the check below is checking nothing."""
    assert "POSTGRES_USER" in first_init_variables()
    assert "POSTGRES_PASSWORD" in first_init_variables()


# --- reading values the way compose reads them --------------------------------------------------


def test_a_quoted_value_and_a_bare_one_are_the_same_value() -> None:
    """Compose strips the quotes, so a comparison that kept them would invent a mismatch."""
    assert parse_env_pairs('POSTGRES_USER="platform"')["POSTGRES_USER"] == "platform"
    assert parse_env_pairs("POSTGRES_USER='platform'")["POSTGRES_USER"] == "platform"


def test_an_exported_variable_wins_over_the_file_because_compose_says_so() -> None:
    """The CI runner exports what it generates, so reading the file compares the wrong pair."""
    assert effective_value("POSTGRES_USER", "POSTGRES_USER=from-file", {}) == "from-file"
    assert (
        effective_value("POSTGRES_USER", "POSTGRES_USER=from-file", {"POSTGRES_USER": "exported"})
        == "exported"
    )


# --- the individual checks ----------------------------------------------------------------------


def test_the_runtime_check_passes_only_when_the_daemon_answered() -> None:
    assert check_runtime(DOCKER_READY).status == OK
    for state in (DOCKER_ABSENT, DOCKER_STOPPED):
        result = check_runtime(state)
        assert result.status == FAIL
        assert result.detail, f"{state} failed without saying what to do about it"


def test_the_credentials_check_names_what_is_missing() -> None:
    result = check_credentials(EXAMPLE_TEXT, "", {})
    assert result.status == FAIL
    assert "POSTGRES_USER" in result.detail


def test_the_credentials_check_accepts_values_from_the_environment_alone() -> None:
    """A machine that exports them instead of writing a file is configured, not broken."""
    exported = {name: "set" for name in parse_env_pairs(EXAMPLE_TEXT)}
    assert check_credentials(EXAMPLE_TEXT, None, exported).status == OK


def test_an_empty_volume_is_a_pass_because_the_next_start_creates_it() -> None:
    result = check_postgres_volume(VolumeState(VOLUME_EMPTY), USER, PASSWORD)
    assert result.status == OK


def test_a_volume_built_with_these_credentials_passes() -> None:
    digest = fingerprint(SALT, USER, PASSWORD)
    state = VolumeState(VOLUME_FINGERPRINTED, salt=SALT, digest=digest)
    assert check_postgres_volume(state, USER, PASSWORD).status == OK


def test_a_volume_built_with_a_different_password_fails_and_says_how_to_recover() -> None:
    """The failure this whole component exists for, and the one a re-clone cannot clear.

    The volume name is derived from the directory name, so cloning again into the same directory
    finds the same volume. Anyone who reads only "it does not work" tries a fresh clone first.
    """
    state = VolumeState(VOLUME_FINGERPRINTED, salt=SALT, digest=fingerprint(SALT, USER, "other"))
    result = check_postgres_volume(state, USER, PASSWORD)
    assert result.status == FAIL
    assert "POSTGRES_PASSWORD" in result.detail
    assert "make reset" in result.detail, "the failure does not say how to get out of it"
    assert "MLflow" in result.detail, (
        "the recovery discards history, and that has to be said rather than implied"
    )


def test_a_volume_that_predates_the_fingerprint_reports_that_it_cannot_tell() -> None:
    """Not OK. An existing volume carries no record, and calling that a pass is the original bug."""
    result = check_postgres_volume(VolumeState(VOLUME_UNFINGERPRINTED), USER, PASSWORD)
    assert result.status == UNKNOWN
    assert "cannot verify" in result.detail


def test_an_unreadable_probe_reports_that_it_cannot_tell_either() -> None:
    state = VolumeState(VOLUME_UNREADABLE, detail="exit code 1: no such volume")
    result = check_postgres_volume(state, USER, PASSWORD)
    assert result.status == UNKNOWN
    assert "no such volume" in result.detail


# --- the pipeline -------------------------------------------------------------------------------


def test_a_stopped_daemon_stops_the_run_before_it_starts_a_container() -> None:
    """A probe on a machine with no daemon replaces a clear message with a connection error."""
    results = run(
        Inputs(
            docker_state=DOCKER_STOPPED,
            example_text=EXAMPLE_TEXT,
            env_text=filled_env(),
            environ={},
            read_volume=no_volume_read,
        )
    )
    assert results[0].name == RUNTIME
    assert results[0].status == FAIL


def test_missing_credentials_stop_the_run_before_compose_is_asked_to_render() -> None:
    """Compose refuses to render an unset interpolation, so the probe cannot run either."""
    results = run(
        Inputs(
            docker_state=DOCKER_READY,
            example_text=EXAMPLE_TEXT,
            env_text="",
            environ={},
            read_volume=no_volume_read,
        )
    )
    assert [result.status for result in results[:2]] == [OK, FAIL]


def test_the_checks_that_never_ran_are_listed_rather_than_omitted() -> None:
    """A short list of lines reads as a clean bill of health.

    Three green lines and three checks is a pass; two green lines and three checks is a pass with
    something unexamined, and only one of those two is what happened.
    """
    results = run(
        Inputs(
            docker_state=DOCKER_ABSENT,
            example_text=EXAMPLE_TEXT,
            env_text=filled_env(),
            environ={},
            read_volume=no_volume_read,
        )
    )
    assert [result.name for result in results] == list(ORDER)
    skipped = [result for result in results if result.name in (CREDENTIALS, POSTGRES_VOLUME)]
    assert all(result.status == UNKNOWN for result in skipped)
    assert all("not checked" in result.detail for result in skipped)


def test_a_ready_machine_runs_every_check_including_the_volume() -> None:
    env = filled_env()
    user = effective_value("POSTGRES_USER", env, {})
    password = effective_value("POSTGRES_PASSWORD", env, {})
    digest = fingerprint(SALT, user, password)
    results = run(
        Inputs(
            docker_state=DOCKER_READY,
            example_text=EXAMPLE_TEXT,
            env_text=env,
            environ={},
            read_volume=lambda: VolumeState(VOLUME_FINGERPRINTED, salt=SALT, digest=digest),
        )
    )
    assert [result.status for result in results] == [OK, OK, OK]
    assert [result.name for result in results] == list(ORDER)


# --- the one-shot container's report ------------------------------------------------------------


def test_the_report_is_found_past_whatever_compose_narrated_first() -> None:
    """Compose announces pulls, volumes and containers, and picks a stream by version."""
    noisy = "[+] Creating 1/1\n Volume mlops-platform_postgres-data Created\nfingerprint\nA:B\n"
    state = parse_volume_report(0, noisy, "")
    assert state.kind == VOLUME_FINGERPRINTED
    assert (state.salt, state.digest) == ("A", "B")


def test_a_failed_probe_is_unreadable_rather_than_empty() -> None:
    state = parse_volume_report(1, "", "no configuration file provided")
    assert state.kind == VOLUME_UNREADABLE
    assert "exit code 1" in state.detail
    assert "no configuration file" in state.detail


def test_a_fingerprint_that_is_not_salt_and_digest_is_unreadable() -> None:
    """Half a record is not a match and not an absence; treating it as either would be a guess."""
    assert parse_volume_report(0, "fingerprint\nonlyonefield\n", "").kind == VOLUME_UNREADABLE


def test_the_two_volume_states_that_are_not_fingerprints_are_read_as_themselves() -> None:
    assert parse_volume_report(0, f"{VOLUME_EMPTY}\n", "").kind == VOLUME_EMPTY
    assert parse_volume_report(0, f"{VOLUME_UNFINGERPRINTED}\n", "").kind == VOLUME_UNFINGERPRINTED


def test_silence_from_the_probe_is_not_read_as_an_empty_volume() -> None:
    """A zero exit with no marker means the script did not run, not that there is no data."""
    assert parse_volume_report(0, "", "").kind == VOLUME_UNREADABLE


# --- the two implementations of one digest ------------------------------------------------------

POSIX_TOOLS = ("sh", "sha256sum", "od")
missing_posix_tools = [tool for tool in POSIX_TOOLS if shutil.which(tool) is None]

requires_posix_tools = pytest.mark.skipif(
    bool(missing_posix_tools),
    reason=f"no POSIX shell to run the init script with: {', '.join(missing_posix_tools)} absent",
)


@requires_posix_tools
def test_the_init_script_and_the_python_digest_agree(tmp_path: Path) -> None:
    """The comparison is only worth anything if both sides compute the same thing.

    Two implementations of one digest agree until the day they do not, and the day they stop is the
    day every existing volume starts reporting a credential mismatch it does not have. Running the
    real script needs no container: it writes one file from three environment variables.
    """
    shell = shutil.which("sh")
    assert shell, "the skip guard let a machine without sh reach this test"

    completed = subprocess.run(  # noqa: S603 (resolved interpreter, fixed argv, no shell)
        [shell, INIT_SCRIPT.as_posix()],
        env={
            "PATH": "/usr/bin:/bin",
            "PGDATA": tmp_path.as_posix(),
            "POSTGRES_USER": USER,
            "POSTGRES_PASSWORD": PASSWORD,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, f"the init script failed: {completed.stderr.strip()}"

    recorded = (tmp_path / ".init-credentials").read_text(encoding="utf-8")
    salt, _, digest = recorded.partition(":")
    assert salt and digest, f"the script wrote {recorded!r}, which is not salt:digest"
    assert digest == fingerprint(salt, USER, PASSWORD), (
        "the shell and the Python disagree about the digest, so every volume the script has "
        "fingerprinted would now report a mismatch"
    )


@requires_posix_tools
def test_the_recorded_file_does_not_contain_the_credentials(tmp_path: Path) -> None:
    """It lives in a volume reviewers are invited to keep, so it has to be safe to keep."""
    shell = shutil.which("sh")
    assert shell
    subprocess.run(  # noqa: S603 (resolved interpreter, fixed argv, no shell)
        [shell, INIT_SCRIPT.as_posix()],
        env={
            "PATH": "/usr/bin:/bin",
            "PGDATA": tmp_path.as_posix(),
            "POSTGRES_USER": USER,
            "POSTGRES_PASSWORD": PASSWORD,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    recorded = (tmp_path / ".init-credentials").read_text(encoding="utf-8")
    assert USER not in recorded
    assert PASSWORD not in recorded


def test_two_initialisations_of_the_same_credentials_record_different_digests() -> None:
    """Salted per volume: identical credentials must not produce a shareable digest."""
    assert fingerprint("aaaa", USER, PASSWORD) != fingerprint("bbbb", USER, PASSWORD)
