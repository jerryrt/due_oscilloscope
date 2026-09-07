"""Long comment blocks in the firmware, held where they are.

A comment:code ratio is not a target the firmware can meet without
cutting the blocks `docs/writing.md` protects - the ISR-priority warning
in `apps/rtos_bringup/time_rtos.c`, the byte-budget table in
`lib/due_shared/src/console_out.h`, the `DEVEPTCFG` re-allocation trap.
What can be held is the count: every firmware file carries a known
number of comment blocks of `LONG` lines or more, recorded in
`comment_blocks.json`, and this test fails when a file's count moves in
either direction.

Up is the case it exists for. A new long block lands only with a bump
to the baseline in the same commit, which puts the reason for the block
in a commit body `git log` keeps. Down is failed too, so the baseline
can never sit above the tree: a stale-high count is exactly the slack a
new block slips through when an old one goes in the same change.

A block is one `/* ... */` comment, or one unbroken run of `//` lines,
measured in source lines. The threshold is 20, four above the length
that reaches the protected blocks.

Needs no board.
"""
import json
import os
import re

import pytest

from test_comment_style import _c_comment_spans, _line_of, _prune_dir, _read

pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "comment_blocks.json")

#: Firmware: everything a track compiles into an image.
FIRMWARE_DIRS = [
    "drivers",
    "bsp",
    "apps",
    os.path.join("lib", "due_shared", "src"),
    os.path.join("sketches", "bringup"),
]
C_EXTS = {".c", ".h", ".cpp", ".ino"}

#: Lines. A block this long or longer is counted.
LONG = 20


def _blocks(text):
    """(first line, line count) for every comment block in a C source.

    A `/* */` comment is one block however many lines it spans. `//`
    comments merge with the `//` comment on the line directly above,
    so a stacked run of them is one block, and a blank line or a line
    of code ends it.
    """
    out = []
    run_start = run_last = None
    for start, span in sorted(_c_comment_spans(text)):
        first = _line_of(text, start)
        if span.startswith("/*"):
            if run_start is not None:
                out.append((run_start, run_last - run_start + 1))
                run_start = run_last = None
            out.append((first, span.count("\n") + 1))
            continue
        if run_start is not None and first == run_last + 1:
            run_last = first
        else:
            if run_start is not None:
                out.append((run_start, run_last - run_start + 1))
            run_start = run_last = first
    if run_start is not None:
        out.append((run_start, run_last - run_start + 1))
    return out


def _long_blocks(path):
    return [(ln, n) for ln, n in _blocks(_read(path)) if n >= LONG]


def _scan():
    """{relative path: [(line, length)]} for every long block in firmware."""
    found = {}
    for d in FIRMWARE_DIRS:
        root_dir = os.path.join(REPO, d)
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [sub for sub in dirs if not _prune_dir(sub)]
            for fn in sorted(files):
                if os.path.splitext(fn)[1] not in C_EXTS:
                    continue
                path = os.path.join(root, fn)
                longs = _long_blocks(path)
                if longs:
                    rel = os.path.relpath(path, REPO).replace(os.sep, "/")
                    found[rel] = longs
    return found


def _baseline():
    with open(BASELINE, encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_block_scanner_measures_lines():
    """Positive control for the scanner, on both comment shapes.

    A block comment is its line span; a run of `//` lines is one block
    and a blank line splits it. Get either wrong and the ratchet holds
    a number about the scanner rather than about the tree.
    """
    text = ("/* one\n" + " * two\n" * 18 + " */\n"
            "int x;\n"
            + "// a\n" * 20 + "\n" + "// b\n" * 5
            + "/* short */\n")
    got = _blocks(text)
    assert got == [(1, 20), (22, 20), (43, 5), (48, 1)], got


def test_long_blocks_match_the_baseline():
    """Every firmware file's count of long blocks is the recorded one."""
    found = {k: len(v) for k, v in _scan().items()}
    base = _baseline()
    drift = []
    for path in sorted(set(found) | set(base)):
        have, want = found.get(path, 0), base.get(path, 0)
        if have != want:
            where = ", ".join(f"{ln}({n})" for ln, n in _scan().get(path, []))
            drift.append(f"  {path}: {have} block(s) of >= {LONG} lines, "
                         f"baseline says {want}  [{where}]")
    assert not drift, (
        f"long comment blocks moved against tests/comment_blocks.json:\n"
        + "\n".join(drift) +
        f"\n\nA new block of {LONG}+ lines is a decision: either it is "
        "load-bearing, and the baseline entry is bumped in the same "
        "commit with the reason in the body, or it is shorter than "
        f"{LONG}. A count that fell is lowered in the baseline so the "
        "slack cannot be spent by the next block.")
