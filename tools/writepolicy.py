#!/usr/bin/env python3
"""Is `Feeder.WRITE_SIZE` still a rule, and *why* is a constant one clean?

Two questions, one instrument. The first is re-validation and was the
reason this file exists; the second is objective 0j, and the arms that
answer it are the `--arms` flag.

The 0-series re-validation is the oldest debt this project carries, and
one half of it is a claim only this platform can test - `docs/usb.md`
owns the loss investigation and the evidence behind this:

    macOS loses 0.45-0.85% of what write() counted, at every rate above
    200 ksps, unless every write is the same size. A constant 512 bytes
    is lossless; "whatever is due" is not, even when every write it
    emits is 512 or 1024.

Everything about the feed is designed around that, and it has not been
re-read since the constant-size feed landed. `Feeder` still carries both
paths for exactly this comparison - `write_size=None` is the constant
size, `write_size=0` the legacy due-sized one - so the A/B costs nothing
but bench time.

    .venv/bin/python tools/writepolicy.py --rcs 195,98,65

Counterbalanced ABBA within each rate rather than swept: the host's byte
loss is intermittent and the die warms, so a block of one policy
followed by a block of the other compares the half-hour as much as the
policy. RC 44 and 39 are excluded by default - their converters run slow
and shed the surplus however it is written, so they cannot answer a
question about write policy.

## Objective 0j: the shape of the write stream, not its size

The recorded contradiction is sharp. A constant 512 B loses nothing. A
constant 1024 B loses nothing. A due-sized feed capped so it can only
ever emit 512 or 1024 loses 0.47-0.84%. Same sizes, same rate, same
pacing thread. So the mechanism is in *how* the writes are issued, and
three candidates survive that:

  H1  variation itself - the driver packs payloads into fixed-size
      internal buffers and a uniform stream stays aligned to them.
      Predicts `alt` loses.
  H2  a size threshold - only writes above some size lose, and the
      due-sized arm loses because MAX_WRITE lets it emit large ones.
      Predicts `alt` and `pair512` are both clean and the `due` arm's
      write histogram is dominated by writes over 1024 B.
  H3  cadence - the due-sized path polls on a 1 ms sleep and writes
      whatever accumulated, so its writes arrive bunched rather than
      evenly spaced. Predicts `pair512` loses and `alt` need not.

The arms are a 2x2 in {size uniform, size varying} x {cadence even,
cadence bunched}, plus the historical artifact as a positive control:

  const512   512 B, evenly paced                     uniform / even
  const1024  1024 B, evenly paced                    uniform / even
  pair512    two 512 B writes back to back, at the
             cadence a single 1024 B write would
             have had                                uniform / bunched
  alt        512, 1024, 512, 1024 ...                varying / even
  due        the legacy due-sized path               the positive control

`due` is not a matched arm and is not meant to be. It is the **positive
control**, and it is the artifact itself rather than a synthetic stand-in
for it: it is the arm measured on this bench on 2026-08-29 at
0.763-0.915% at 600,000 sps, 4 runs of 4. A null in `alt` or `pair512`
is worth exactly nothing unless `due` loses in the same session, at the
same rate, through the same drain - which is the whole reason it is in
every block rather than measured once at the start.

The shapes are built by wrapping the port the feeder writes to, so
`measure.Feeder`'s policy is read but never edited: `WRITE_SIZE` is a
settled workaround (issue #27) and an experiment that changes it is
measuring a different program. The wrapper also counts the sizes that
were actually issued, which is what separates H2 from the other two
without a second run.

    .venv/bin/python tools/writepolicy.py --arms shape --rcs 65 --rounds 5
"""
import argparse
import collections
import json
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402
import provenance  # noqa: E402

#: The legacy pair, which is what this file was written to compare.
#: `None` is `Feeder.WRITE_SIZE`, `0` the due-sized path.
ARMS = {"const": None, "due": 0}

#: The 0j arms. `first` is the size the feeder is armed with, `cycle`
#: the sizes it then rotates through, and `split` chops each write into
#: back-to-back pieces of that size without changing when it is issued.
SHAPES = {
    "const512":  {"first": 512,  "cycle": (512,),       "split": None},
    "const1024": {"first": 1024, "cycle": (1024,),      "split": None},
    # A constant that is not a power of two, and the size the due-sized
    # path emits most. If a constant size is clean because it is
    # constant this is clean; if it is clean because every write lands
    # on a boundary the driver also uses, this one does not.
    "const1536": {"first": 1536, "cycle": (1536,),      "split": None},
    # 2048 is the one constant that separates a 1 KiB internal boundary
    # from any larger one: it spans a 1 KiB boundary on every write and
    # a 2 KiB or 4 KiB boundary on none. 4096 spans 1 KiB and 2 KiB
    # boundaries and no 4 KiB one, so the pair reads the size off two
    # points rather than one.
    "const2048": {"first": 2048, "cycle": (2048,),      "split": None},
    "const4096": {"first": 4096, "cycle": (4096,),      "split": None},
    "pair512":   {"first": 1024, "cycle": (1024,),      "split": 512},
    "alt":       {"first": 512,  "cycle": (512, 1024),  "split": None},
    "due":       {"first": 0,    "cycle": None,         "split": None},
}

#: The due-sized path with the size counter fitted and nothing else -
#: what H2 needs, since it asks whether the legacy arm loses because of
#: the large writes MAX_WRITE lets it emit. `due` itself stays
#: unwrapped, so the pair is also a check on the wrapper: the artifact
#: reproduces without it and the clean arms stay clean with it.
SHAPES["duehist"] = dict(SHAPES["due"])

ARM_SETS = {
    "policy": ("const", "due"),
    "shape": ("const512", "const1024", "pair512", "alt", "due"),
    # Does the loss follow the number of size *transitions*? `altN`
    # writes N 512s then N 1024s, so the byte stream and the size set
    # are identical across the family and only the transition rate
    # changes - by 64x from end to end. A loss that is flat across it
    # is not counting transitions; one that falls with N is.
    "runlen": ("const512", "alt", "alt4", "alt16", "alt64", "due",
               "duehist"),
    # A run of N 512s then N 1024s spans a power-of-two boundary for
    # every odd N and for no even one - identically at 1 KiB and at
    # 16 KiB. So run length and byte alignment, which agree on N=1 and
    # N=4, disagree flatly here: alignment says 3 and 5 lose as much as
    # 1 does and 2 loses nothing, and run length says 2, 3 and 5 are all
    # clean.
    "parity": ("const512", "const1536", "alt", "alt2", "alt3", "alt5",
               "duehist"),
    # If the boundary is 1 KiB both of these lose; if it is 2 KiB only
    # 4096 does; if it is 4 KiB neither does.
    "boundary": ("const512", "const2048", "const4096", "duehist"),
}

# --- the second rate -------------------------------------------------------
#
# EVERY 0j FIGURE IS ONE RATE, 600,000 sps, and a rule measured at one
# point on an axis is a rule about that point. `parity` at two rates is
# the cheapest reading that is not: it carries two arms alignment says
# are clean, four it says lose, and the artifact as a positive control,
# so the whole rule is re-read at the second rate rather than one arm of
# it.
#
# Run it at RC 98 and RC 65 - 397,959 and 600,000 sps - and run the pair
# in both orders. The tool blocks by rate, so a single ordering confounds
# the rate with the half-hour, which is the reason the arms inside a
# round are counterbalanced in the first place.
#
# RC 98 rather than a rate further away on purpose. It is above the
# 200 ksps floor where loss appears at all, below the 750 kHz-1.3 MHz
# band where the converter runs slow and sheds the surplus however it is
# written, and it is the one other rate this bench has a due-sized figure
# for - 0.605-0.633% on 2026-08-29 - so the positive control has an
# expectation rather than a hope.
#
# WHAT ALIGNMENT PREDICTS AT THE SECOND RATE, written before the run:
# const512 and alt2 lose nothing, because no write in either can contain
# a multiple of 1024; const1536, alt, alt3, alt5 and duehist all lose.
#
# WHAT WOULD REFUTE IT, also written before the run. Either clean arm
# losing at RC 98 makes the rule rate-dependent and therefore false as
# stated. Any of the four straddling arms coming back clean while
# duehist loses breaks the other half. And duehist clean voids the whole
# block rather than supporting anything - a null is worth what the
# instrument could have detected.
#
# AND THE SECOND RATE ANSWERS SOMETHING ONE RATE CANNOT. A deficit can
# be a fixed fraction of the bytes written or a fixed number of shed
# events per second, and at one rate those are the same number. The two
# rates differ by 1.5x, so:
#
#   fraction  the percentage is equal at both rates
#   events    the bytes lost per second are equal, so the percentage at
#             397,959 sps is about 1.5x the percentage at 600,000
#
# No prediction is registered between those two: the magnitude has
# resisted explanation across 15 arms at one rate, and guessing here
# would be inventing a number.

#: `altN` - runs of N writes at each size. Built on demand so the
#: family is a scan rather than five hand-written table entries.
_ALT_RE = re.compile(r"^alt(\d+)$")


def shape_for(arm):
    if arm in SHAPES:
        return SHAPES[arm]
    m = _ALT_RE.match(arm)
    if not m:
        return None
    n = int(m.group(1))
    return {"first": 512, "cycle": (512,) * n + (1024,) * n, "split": None}


class _ShapedPort:
    """The native port, with the feeder's write size rotated under it.

    Everything the feeder does with the port other than writing is
    delegated untouched. `write` is where the shape lives: it records
    the size actually issued, optionally splits the block into
    back-to-back pieces, and then arms the feeder with the next size in
    the cycle. The feeder reads `write_size` several times per pass but
    always before the write, so advancing it here is safe.
    """

    #: Candidate internal buffer sizes. A write that spans a multiple
    #: of one of these is what the alignment hypothesis says gets shed;
    #: counting them per arm turns that from a guess into a rate the
    #: deficit can be divided by, and it is the only way to read it off
    #: the due-sized path, whose sequence nobody chose.
    BOUNDARIES = (1024, 2048, 4096, 8192, 16384)

    def __init__(self, port, feeder, cycle, split, hist):
        self._port = port
        self._feeder = feeder
        self._cycle = cycle
        self._split = split
        self._hist = hist
        self._i = 0
        self._off = 0

    def _account(self, n):
        self._hist[n] += 1
        off = self._off
        for b in self.BOUNDARIES:
            if off // b != (off + n - 1) // b:
                self._hist[f"straddle{b}"] += 1
        self._off = off + n

    def __getattr__(self, name):
        return getattr(self._port, name)

    def write(self, data):
        if self._split:
            n = 0
            for off in range(0, len(data), self._split):
                piece = data[off:off + self._split]
                k = self._port.write(piece)
                self._account(k)
                n += k
                if k != len(piece):
                    break
            self._hist["bursts"] += 1
        else:
            n = self._port.write(data)
            self._account(n)
        if self._cycle:
            self._i = (self._i + 1) % len(self._cycle)
            self._feeder.write_size = self._cycle[self._i]
        return n


#: The feeder the last shaped run built, so its write histogram can be
#: read back - `run_play` owns the object and does not return it.
_LAST = []


def _shaped_feeder(shape):
    hist = collections.Counter()

    class ShapedFeeder(measure.Feeder):
        def __init__(self, port, *a, **kw):
            super().__init__(port, *a, **kw)
            self.hist = hist
            self.fd = _ShapedPort(port, self, shape["cycle"],
                                  shape["split"], hist)

    _LAST[:] = [hist]
    return ShapedFeeder


def one(board, rc, arm, seconds):
    hz = measure.hz_for(rc)
    # SHAPES first, so `due` keeps the stock feeder and `duehist` gets
    # the same policy with the counter fitted.
    shape = None if arm in ARMS else shape_for(arm)
    write_size = shape["first"] if shape else ARMS[arm]
    stock = measure.Feeder
    if shape:
        measure.Feeder = _shaped_feeder(shape)
    try:
        res = measure.run_play(board, dac_sps=hz, seconds=seconds,
                               drain_s=1.5, write_size=write_size)
    finally:
        measure.Feeder = stock
    if res.refused:
        return None
    deficit = res.host_deficit
    tx = res.host_tx_bytes
    hist = dict(_LAST[0]) if shape else {}
    return {"rc": rc, "hz": hz, "arm": arm, "tx": tx,
            "in": res.play.bytes_in if res.play else None,
            "deficit": deficit,
            "pct": round(deficit / tx * 100, 4) if tx else None,
            "chunks": deficit // 128 if deficit % 128 == 0 else None,
            "mod128": deficit % 128,
            "under": res.play.underruns if res.play else None,
            "drained": bool(res.drained),
            "elapsed_s": res.elapsed_s,
            "writes": {str(k): v for k, v in sorted(hist.items(),
                                                    key=lambda kv: str(kv[0]))},
            "via": res.play.via if res.play else None,
            "t_wall": time.time()}


def _order(arms, r):
    """Rotate the block, and reverse it on odd rounds.

    A fixed order gives one arm every warm slot and another every cold
    one, which is the drift confound this file already guards against
    for two arms; with five, rotation is the cheap version of the same
    thing.
    """
    k = r % len(arms)
    out = list(arms[k:]) + list(arms[:k])
    return out if r % 2 == 0 else out[::-1]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcs", default="195,98,65")
    ap.add_argument("--arms", default="policy",
                    help="policy | shape | a comma-separated arm list")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    arms = ARM_SETS.get(args.arms)
    if arms is None:
        arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    for a in arms:
        if a not in ARMS and shape_for(a) is None:
            ap.error(f"unknown arm {a!r}")

    rcs = [int(x) for x in args.rcs.split(",")]
    board = measure.Board(settle=3.0)
    prov = provenance.run_fields(board)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for rc in rcs:
            for r in range(args.rounds):
                for arm in _order(arms, r):
                    row = one(board, rc, arm, args.seconds)
                    if row is None:
                        print(f"  RC {rc} {arm}: refused", flush=True)
                        continue
                    row["round"] = r
                    row.update(bench=args.bench, **prov)
                    rows.append(row)
                    print(f"r{r} RC {rc:3d} ({row['hz']:7d} sps) "
                          f"{arm:9s}: deficit {row['deficit']:8d} B "
                          f"({row['pct']:6.3f}%)  "
                          f"{'' if row['mod128'] == 0 else 'NOT A CHUNK  '}"
                          f"under={row['under']}", flush=True)
                    board.stop()
                    board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    # Round 0 goes by index, never by a filter on what round 0 does
    # wrong - CLAUDE.md, and it has cost this project a claim already.
    later = [r for r in rows if r["round"] > 0]
    print(f"\nfirst round dropped by index; {len(later)} of {len(rows)} "
          f"rows analysed")
    for rc in rcs:
        print(f"RC {rc} ({measure.hz_for(rc)} sps):")
        for arm in arms:
            v = [r for r in later if r["rc"] == rc and r["arm"] == arm]
            if not v:
                continue
            pct = [r["pct"] for r in v]
            print(f"  {arm:9s} n={len(v)}  deficit "
                  f"{min(r['deficit'] for r in v)}-"
                  f"{max(r['deficit'] for r in v)} B, "
                  f"{min(pct):.3f}-{max(pct):.3f}%, "
                  f"median {statistics.median(pct):.3f}%, "
                  f"under {min(r['under'] for r in v)}-"
                  f"{max(r['under'] for r in v)}")
            w = collections.Counter()
            for r in v:
                for k, n in r["writes"].items():
                    w[k] += n
            if w:
                print("             writes " + ", ".join(
                    f"{k}x{n}" for k, n in sorted(w.items())))

    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
