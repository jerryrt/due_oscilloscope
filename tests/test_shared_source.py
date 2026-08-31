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
        assert "play_report_print(" in text, (
            f"Track {track} does not call play_report_print()")
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
    # The fields used to be `name=%lu` inside a printf format string.
    # Issue #49 replaced the formatter with emitters, so the shared
    # prefix is now a con_kv_u32("name", v) per field and a track's own
    # trailing fields are con_str(" name=") followed by the value. The
    # property under test is unchanged - order in the shared prefix,
    # append-only per track, no overlap - so only these two patterns
    # move.
    shared = re.findall(r'con_kv_u32\("([A-Za-z][A-Za-z0-9_-]*)"',
                        _read(PLAY_REPORT_C))
    assert shared[0] == "in" and "svc" in shared, shared

    for track, path in PLAY_LINE_CALLERS.items():
        text = _read(path)
        # Whatever this track appends after the shared prefix - which is
        # literally "between play_report_print() and the con_nl() that
        # ends the line", so read exactly that window rather than the
        # whole file. `con_str(" name=")` is a common enough shape that a
        # file-wide scan picks up unrelated register dumps.
        call = text.find("play_report_print(")
        assert call >= 0, f"Track {track} does not call play_report_print()"
        end = text.find("con_nl()", call)
        assert end > call, (
            f"Track {track} calls play_report_print() but never ends the "
            f"line with con_nl()")
        extra = re.findall(r'con_str\("\s+([A-Za-z][A-Za-z0-9_-]*)="\)',
                           text[call:end])
        assert extra == PLAY_TRACK_ONLY[track], (
            f"Track {track} appends {extra} to the `# play:` line; "
            f"declared {PLAY_TRACK_ONLY[track]}. Add it here with a "
            f"reason the other track cannot have it, or move it into "
            f"the shared prefix in play_report.c.")
        assert not (set(extra) & set(shared)), (
            f"Track {track} re-prints a shared field: "
            f"{sorted(set(extra) & set(shared))}")


# ------------------------------------------- the wire values the host matches

def test_the_host_channel_tags_match_the_firmware():
    """The third home for one wire fact, and the only one outside C.

    Every sample carries its channel index and the frame header carries
    `channel_mask` over the same indices, so these numbers are what the
    host demultiplexes by. They were written down three times - twice in
    firmware, which `frame.h` now holds in one place, and once in
    `host/measure.py`, which cannot include a C header.

    That third copy is why this is a test rather than a `#define`. A
    firmware change to a tag value would leave the host matching the old
    one and every capture would demultiplex into the wrong channel -
    silently, because a tag that matches nothing produces an empty
    series rather than an error.

    They are not obvious numbers: Arduino's A0..A7 map to ADC channels
    in descending order, so A0 is AD7. Code assuming A0 == AD0 reads the
    wrong pin, which is why the table travels with the values.
    """
    import re
    import sys

    frame_h = _read(os.path.join(SHARED, "frame.h"))
    fw = {}
    for name in ("A0", "A1", "A2"):
        m = re.search(rf"#define\s+FRAME_CH_{name}\s+(\d+)u", frame_h)
        assert m, f"frame.h no longer defines FRAME_CH_{name}"
        fw[name] = int(m.group(1))

    sys.path.insert(0, os.path.join(REPO, "host"))
    import measure

    host = {"A0": measure.CH_A0, "A1": measure.CH_A1, "A2": measure.CH_A2}
    assert host == fw, (
        f"host/measure.py matches channel tags {host} while the firmware "
        f"sends {fw}. Captures would demultiplex into the wrong channel, "
        f"and a tag matching nothing gives an empty series rather than "
        f"an error")


def test_the_channel_tags_are_not_written_out_twice_in_firmware():
    """Neither track may define the tag values again.

    `drivers/analog.h` and `sketches/bringup/acq.h` each carried the
    literals 7, 6 and 5. Both now spell them from `FRAME_CH_*`, and a
    track that writes a number back is the drift this seam exists to
    stop.
    """
    import re
    for rel in ("drivers/analog.h", os.path.join("sketches", "bringup",
                                                 "acq.h")):
        text = _read(rel)
        bad = re.findall(r"#define\s+(?:ADC|ACQ)_CH_A[012]\s+(\d+)u", text)
        assert not bad, (
            f"{rel} defines a channel tag as a literal again ({bad}); it "
            f"must come from FRAME_CH_* so the wire value has one home")


def test_the_identity_line_has_one_format_string():
    """`# id:` is what a host refuses a pairing on, so it is wire contract.

    It was built twice - `printf(FW_ID_FORMAT ...)` in Track B's main.c
    and `snprintf` plus `Serial.println` in Track A's sketch - identical
    argument for argument, differing only in how the line reached the
    wire. Ten arguments in one order, maintained in two places, feeding
    `measure.parse_identity` and every pairing check.

    `FW_VERSION_STR` disagreeing with `FW_VERSION_MAJOR/MINOR/PATCH` is
    the precedent: the same value written twice, wrong identically on
    both tracks, so a board answered "which firmware are you" two ways
    and copying kept the copies in perfect agreement at the wrong value.
    """
    # This asserted on the name FW_ID_FORMAT until issue #49, when the
    # printf format string became a sequence of emitter calls and the
    # macro was deleted rather than left behind - an uncompiled, untested
    # copy of a wire format is the second home this seam exists to
    # prevent. It now asserts on the wire text itself, which is both
    # stronger and the same shape as the `# play:` check above.
    shared = _read(os.path.join(SHARED, "console.c"))
    assert "# id: track=" in shared, (
        "console.c no longer builds the identity line; the tracks have "
        "taken it back")

    for track, rel in (("B", os.path.join("apps", "baremetal_bringup",
                                          "main.c")),
                       ("A", os.path.join("sketches", "bringup",
                                          "bringup.ino"))):
        text = _read(rel)
        assert "# id: track=" not in text and "FW_ID_FORMAT" not in text, (
            f"Track {track} ({rel}) builds the identity line again. It "
            f"is built by console_identity(); a second copy is a second "
            f"home for the field order that measure.parse_identity "
            f"depends on")
        assert "console_identity(" in text, (
            f"Track {track} does not call console_identity()")


#: Handler bodies that have moved into lib/due_shared/src/console_cmds.c.
#: A track defining one again is the duplication coming back.
MOVED_HANDLER_BODIES = ("trigger_fault", "gen_report")


def test_moved_handler_bodies_do_not_come_back_per_track():
    """Issue #45's C-share, held open.

    Measured before any of it moved, because "the handlers are
    duplicated" was true and not specific enough to plan from. Of 48
    handlers per track - and all 48 share a command letter - 17 have a
    paired named body. Four of those program registers directly
    (`cmd_crosstalk`, `cmd_profile`, `cmd_rate_sweep`, `measure_gpio`)
    and stay per track, which is invariant 3 working rather than
    failing. The other 13 touch no register at all: 269 lines on Track B
    and 260 on Track A, about 529 lines expressing one logic.

    So the boundary is drawn by what a body *does*, not by taste, and
    this pins the ones that have crossed it.
    """
    shared = _read(PLAY_REPORT_C.replace("play_report.c", "console_cmds.c"))
    for name in MOVED_HANDLER_BODIES:
        assert f"console_{name}(" in shared, (
            f"console_cmds.c no longer defines console_{name}()")

    for track, rel in (("B", os.path.join("apps", "baremetal_bringup",
                                          "main.c")),
                       ("A", os.path.join("sketches", "bringup",
                                          "bringup.ino"))):
        text = _read(rel)
        for name in MOVED_HANDLER_BODIES:
            import re
            assert not re.search(rf"^static \w+ {name}\s*\(", text, re.M), (
                f"Track {track} defines {name}() again; it lives in "
                f"console_cmds.c and a second definition is the "
                f"duplication this seam removed")
            assert f"console_{name}(" in text, (
                f"Track {track} does not call console_{name}()")


def test_register_touching_bodies_stay_per_track():
    """The other half of the boundary, and the more important one.

    `cmd_crosstalk` alone is 183 lines with direct ADC and DACC access
    on both tracks. Moving it would buy tidiness with exactly what
    invariant 3 protects: two independent programmings of one
    peripheral is what makes a behavioural divergence point at one of
    them. This fails if one is ever moved into the shared library.
    """
    import re

    def code_only(text):
        """Strings and comments are not register access.

        The console's own help table contains "full loop
        HOST->DAC->ADC->HOST", which a naive substring search reads as
        an ADC access. A guard that cries wolf on its own help text is
        one people learn to switch off.
        """
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"//[^\n]*", " ", text)
        text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
        return text

    for f in sorted(os.listdir(SHARED)):
        if not f.endswith(".c"):
            continue
        text = code_only(_read(os.path.join("lib", "due_shared", "src", f)))
        for reg in ("ADC->", "DACC->", "UOTGHS->", "PIOB->", "PMC->",
                    "REG_ADC", "REG_DACC"):
            assert reg not in text, (
                f"lib/due_shared/src/{f} touches {reg}. Register "
                f"programming stays per track - two independent "
                f"programmings of one peripheral is what makes a "
                f"behavioural divergence point at one of them")


def test_the_console_seam_is_pinned_like_the_stream_seam():
    """The rescoped console_port.h is only safe because this exists.

    `console_port.h` used to say "two functions, and no more". Issue
    #45 rescoped it to "a record of exactly what the shared code calls",
    which is a better rule *and* a weaker one until something checks it:
    a size limit needs no test, and a record does.

    So the console gets the same check `stream_port.h` has had since
    issue #14, through the same code rather than a second copy of it -
    a parallel `console_seam.py` would have been the duplication #45
    exists to remove.
    """
    ss = _stream_seam()
    assert "console" in ss.SEAMS, (
        "the console seam is no longer registered; console_port.h is "
        "back to being unchecked")
    drift = ss.core_check(seam="console")
    assert not drift, "\n".join(drift)


def test_the_console_seam_check_can_fail(tmp_path):
    """A check that cannot fail is decoration.

    Proven in both directions, the way #14 step 2 proved the stream
    one: a port that declares something nothing calls, and shared code
    reaching a name the port does not declare.
    """
    ss = _stream_seam()
    port = ss._strip(ss._read(ss.SEAMS["console"]["port"]))

    padded = port.replace("void console_flush(void);",
                          "void console_flush(void);\n"
                          "void console_nobody_calls_this(void);")
    drift = ss.core_check(padded, seam="console")
    assert any("nobody_calls_this" in d for d in drift), (
        f"a port declaring an unused name did not register as drift: "
        f"{drift}")

    cut = port.replace("void console_write(const char *s);", "")
    drift = ss.core_check(cut, seam="console")
    assert any("console_write" in d for d in drift), (
        f"removing console_write from the port did not register as "
        f"drift, though the shared console calls it: {drift}")


def test_the_extractor_ignores_indirect_calls():
    """Calls through a pointer are not seam surface.

    Three shapes appear in the shared console and none is an external
    dependency: a cast through a function pointer
    (`(void (*)(void))addr`), a local function pointer (`bad()`), and a
    variable whose type is a function-pointer typedef (`console_fn fn;`
    then `fn(arg)`). Each one asked the port header to declare something
    it never could, so the seam could not go green until the extractor
    learned them.
    """
    ss = _stream_seam()
    src = """
    typedef void (*thing_fn)(int);
    void f(void) {
        void (*bad)(void) = (void (*)(void))0x20000000;
        thing_fn fn = pick();
        bad(); fn(1); real_call();
    }
    """
    names = ss.called_names(src, ss.fnptr_typedefs(src))
    assert "real_call" in names and "pick" in names
    for indirect in ("bad", "fn", "void"):
        assert indirect not in names, (
            f"{indirect!r} was read as an external call; it is an "
            f"indirect call or a cast")
