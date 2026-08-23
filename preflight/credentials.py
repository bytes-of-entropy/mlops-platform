"""What the spine needs before it starts, and when each value is read.

Two callers share this module: the test suite, which skips the integration tier by name when a
credential is missing, and the doctor, which refuses to start the stack for the same reason. A
second implementation of "is this configured" would be a second place to be wrong, and the wrong
one is always the one nobody runs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

#: Read only while an empty data directory is being initialised. Changing one of these against a
#: volume that already exists changes nothing inside the volume -- the old value stays in force and
#: every client presenting the new one is refused.
FIRST_INIT = "first-init"

#: Re-read on every start, so the value can be rotated by editing .env and restarting.
EVERY_START = "every-start"


@dataclass(frozen=True)
class Credential:
    """When a value takes effect, and what handing the stack a different one therefore costs."""

    timing: str
    consequence: str


#: Every variable .env.example declares, classified by when its image reads it. This is the table
#: the whole preflight exists to act on: the failures worth catching before an ``up`` are the ones
#: where the file on disk and the state in the volume disagree, and only the first-init half can
#: disagree. A test fails when the example declares a variable this table does not classify,
#: because an unclassified credential is one whose failure mode nobody has thought about yet.
READ_TIMING: Mapping[str, Credential] = {
    "MINIO_ROOT_USER": Credential(
        EVERY_START,
        "MinIO reads its root credentials at every start, so rotating the pair is safe; MLflow is "
        "handed the same two values and picks up the change with it",
    ),
    "MINIO_ROOT_PASSWORD": Credential(
        EVERY_START,
        "rotatable with MINIO_ROOT_USER, and rotated in the same edit or neither works",
    ),
    "POSTGRES_USER": Credential(
        FIRST_INIT,
        "the superuser role is created once, while the data directory is initialised; a kept "
        'volume keeps the first run\'s role and answers a new one with FATAL: role "x" does not '
        "exist",
    ),
    "POSTGRES_PASSWORD": Credential(
        FIRST_INIT,
        "set on that same role at that same moment; a kept volume answers the new password with a "
        "password authentication failure, which compose reports only as an unhealthy container",
    ),
    "POSTGRES_DB": Credential(
        FIRST_INIT,
        "the database is created during the first initialisation only; renaming it later leaves "
        "the old database in place and points MLflow's backend URI at a name that does not exist",
    ),
    "AIRFLOW_FERNET_KEY": Credential(
        EVERY_START,
        "read at every start, so the key can be replaced -- but connections and variables already "
        "encrypted with the old one become unreadable, which is a data loss rather than an error",
    ),
    "AIRFLOW_ADMIN_PASSWORD": Credential(
        FIRST_INIT,
        "the entrypoint creates the admin account and tolerates its own failure, so against a "
        "database that already holds an admin the create is a silent no-op and the first run's "
        "password stays in force",
    ),
}


def _unquote(value: str) -> str:
    for quote in ('"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1]
    return value


def parse_env_pairs(text: str) -> dict[str, str]:
    """Name/value pairs out of dotenv-shaped text. Comments and blank lines are neither.

    Surrounding quotes are stripped because compose strips them: a value written as "abc" and one
    written as abc reach the container identically, so a comparison that told the two apart would
    report a mismatch the stack does not have.
    """
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        pairs[name.strip()] = _unquote(value.strip())
    return pairs


def effective_value(name: str, env_text: str | None, environ: Mapping[str, str]) -> str:
    """The value compose would interpolate, resolved the way compose resolves it.

    The shell environment wins over the file, which matters here rather than academically: a
    comparison that read the file while the container was handed the exported value would call a
    working stack broken.
    """
    exported = environ.get(name, "")
    if exported.strip():
        return exported
    return parse_env_pairs(env_text or "").get(name, "")


def missing_credentials(
    example_text: str, env_text: str | None, environ: Mapping[str, str]
) -> frozenset[str]:
    """Which variables the spine would refuse to start without.

    Required is read out of the example file rather than restated here, so a variable added to the
    spine cannot be remembered in one place and forgotten in the other. Satisfied means a
    non-empty value in ``.env`` *or* in the process environment, because compose reads both and
    exporting the variables instead of writing them to a file is a supported choice rather than a
    workaround -- a guard that only looked for the file would skip on a machine that was in fact
    ready.
    """
    required = set(parse_env_pairs(example_text))
    satisfied = {name for name, value in parse_env_pairs(env_text or "").items() if value}
    satisfied |= {name for name, value in environ.items() if value.strip()}
    return frozenset(required - satisfied)


def credentials_skip_reason(missing: frozenset[str]) -> str:
    """Name the variables, because "not configured" is not an instruction."""
    return (
        "the compose spine has no credentials to start with: "
        + ", ".join(sorted(missing))
        + " unset in both .env and the environment. Copy .env.example to .env and fill it in."
    )


def fingerprint(salt: str, user: str, password: str) -> str:
    """The digest the first initialisation recorded, recomputed from the values in hand.

    Salted, and the salt is generated inside the volume at that first initialisation. An unsalted
    digest of a credential pair is a password oracle for whoever can read the file, and this file
    is written into a volume reviewers are explicitly invited to keep. The salt buys nothing
    against someone holding the file and one good guess; it buys everything against a precomputed
    table.

    Must stay byte-identical to what postgres/init/00-record-init-credentials.sh computes, which is
    why both sides join with a colon and neither appends a newline.
    """
    return hashlib.sha256(f"{salt}:{user}:{password}".encode()).hexdigest()
