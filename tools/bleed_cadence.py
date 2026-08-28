"""Issue #16: is the A1-arm excursion random, or on a cadence?

`x` reports a distribution now, which was the fix for reporting one
draw. It raised a question a summary cannot answer: median and range
say *that* the quantity is spread, not whether the high observations
arrive at random, cluster, or recur. Those are three different defects
and #5 was got wrong by not separating them.

So `x` prints its observations in order, and this drives it at several
settle times and reads the gaps between the high ones. The cadence is
the discriminator:

  - a gap that stays the same when the settle time changes is a count
    kept somewhere in software;
  - a gap that scales so that gap x observation-duration is constant is
    a beat against something periodic in wall-clock time, and that
    product is its period.

Track A's delay() snaps each wait to the SysTick millisecond, so its
observation duration is an exact number of milliseconds and the beat
locks cleanly. Track B waits on micros(), so the same disturbance
aliases irregularly there - the effect is not weaker, the sampling is
just not commensurate. Do not read a scattered Track B gap list as a
different phenomenon; compare amplitudes and arms, which do agree.

The control arm is the other half. It writes the same DAC code twice
where the real arm swings it, so everything but the swing is identical:
a hit there would mean the excursion is not crosstalk at all.

Runs against either track, needs no instrument, and touches nothing but
the console.
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
import measure                                            # noqa: E402

VALUES = re.compile(r"# (A\d) (bleed|control), in order:((?: [+-]\d+)+)")

# The watched channel is whichever `C` selected - A1 by default, A2 with
# `=2C` - so the arm names are read out of the output rather than
# assumed. Labelling an A2 figure "A1" is the class of error issue #16
# is about, and a tool that hardcodes the name reintroduces it one layer
# up.
WATCHED = "watched"
ARMS = (WATCHED + " bleed", WATCHED + " control",
        "A0 bleed", "A0 control")

# A hit is an excursion, not scatter: every quiet observation measured
# on either track sits inside +-11 codes and every loud one above +150.
# Nothing has ever landed between 50 and 150 except the edge samples the
# threshold is meant to catch, so the exact value does not matter.
HIT_CODES = 50


def one_run(board, n, ms):
    """One invocation, keyed by role rather than by channel name.

    Returns the four arms as "watched bleed", "watched control",
    "A0 bleed", "A0 control", plus the channel name that was actually
    watched. A0 is the second-converted channel in every pairing and is
    the one arm whose name is fixed.
    """
    board.poll_console()
    board.cmd("=%d,%dx" % (n, ms))
    out = board.drain_console(90.0, until="Full swing")
    got, watched = {}, None
    for m in VALUES.finditer(out):
        ch, role, vals = m.group(1), m.group(2), m.group(3)
        key = ch + " " + role
        if ch != "A0":
            watched = ch
            key = WATCHED + " " + role
        got[key] = [int(v) for v in vals.split()]
    if not all(a in got for a in ARMS):
        return None
    got["_watched"] = watched
    return got


def gaps_of(vals):
    """Positions of the loud observations, and the gaps between them.

    By magnitude, not by sign. The driven channel excurses positive and
    the bare one negative - A2 reads a median of -90 codes on Track B -
    and a threshold that only looks upward finds nothing on the arm
    where the effect is largest.
    """
    hits = [i for i, v in enumerate(vals) if abs(v) > HIT_CODES]
    return hits, [b - a for a, b in zip(hits, hits[1:])]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settle", default="2,4,5,8,10,20",
                    help="settle times in ms, comma separated")
    ap.add_argument("--rounds", type=int, default=4,
                    help="passes over the settle list; each pass is "
                         "reversed against the last, so the die warming "
                         "cancels inside a pair")
    ap.add_argument("--n", type=int, default=15,
                    help="observations per invocation (CTL_BLEED_MAX)")
    ap.add_argument("--json", default=None, help="append rows here")
    args = ap.parse_args()

    settles = [int(s) for s in args.settle.split(",")]
    board = measure.Board(settle=3.0)
    board.stop()
    board.drain_console(0.5)

    rows = []
    order = []
    for r in range(args.rounds):
        order += settles if r % 2 == 0 else list(reversed(settles))
    for ms in order:
        got = one_run(board, args.n, ms)
        if got is None:
            print("ms=%-3d no parse - is this build carrying the ordered "
                  "values?" % ms)
            continue
        hits, gaps = gaps_of(got[WATCHED + " bleed"])
        rows.append({"settle_ms": ms, "n": args.n,
                     "watched": got["_watched"],
                     "hits": hits, "gaps": gaps,
                     "values": {a: got[a] for a in ARMS}})
        print("ms=%-3d %s hits@%-22s %s"
              % (ms, got["_watched"], hits, got[WATCHED + " bleed"]))

    print()
    print("ms   runs  obs  hits    %%   gaps        gap x duration"
          "   other arms")
    for ms in settles:
        mine = [r for r in rows if r["settle_ms"] == ms]
        if not mine:
            continue
        obs = sum(len(r["values"][WATCHED + " bleed"]) for r in mine)
        hits = sum(len(r["hits"]) for r in mine)
        gaps = collections.Counter(g for r in mine for g in r["gaps"])
        # Eight settle waits per observation on both tracks: two per arm,
        # four arms. Overhead is conversions and DAC writes, microseconds.
        dur = 8 * ms
        prod = sorted({g * dur for g in gaps})
        other = sum(1 for r in mine for a in ARMS[1:]
                    for v in r["values"][a] if abs(v) > HIT_CODES)
        rate = 100.0 * hits / obs if obs else 0.0
        # A standing offset is not a cadence, and the gap table cannot
        # tell you which it is looking at. A bare channel is loud on
        # nearly every observation - `=2C` here reads a permanent +95 -
        # so the gaps collapse to 1 and would read as "period 1" rather
        # than "no period at all". Say so instead of tabulating it.
        note = "  <- standing offset, not a cadence" if rate > 80 else ""
        print("%-4d %4d %4d %5d %4.0f   %-11s %-15s %d%s"
              % (ms, len(mine), obs, hits, rate,
                 sorted(gaps.items()), prod or "-", other, note))

    print()
    print("gap x duration is in ms. A single period dividing every one of "
          "them is the\ndisturbance; a column that does not settle on one "
          "means the sampling is not\ncommensurate with it, which is the "
          "expected Track B result - see the docstring.")
    if any(r["hits"] for r in rows):
        loud = [v for r in rows for v in r["values"][WATCHED + " bleed"]
                if abs(v) > HIT_CODES]
        print("excursion amplitude: %d observations, %d..%d codes"
              % (len(loud), min(loud), max(loud)))

    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print("appended %d rows to %s" % (len(rows), args.json))


main()
