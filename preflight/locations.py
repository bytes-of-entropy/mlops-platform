"""Where things are, in one place.

Both the test suite and the doctor need these paths, and a path computed twice is a path that
can be computed differently once.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "compose" / "docker-compose.yml"
QUICKSTART_FILE = REPO_ROOT / "compose" / "docker-compose.quickstart.yml"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
ENV_FILE = REPO_ROOT / ".env"


def read_text_if_present(path: Path) -> str | None:
    """The contents, or ``None`` for a file that is legitimately absent.

    ``.env`` is the case: it is gitignored and a machine that exports the variables instead never
    creates one, so its absence is a state to report rather than an error to raise.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
