"""The stream banner is printed before the capture is started.

Issue #41. Capture is device-driven - the ring fills from the moment the
timer runs - so a console line between the start and the first drain is
spent out of the ring's runway. Invariant 8 prices a line at 13-20 ms of
blocked main loop, `cmd_stream`'s banner measures 17.9-20.2 ms, and the
ring holds 8.96 ms at 453,488 Hz. Printing after the start lost exactly
3 frames, on three benches and three hosts, before the host ever saw a
byte.

**This is a source-shape test on purpose, and it is the cheap half of
the cover.** `test_startup_frames.py` catches the *effect* and is worth
more, but it needs a board, it only bites above 200 kHz, and it can only
speak for whichever track that board is flashed with. Reordering these
two statements back on the track nobody happened to be running would
reintroduce the defect and pass every board-free run. So: both tracks,
no hardware, on the ordering itself.

The pattern is `test_clean_build.py`'s - assert the shape of the source
where the property lives in the source rather than in a value - and it
carries the same caveat: it can only see what it can match, so it is a
guard against an accidental reorder, not against a rewrite.
"""

import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRACKS = [
    ("track B", os.path.join("apps", "baremetal_bringup", "main.c")),
    ("track A", os.path.join("sketches", "bringup", "bringup.ino")),
]

#: (handler, signature, banner, the capture start, the refusal it guards).
#:
#: Both handlers, because the audit in docs/debugging.md priced the class
#: and the first fix went to one instance: `h_loop` was listed at margin
#: -5.89 ms and left unfixed for a day while `cmd_stream` was covered by
#: this very file. A per-site test that only knows about the site someone
#: happened to fix reproduces exactly that gap.
SHARED = os.path.join("lib", "due_shared", "src", "console_cmds.c")

#: (handler, where it lives, signature, banner, start, refusal).
#:
#: `cmd_stream` has ONE site now. Issue #45 moved the body into
#: `lib/due_shared/src/console_cmds.c` as `console_cmd_stream()`, so
#: what this file was asking for - "one decision here and not two" - is
#: now true by construction rather than by a test noticing when it
#: stopped being. The guard is kept and pointed at the one home: the
#: ordering is still a source property, and a rewrite of the shared body
#: can still get it wrong once for both tracks.
#:
#: `loop` is still two sites and still needs both. It was listed at
#: margin -5.89 ms in docs/debugging.md's class audit and fixed per
#: track, which is exactly the gap this file was written to close.
HANDLERS = [
    ("cmd_stream", [("shared", SHARED)],
     r"void console_cmd_stream\(uint32_t trigger_hz\)\s*\{",
     r'"# streaming:',
     r"console_port_stream_start\(trigger_hz\)", r"# refused:"),
    # The two `loop` patterns must match BOTH dialects, because Track B
    # emits with con_* (issue #49) while Track A still uses a printf
    # format string, and they must stay **banner-specific**: h_loop also
    # says "# loop: DAC ... sps refused" earlier in the same body, and a
    # pattern loose enough to match that would find its "banner" before
    # the start unconditionally and pass for the wrong reason.
    #
    # So the text matched is the part only the banner has.
    ("loop", TRACKS,
     r"static void h?a?_?loop\(const uint32_t \*a\)\s*\{",
     r"sps from USB, ADC ",
     r"stream_start_capture_only\(adc_hz, nch\)",
     r"# loop: ADC "),
]

SITES = [(f"{h} {where}", path, sig, banner, start, refusal)
         for (h, places, sig, banner, start, refusal) in HANDLERS
         for (where, path) in places]


def _body(path, signature):
    """One function body, from its opening brace to the matching one."""
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        text = f.read()
    m = re.search(signature, text)
    assert m, f"{signature} not found in {path}"
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    return text[m.end():i]


@pytest.mark.parametrize("label,path,sig,banner,start,refusal", SITES,
                         ids=[s[0] for s in SITES])
def test_the_banner_is_printed_before_the_capture_starts(
        label, path, sig, banner, start, refusal):
    body = _body(path, sig)

    at_banner = re.search(banner, body)
    at_start = re.search(start, body)
    assert at_banner, f"{label}: no banner found"
    assert at_start, f"{label}: no longer starts the capture"

    assert at_banner.start() < at_start.start(), (
        f"{label} ({path}): the capture starts before the banner "
        f"is printed. That is issue #41 - the print costs 13-20 ms "
        f"of blocked main loop against 8.96 ms of ring runway at "
        f"453,488 Hz, so the frames that arrive during it are lost before "
        f"the host sees any. See docs/debugging.md.")


@pytest.mark.parametrize("label,path,sig,banner,start,refusal", SITES,
                         ids=[s[0] for s in SITES])
def test_the_refusal_still_follows_the_start(
        label, path, sig, banner, start, refusal):
    """The banner moving up must not take the refusal with it.

    A refusal is only knowable from `stream_start`'s return, so it has to
    stay after it. Asserting only "banner before start" would be
    satisfied by a version that also announced a refusal it had not yet
    had - which would be a worse defect than the one being fixed, and a
    silent one, because the host reads success as the *absence* of
    "refused".
    """
    body = _body(path, sig)
    at_start = re.search(start, body)
    at_refusal = re.search(refusal, body)
    assert at_refusal, f"{label}: no longer reports a refusal"
    assert at_start.start() < at_refusal.start(), (
        f"{label} ({path}): the refusal is printed before the start whose "
        f"return decides it, so the device would announce a refusal it "
        f"has not had. Success is read as the absence of that word.")
