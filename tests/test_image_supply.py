"""Where the images come from, and whether they are still there.

Pinning an image makes a build reproducible. It does not make the image *available*: the
Spark image this spine used to name was pinned to an exact tag and vanished anyway, because
its publisher moved its whole Docker Hub catalogue elsewhere and deleted the originals. A
digest pin would have gone with it, so this is not a failure that pinning harder can fix.

The set to ask a registry about is not the set of `image` keys, which is what this module used
to assume. A built image's tag is local: it names something this repository produces, so no
registry has ever heard of it and asking one reports a withdrawal that has not happened. What a
registry must still answer for is the base that image is built *from*: the same supply-chain
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

import re
import shutil
import subprocess
from typing import Any

import pytest
import yaml

from tests.conftest import COMPOSE_FILE, REPO_ROOT, describe_process, requires_docker

#: Namespaces that still answer for some tags but are published as frozen archives. Reaching
#: for one is how a withdrawn dependency comes back wearing a working URL; bitnamilegacy
#: holds the exact tag this spine used to name, which makes it the path of least resistance
#: and the reason this assertion exists. Its publisher states that catalogue "will receive no
#: further updates or support".
ARCHIVED_NAMESPACES = ("bitnami/", "bitnamilegacy/")

MANIFEST_TIMEOUT_SECONDS = 60

#: A reference pinned the way record 018 requires: a tag a reader recognises, then the bytes.
DIGEST_PINNED = re.compile(r"^[^\s@]+:[^\s@:]+@sha256:[0-9a-f]{64}$")


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
    """The `FROM` of everything this spine builds: what a registry answers for instead."""
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
    asserts the two sets still account for every `image` key between them, so an image can move
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
    completed = subprocess.run(  # noqa: S603 (fixed argv, resolved path, no shell)
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


# --------------------------------------------------------------------------------------------------
# Record 018: the pins themselves, which need no registry and so run everywhere.
# --------------------------------------------------------------------------------------------------


def test_every_pulled_reference_is_pinned_by_digest() -> None:
    """A tag its publisher can move is a pointer; the digest is the bytes.

    Record 012 probes that these references resolve. That proves they exist today and says nothing
    about their resolving to the same image tomorrow, which is what this asserts.
    """
    unpinned = [image for image in pulled_images() if not DIGEST_PINNED.match(image)]
    assert not unpinned, (
        f"{unpinned} name a tag with no digest. A moved tag rebuilds a different platform than the "
        f"one this suite passed on, with nothing in the repository changed to notice it."
    )


def test_every_built_base_is_pinned_by_digest() -> None:
    """The supply-chain claim for a locally built image is made on its base, in its Dockerfile."""
    unpinned = [base for base in built_bases() if not DIGEST_PINNED.match(base)]
    assert not unpinned, f"{unpinned} are FROM lines naming a tag with no digest"


def test_the_locally_built_reference_is_not_pinned_by_digest() -> None:
    """The trap record 018 exists to name.

    `docker image inspect` reports a RepoDigests entry for a locally built image, and pinning
    the compose key to it looks like the same discipline while being its opposite. A local digest
    is a fact about one image store, so it pins the spine to an artifact nobody else can get.
    """
    built = sorted(
        {
            str(service["image"])
            for service in SERVICES.values()
            if _build_context(service) is not None
        }
    )
    assert built, "no service builds, so this assertion proves nothing"
    pinned = [image for image in built if "@sha256:" in image]
    assert not pinned, (
        f"{pinned} are built here and pinned by digest. That digest is local rather than a "
        f"registry fact, so it pins the spine to an image no other machine can pull."
    )


def test_a_pinned_reference_keeps_its_tag() -> None:
    """A digest with no tag beside it is unreadable, so every version question needs a registry."""
    for image in [*pulled_images(), *built_bases()]:
        name, _, remainder = image.partition("@")
        assert ":" in name, (
            f"{image} carries a digest with no tag; the tag is the documentation and the digest is "
            f"the constraint, and a reviewer needs both"
        )
        assert remainder.startswith("sha256:")


def test_the_two_sets_between_them_cover_every_image_key() -> None:
    """Guards the same hole record 012 guards: a reference in neither set is unconstrained.

    Restated because these assertions read the same two functions, so a service whose `build` key
    moved would silently leave both rules rather than breaking one.
    """
    keys = {str(service["image"]) for service in SERVICES.values()}
    built = {
        str(service["image"])
        for service in SERVICES.values()
        if _build_context(service) is not None
    }
    assert set(pulled_images()) | built == keys
