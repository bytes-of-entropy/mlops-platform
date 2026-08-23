"""Where the images come from, and whether they are still there.

Pinning an image makes a build reproducible. It does not make the image *available*: the
Spark image this spine used to name was pinned to an exact tag and vanished anyway, because
its publisher moved its whole Docker Hub catalogue elsewhere and deleted the originals. A
digest pin would have gone with it, so this is not a failure that pinning harder can fix.

Two tiers, because the two claims cost different things to check. That no image comes from a
namespace already published as an archive is a fact about this file, checkable with no daemon.
That every pin still resolves is a fact about the world, and needs a client and a network, so
it is integration-tier and skips cleanly wherever Docker is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import pytest
import yaml

from tests.conftest import COMPOSE_FILE, describe_process, requires_docker

#: Namespaces that still answer for some tags but are published as frozen archives. Reaching
#: for one is how a withdrawn dependency comes back wearing a working URL -- bitnamilegacy
#: holds the exact tag this spine used to name, which makes it the path of least resistance
#: and the reason this assertion exists. Its publisher states that catalogue "will receive no
#: further updates or support".
ARCHIVED_NAMESPACES = ("bitnami/", "bitnamilegacy/")

MANIFEST_TIMEOUT_SECONDS = 60


def pinned_images() -> list[str]:
    loaded = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services: dict[str, dict[str, Any]] = dict(loaded["services"])
    return sorted({str(service["image"]) for service in services.values()})


PINNED_IMAGES = pinned_images()


def test_the_spine_declares_images_for_these_tests_to_check() -> None:
    assert PINNED_IMAGES, "no image parsed out of the spine, so both tests below prove nothing"


@pytest.mark.parametrize("image", PINNED_IMAGES)
def test_no_image_comes_from_an_archived_namespace(image: str) -> None:
    for namespace in ARCHIVED_NAMESPACES:
        assert not image.startswith(namespace), (
            f"{image} comes from {namespace}, which is published as an archive rather than "
            f"maintained; a pin there is a pin to an image that will never be patched again"
        )


@pytest.mark.integration
@requires_docker
@pytest.mark.parametrize("image", PINNED_IMAGES)
def test_every_pinned_image_still_resolves(image: str) -> None:
    """The guard the withdrawal needed: an unpullable pin fails here, not halfway through up.

    Asking the registry about a reference is not the same as pulling it, which is what keeps
    this cheap enough to sit beside the rest of the integration tier.
    """
    binary = shutil.which("docker")
    assert binary is not None, "requires_docker admitted this test with no docker client present"
    argv = [binary, "manifest", "inspect", image]
    completed = subprocess.run(  # noqa: S603 -- fixed argv, resolved path, no shell
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=MANIFEST_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            describe_process(
                f"resolving {image}",
                argv,
                completed.returncode,
                completed.stdout,
                completed.stderr,
                {
                    "consequence": "this pin resolves in no configured registry, so nobody can "
                    "start this spine; the fix is a deliberate bump with the new tag committed"
                },
            )
        )
