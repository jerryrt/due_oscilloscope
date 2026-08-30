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

    # And the residue is what steps 3 and 4 left per track: framer and
    # bench policy moved to the shared files, so what remains is each
    # track's stream_port implementations and the reports - the raw
    # DMA status read the out_done decode wraps, and the acq counters
    # the reports read directly.
    a, b = ss.seam(ss.SOURCES["a"]), ss.seam(ss.SOURCES["b"])
    assert "usb_dma_out_status" in a and "usb_dma_out_status" in b
    assert "acq_produced" in a and "acq_produced" in b
    assert "acq_start" not in a and "acq_start" not in b  # framer's now
    assert "usbdma_keepalive" in a      # Track A repairs the core's reset
    assert "usb_cdc_write" in b         # Track B's transport shim


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
    removed.write_text(
        "\n".join(l for l in good if "usb_dma_out_status" not in l) + "\n")
    drift = ss.check(str(removed))
    assert any("usb_dma_out_status" in d and "extracted but not pinned" in d
               for d in drift), drift

    empty = tmp_path / "empty.list"
    empty.write_text("# nothing\n")
    assert ss.check(str(empty)), "an empty pinned list passed the check"

    missing = tmp_path / "does-not-exist.list"
    assert ss.check(str(missing)), "a missing pinned list passed the check"


def test_a_wrong_stream_port_header_fails_the_check(tmp_path):
    """The core/port drift check can fail, proven both ways.

    Same argument as the pinned-list tamper test: without this, a
    check whose extraction silently broke would report that
    stream_port.h and stream_core.c agree when nothing was compared.
    """
    ss = _stream_seam()

    # The real pair agrees.
    assert ss.core_check() == []

    real = open(os.path.join(REPO, ss.PORT)).read()

    # A declaration nothing uses must be flagged.
    padded = ss._strip(real + "\nvoid stream_port_never_called(void);\n")
    drift = ss.core_check(padded)
    assert any("stream_port_never_called" in d and "uses" in d
               for d in drift), drift

    # Removing a declaration the core does use must be flagged.
    cut = ss._strip(real.replace("bool     usb_dma_in_busy(void);", ""))
    drift = ss.core_check(cut)
    assert any("usb_dma_in_busy" in d and "no shared header declares" in d
               for d in drift), drift


# --------------------------------------------- console lines the host parses

#: The one file allowed to hold the `# play:` format string.
PLAY_REPORT_C = os.path.join(SHARED, "play_report.c")

#: The two call sites that print it.
PLAY_LINE_CALLERS = {
    "B": os.path.join(REPO, "apps", "baremetal_bringup", "main.c"),
    "A": os.path.join(REPO, "sketches", "bringup", "bringup.ino"),
}

#: Counters only one track can keep, appended after the shared prefix.
#: Track A's are its UOTGHS DMA stack; Track B has nothing to put there.
PLAY_TRACK_ONLY = {"A": ["rebuilds", "act-in", "act-out"], "B": []}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_the_play_line_has_exactly_one_home():
    """`# play:` is surface, so it is written once.

    Issue #13's split - the surface is shared, the handlers are not -
    applied to a status line. The counters behind these fields are each
    track's own and stay two independent programmings, which invariant 3
    requires. The line is application formatting and was written twice
    by hand, and it had already drifted: Track A printed `svc` between
    `endtx` and `spans` while Track B printed no `svc` at all, though
    `play_svc_calls` is counted in `drivers/play.c` and was already
    going out over its control channel. Every field after `endtx` sat
    one position out between the tracks, and `tools/bench.py` read one
    track's line into the other's columns and reported an unread counter
    as a 100%% byte deficit.

    Two copies agreeing today is not the property worth testing. One
    copy is.
    """
    assert "# play:" in _read(PLAY_REPORT_C), (
        "the shared formatter no longer holds the `# play:` format "
        "string; the tracks have taken it back")
    for track, path in PLAY_LINE_CALLERS.items():
        assert "# play:" not in _read(path), (
            f"Track {track} ({os.path.relpath(path, REPO)}) writes its own "
            f"`# play:` format string again. That is the second copy this "
            f"seam exists to prevent - build it from "
            f"play_report_format() and append only what this track alone "
            f"can count.")


def test_both_tracks_reach_the_line_through_the_shared_formatter():
    for track, path in PLAY_LINE_CALLERS.items():
        text = _read(path)
        assert "play_report_format(" in text, (
            f"Track {track} does not call play_report_format()")
        assert '#include "play_report.h"' in text, (
            f"Track {track} does not include play_report.h")


def test_track_specific_play_counters_only_trail():
    """A per-track counter is appended, never interleaved.

    A positional reader then degrades to "the fields I know" instead of
    silently reading the wrong column, and a new field on one track
    fails this until someone has said which track it belongs to and
    why the other cannot have it.
    """
    import re
    shared = re.findall(r"([A-Za-z][A-Za-z0-9_-]*)=%lu", _read(PLAY_REPORT_C))
    assert shared[0] == "in" and "svc" in shared, shared

    for track, path in PLAY_LINE_CALLERS.items():
        text = _read(path)
        # Whatever this track appends after the shared prefix.
        extra = []
        for m in re.finditer(r'"\s+((?:[A-Za-z][A-Za-z0-9_-]*=%lu\s*)+)"', text):
            extra += re.findall(r"([A-Za-z][A-Za-z0-9_-]*)=%lu", m.group(1))
        assert extra == PLAY_TRACK_ONLY[track], (
            f"Track {track} appends {extra} to the `# play:` line; "
            f"declared {PLAY_TRACK_ONLY[track]}. Add it here with a "
            f"reason the other track cannot have it, or move it into "
            f"the shared prefix in play_report.c.")
        assert not (set(extra) & set(shared)), (
            f"Track {track} re-prints a shared field: "
            f"{sorted(set(extra) & set(shared))}")
