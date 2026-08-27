"""The shared/per-track boundary, enforced rather than remembered.

`docs/shared-source.md` moved the wire contract into `lib/due_shared`
because the tracks had been hand-copying it and it had already drifted
twice - a missing `frame_crc32_update` on Track A, and a version string
that disagreed with its own numbers on both.

Nothing stops that growing back. A future session adding a header to a
track's own folder, with a name the shared library already uses, gets
whichever the include path reaches first and no diagnostic at all; the
two copies then drift exactly as before. So this checks it.

Board-free and instant, and it runs in the same suite as everything
else so a divergence fails the same run that introduced it.
"""

import os

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

SHARED = os.path.join(REPO, "lib", "due_shared", "src")

# Where each track keeps its own code.
TRACK_DIRS = [
    os.path.join(REPO, "drivers"),
    os.path.join(REPO, "bsp"),
    os.path.join(REPO, "apps", "baremetal_bringup"),
    os.path.join(REPO, "sketches", "bringup"),
]


def _names(d, exts):
    if not os.path.isdir(d):
        return set()
    return {f for f in os.listdir(d) if os.path.splitext(f)[1] in exts}


def test_no_track_shadows_a_shared_header():
    """A per-track file may not take a shared file's name.

    This is the failure that has no symptom. `#include "frame.h"`
    resolves against the include path, so a copy in a track's own folder
    silently wins there and the shared one keeps being compiled
    elsewhere - two definitions of one wire format, no error, and a
    divergence that shows up as a host parsing a frame wrongly.
    """
    shared = _names(SHARED, {".h"})
    assert shared, f"no shared headers found in {SHARED}"

    clashes = []
    for d in TRACK_DIRS:
        for name in sorted(_names(d, {".h"}) & shared):
            clashes.append(os.path.relpath(os.path.join(d, name), REPO))

    assert not clashes, (
        "these per-track headers shadow a shared one in "
        "lib/due_shared/src: " + ", ".join(clashes) + ". An include "
        "resolves to whichever the path reaches first, so the two copies "
        "drift with no diagnostic - which is what docs/shared-source.md "
        "exists to stop. Move the contract into the shared header, or "
        "rename the per-track file if it is genuinely something else.")


def test_track_id_is_the_only_per_track_duplicate():
    """`FW_TRACK` is the one fact that is legitimately per-track.

    Both tracks carry a `track_id.h` and they differ by one character.
    That is the exception the boundary is drawn around, so it is named
    here: if a second duplicated basename appears across the two tracks'
    own folders, it wants a reason.
    """
    b = _names(os.path.join(REPO, "drivers"), {".h"})
    a = _names(os.path.join(REPO, "sketches", "bringup"), {".h"})

    both = b & a
    # acq.h, play.h, stream.h and friends exist on both tracks and are
    # genuinely different code - the hardware halves this project keeps
    # independent on purpose. What must not appear is a *contract*
    # duplicated by hand, and track_id.h is the only sanctioned one.
    expected = {"acq.h", "play.h", "stream.h", "gen.h", "clock.h",
                "track_id.h"}
    surprises = sorted(both - expected)

    assert not surprises, (
        "these basenames now exist in both drivers/ and "
        "sketches/bringup/: " + ", ".join(surprises) + ". If they are "
        "two implementations of the same hardware, add them to the list "
        "in this test. If they are two copies of one contract, they "
        "belong in lib/due_shared/src - see docs/shared-source.md.")
