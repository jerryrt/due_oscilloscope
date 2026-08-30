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

#: (label, path, how the banner is emitted). Both tracks, because
#: invariant 3 wants one decision here and not two: the fix landed on
#: both in one change and it has to stay that way, or the oracle carries
#: a defect the project keeps it to detect.
SITES = [
    ("track B", os.path.join("apps", "baremetal_bringup", "main.c"),
     r'printf\("# streaming:'),
    ("track A", os.path.join("sketches", "bringup", "bringup.ino"),
     r'"# streaming:'),
]


def _cmd_stream(path):
    """The body of cmd_stream, from its opening brace to the matching one."""
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"static void cmd_stream\(uint32_t trigger_hz\)\s*\{", text)
    assert m, f"cmd_stream not found in {path}"
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += (text[i] == "{") - (text[i] == "}")
        i += 1
    return text[m.end():i]


@pytest.mark.parametrize("label,path,banner", SITES,
                         ids=[s[0] for s in SITES])
def test_the_banner_is_printed_before_the_capture_starts(label, path, banner):
    body = _cmd_stream(path)

    at_banner = re.search(banner, body)
    at_start = re.search(r"stream_start\(trigger_hz\)", body)
    assert at_banner, f"{label}: no streaming banner in cmd_stream"
    assert at_start, f"{label}: cmd_stream no longer calls stream_start"

    assert at_banner.start() < at_start.start(), (
        f"{label} ({path}): cmd_stream starts the capture before it "
        f"prints its banner. That is issue #41 - the print costs 13-20 ms "
        f"of blocked main loop against 8.96 ms of ring runway at "
        f"453,488 Hz, so the frames that arrive during it are lost before "
        f"the host sees any. See docs/debugging.md.")


@pytest.mark.parametrize("label,path,banner", SITES,
                         ids=[s[0] for s in SITES])
def test_the_refusal_still_follows_the_start(label, path, banner):
    """The banner moving up must not take the refusal with it.

    A refusal is only knowable from `stream_start`'s return, so it has to
    stay after it. Asserting only "banner before start" would be
    satisfied by a version that also announced a refusal it had not yet
    had - which would be a worse defect than the one being fixed, and a
    silent one, because the host reads success as the *absence* of
    "refused".
    """
    body = _cmd_stream(path)
    at_start = re.search(r"stream_start\(trigger_hz\)", body)
    at_refusal = re.search(r"# refused:", body)
    assert at_refusal, f"{label}: cmd_stream no longer reports a refusal"
    assert at_start.start() < at_refusal.start(), (
        f"{label} ({path}): the refusal is printed before the start whose "
        f"return decides it, so the device would announce a refusal it "
        f"has not had. Success is read as the absence of that word.")
