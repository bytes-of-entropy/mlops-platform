"""Reading a fenced JSON payload out of a container's stdout.

The function under test is the fix for a defect that reached the build machine: two integration
modules ran a Python snippet inside a container and parsed the whole of stdout as one JSON document.
MLflow 2.22 prints a "View run at ..." banner when a run exits and MLflow 2.13 did not, so the first
suite run after the base bump failed with `Expecting value: line 1 column 1` on an artifact round
trip that had *succeeded* — the JSON was present, with the right body, behind two lines of someone
else's output.

Tested here rather than only through the tier that uses it, because the tier needs a daemon and
credentials and runs on one machine, and this function is pure. The original defect was a
pure-text bug in a code path only a container could reach, which is the least convenient place
to keep one.
"""

from __future__ import annotations

import json

import pytest

from tests.stackops import PAYLOAD, payload

#: The literal shape of the failure, reconstructed from the build machine's traceback. Both
#: banner lines came back with escaped rather than real newlines, which is why the reader
#: searches the whole string for the marker instead of splitting into lines first.
OBSERVED = (
    "\U0001f3c3 View run aged-dog-886 at: "
    "http://localhost:5000/#/experiments/1/runs/d5bc5a1d2100436081324895ec3a6b1c\\n"
    "\U0001f9ea View experiment at: http://localhost:5000/#/experiments/1\\n"
    + PAYLOAD
    + '{"run_id": "d5bc5a1d2100436081324895ec3a6b1c", "keys": ["1/d5bc/artifacts/probe.txt"], '
    '"matched": ["1/d5bc/artifacts/probe.txt"], '
    '"body": "artifact store round trip, asserted rather than assumed"}\\n'
)


def test_the_payload_is_read_out_of_the_output_that_actually_failed() -> None:
    """The regression test, against the string the build machine produced rather than a stand-in."""
    result = payload(OBSERVED, "artifact round trip")
    assert result["body"] == "artifact store round trip, asserted rather than assumed"
    assert result["matched"] == ["1/d5bc/artifacts/probe.txt"]


def test_stdout_that_is_only_the_payload_still_reads() -> None:
    """The case that worked before, which the fix must not have broken."""
    assert payload(PAYLOAD + '{"ok": true}', "plain") == {"ok": True}


def test_output_after_the_payload_is_ignored() -> None:
    """`raw_decode`, not `loads`: a library may print on the way out as well as on the way in."""
    assert payload(PAYLOAD + '{"ok": true}\ngoodbye from some library\n', "trailing") == {
        "ok": True
    }


def test_a_list_payload_reads() -> None:
    """One of the two call sites fences a list rather than an object."""
    assert payload(PAYLOAD + '["mlflow", "other"]', "buckets") == ["mlflow", "other"]


def test_the_last_marker_wins() -> None:
    """A snippet that somehow printed twice meant its final answer."""
    assert payload(f'{PAYLOAD}{{"n": 1}}\n{PAYLOAD}{{"n": 2}}', "twice") == {"n": 2}


def test_a_missing_marker_says_the_snippet_never_printed() -> None:
    """Distinct from bad JSON, because the causes are different and so are the next steps.

    No marker means the snippet died before its last line, so the interesting evidence is
    whatever it did print. Bad JSON after a marker means it printed and the payload is malformed.
    """
    with pytest.raises(AssertionError, match="did not reach"):
        payload("Traceback (most recent call last):\n  ImportError: no mlflow\n", "round trip")


def test_malformed_json_after_the_marker_is_reported_as_such() -> None:
    with pytest.raises(AssertionError, match="is not JSON"):
        payload(PAYLOAD + "{not json", "round trip")


def test_the_failure_message_carries_the_output_it_could_not_read() -> None:
    """An integration failure is produced on one machine and read on another.

    A bare "could not parse" costs a round trip to ask what the container actually said, the
    same argument `Stack.check` already makes for compose failures.
    """
    with pytest.raises(AssertionError) as raised:
        payload("mystery output", "round trip")
    assert "mystery output" in str(raised.value)


def test_an_empty_stdout_is_a_missing_marker_rather_than_a_crash() -> None:
    with pytest.raises(AssertionError, match="did not reach"):
        payload("", "round trip")


def test_the_marker_cannot_be_valid_json_on_its_own() -> None:
    """Otherwise a payload could be mistaken for the fence, or the fence for a payload."""
    with pytest.raises(json.JSONDecodeError):
        json.loads(PAYLOAD)
