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


# ---------------------------------------------------------------------------
# Issue #14: the stream seam, pinned before anything moves.
#
# stream.c and stream.cpp are one file written twice, and the plan for
# sharing them starts by recording exactly what each copy reaches
# outside itself. tools/stream_seam.py extracts that list mechanically;
# tools/stream_seam.list pins it. The eventual stream_port.h must
# declare exactly the extracted seam, so drift between the pin and the
# source has to fail a run - in either direction.

def _stream_seam():
    import sys
    tools = os.path.join(REPO, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import stream_seam
    return stream_seam


def test_stream_seam_list_is_pinned_and_current():
    """The committed seam list equals a fresh extraction, exactly.

    A new call into acq/gen/the transport, a rename, or a dropped
    dependency all change the extraction, and each must fail here until
    `tools/stream_seam.py --write` re-pins it - the same run that
    introduced the change, not a later reader, notices.
    """
    ss = _stream_seam()
    drift = ss.check()
    assert not drift, "\n".join(drift)

    # And the seam itself is what issue #14 recorded: nonempty on both
    # tracks, acq/gen on both, each track's own transport names.
    a, b = ss.seam(ss.SOURCES["a"]), ss.seam(ss.SOURCES["b"])
    for names in (a, b):
        assert "acq_start" in names and "gen_start" in names
    assert "usb_dma_in_start" in a and "usb_dma_in_start" in b
    assert "usbdma_keepalive" in a      # Track A repairs the core's reset
    assert "usb_cdc_write" in b         # Track B's console shim


def test_a_wrong_seam_list_fails_the_check(tmp_path):
    """The check can fail, proven both ways - the deliverable of #14
    step 2.

    A generated-artifact check that silently stops extracting passes
    for ever and reports agreement where nothing was compared (the
    tools/report.py lesson, recorded on the issue). So: a pinned list
    with a name nothing calls must fail, a pinned list missing a name
    the source calls must fail, and an empty list must fail rather than
    vacuously pass.
    """
    ss = _stream_seam()
    good = [l for l in ss.render().splitlines() if not l.startswith("#")]

    added = tmp_path / "added.list"
    added.write_text("\n".join(good + ["b drivers/acq.h acq_nothing_calls_this"]) + "\n")
    drift = ss.check(str(added))
    assert any("acq_nothing_calls_this" in d and "pinned but not extracted" in d
               for d in drift), drift

    removed = tmp_path / "removed.list"
    removed.write_text("\n".join(l for l in good if "acq_start" not in l) + "\n")
    drift = ss.check(str(removed))
    assert any("acq_start" in d and "extracted but not pinned" in d
               for d in drift), drift

    empty = tmp_path / "empty.list"
    empty.write_text("# nothing\n")
    assert ss.check(str(empty)), "an empty pinned list passed the check"

    missing = tmp_path / "does-not-exist.list"
    assert ss.check(str(missing)), "a missing pinned list passed the check"
