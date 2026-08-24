"""Where the images come from, and whether they are still there.

Pinning an image makes a build reproducible. It does not make the image *available*: the
Spark image this spine used to name was pinned to an exact tag and vanished anyway, because
its publisher moved its whole Docker Hub catalogue elsewhere and deleted the originals. A
digest pin would have gone with it, so this is not a failure that pinning harder can fix.

The set to ask a registry about is not the set of `image` keys, which is what this module used
to assume. A built image's tag is local: it names something this repository produces, so no
registry has ever heard of it and asking one reports a withdrawal that has not happened. What a
registry must still answer for is the base that image is built *from* -- the same supply-chain
claim, one level down, and the level the pin actually lives at. So each `image` key is sorted
into exactly one of two sets, and a third test asserts that the sorting accounts for all of
them, because the way this went wrong was an image quietly joining the wrong one.

Two claims, costing different things to check. That no reference comes from a namespace already
published as an archive is a fact about these files, checkable with no daemon. That every
reference still resolves is a fact about the world, and needs a client and a network, so it is
integration-tier and skips cleanly wherever Docker is absent.

Not checked here: that a built tag exists locally. That would be a claim about whether someone
has run a build yet, which changes with the order tests happen to run in and is proven anyway by
the stack starting at all.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import pytest
import yaml

from tests.conftest import COMPOSE_FILE, REPO_ROOT, describe_process, requires_docker

#: Namespaces that still answer for some tags but are published as frozen archives. Reaching
#: for one is how a withdrawn dependency comes back wearing a working URL -- bitnamilegacy
#: holds the exact tag this spine used to name, which makes it the path of least resistance
#: and the reason this assertion exists. Its publisher states that catalogue "will receive no
#: further updates or support".
ARCHIVED_NAMESPACES = ("bitnami/", "bitnamilegacy/")

MANIFEST_TIMEOUT_SECONDS = 60


def _services() -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return dict(loaded["services"])


SERVICES = _services()


def _build_context(service: dict[str, Any]) -> str | None:
    build = service.get("build")
    if build is None:
        return None
    return str(build if isinstance(build, str) else build["context"])


def pulled_images() -> list[str]:
    """The tags a registry has to hand over: named by the spine and built by someone else."""
    return sorted(
        {str(service["image"]) for service in SERVICES.values() if _build_context(service) is None}
    )


def built_bases() -> list[str]:
    """The `FROM` of everything this spine builds -- what a registry answers for instead."""
    bases: set[str] = set()
    for service in SERVICES.values():
        context = _build_context(service)
        if context is None:
            continue
        dockerfile = REPO_ROOT / context / "Dockerfile"
        bases.update(
            line.split()[1]
            for line in dockerfile.read_text(encoding="utf-8").splitlines()
            if line.startswith("FROM ")
        )
    return sorted(bases)


PULLED_IMAGES = pulled_images()
BUILT_BASES = built_bases()

#: Everything an upstream publisher could withdraw, which is what both tests below are about.
REGISTRY_REFERENCES = sorted(set(PULLED_IMAGES) | set(BUILT_BASES))


def test_the_spine_declares_images_for_these_tests_to_check() -> None:
    assert REGISTRY_REFERENCES, (
        "no upstream reference parsed out of the spine, so both tests below prove nothing"
    )


def test_every_service_image_is_either_pulled_or_built() -> None:
    """The guard on the sorting itself, and the one this module was missing.

    A service gaining a `build` moves its tag out of the pulled set, which is correct and also
    silent: the pin it used to be checked against stops being checked, and nothing says so. This
    asserts the two sets still account for every `image` key between them -- so an image can move
    from one to the other, but it cannot fall out of both.
    """
    declared = {str(service["image"]) for service in SERVICES.values()}
    built_tags = {
        str(service["image"])
        for service in SERVICES.values()
        if _build_context(service) is not None
    }
    unaccounted = declared - set(PULLED_IMAGES) - built_tags
    assert not unaccounted, (
        f"{sorted(unaccounted)} is neither pulled nor built, so no test asks anything about where "
        f"it comes from"
    )
    for tag in built_tags:
        assert tag not in PULLED_IMAGES, (
            f"{tag} is built here and also treated as a registry pin, which is the defect this "
            f"test exists for: no registry has heard of a tag this repository produces"
        )


@pytest.mark.parametrize("reference", REGISTRY_REFERENCES)
def test_no_image_comes_from_an_archived_namespace(reference: str) -> None:
    for namespace in ARCHIVED_NAMESPACES:
        assert not reference.startswith(namespace), (
            f"{reference} comes from {namespace}, which is published as an archive rather than "
            f"maintained; a pin there is a pin to an image that will never be patched again"
        )


@pytest.mark.integration
@requires_docker
@pytest.mark.parametrize("reference", REGISTRY_REFERENCES)
def test_every_pinned_image_still_resolves(reference: str) -> None:
    """The guard the withdrawal needed: an unpullable pin fails here, not halfway through up.

    Asking the registry about a reference is not the same as pulling it, which is what keeps
    this cheap enough to sit beside the rest of the integration tier.
    """
    binary = shutil.which("docker")
    assert binary is not None, "requires_docker admitted this test with no docker client present"
    argv = [binary, "manifest", "inspect", reference]
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
                f"resolving {reference}",
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
