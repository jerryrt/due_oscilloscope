#!/usr/bin/env python3
"""Verify a bench's declared wiring electrically, with arms that can fail.

    python3 tools/wiring_probe.py
    python3 tools/wiring_probe.py --rounds 4 --out records/x.jsonl

A declared wiring is what someone wrote in `bench.json`. This checks the
one layout the campaign benches share - DAC0->A0, DAC1->A1, A2 bare - by
making the board drive each pin and watching which ADC channel moves.
Track B only: `=<n>N` (gen layout) is a Track B console command.

PEAK-TO-PEAK ALONE CANNOT ANSWER THIS, and a probe that relied on it
reported "confirmed" here on bands that never moved. Preset M's default
sync (`gen_sync = GEN_SYNC_CYCLE`, drivers/gen.c) puts a full-scale square
on whichever DAC is not carrying the sine. So with sync on, A0 and A1 both
swing full scale in both layouts, and swapping the layout moves neither -
an "exchange" inside any tolerance wide enough to absorb noise is then a
check that cannot fail.

THE ARMS, interleaved per round, the first round dropped by index:

  sync off (=0J)   the spare DAC holds DC, so its pin must read SMALL.
      layout 0 (sine DAC0, DC DAC1): A0 big, A1 small
      layout 1 (DC DAC0, sine DAC1): A1 big, A0 small
  sync on  (=1J)   the POSITIVE CONTROL: both DACs swing full scale, so
      A0 and A1 must both read big. It proves the instrument sees a
      driven pin when one is there; without it a small reading means
      nothing.

A2 BARE is judged in the arms where both DACs are at full scale: a wire
from either would put A2 at full scale too. A bare A2 is not quiet. It
reads the charge its sample-and-hold kept from the conversion before it
- on windows-desk it follows A0's waveform, sine or square, at ~56% of
its amplitude, and falls to ~50 codes when A0 holds DC - so "quiet" is
the wrong test and "never full scale" is the right one.

Per channel the rows also carry the fraction of samples within 10% of the
range from either extreme - a square sits there ~1.0 of the time, a sine
~0.40 - so they say which waveform a pin carried, not only how big it was.

Restores `=1J` (the power-on sync) and `=0N` on the way out, whatever
happens. Opens the control port once; see tools/uptime_reset_probe.py
for whether that resets the board on your host.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure      # noqa: E402
import provenance   # noqa: E402

CHANS = (("a0", measure.CH_A0), ("a1", measure.CH_A1), ("a2", measure.CH_A2))
#: Codes. A driven sine or square here spans ~2750; a DC pin ~25.
BIG, SMALL = 2000, 400
#: A2 must stay below this fraction of the smallest driven reading.
A2_FRACTION = 0.75
ARMS = (("off", 0), ("off", 1), ("on", 0), ("on", 1))
PRESET = "=200000,200000,3M"


def stats(ps, tag):
    vals = ps.series.get(tag) or []
    tail = vals[ps._index_at(tag, measure.SETTLE_US):] if vals else []
    if len(tail) < 1000:
        return {"ptp": None, "edge": None, "n": len(tail)}
    lo, hi = min(tail), max(tail)
    rng = hi - lo
    if rng == 0:
        return {"ptp": 0, "edge": None, "n": len(tail)}
    band = 0.10 * rng
    edge = sum(1 for v in tail if v <= lo + band or v >= hi - band) / len(tail)
    return {"ptp": rng, "edge": round(edge, 3), "n": len(tail),
            "mean": round(statistics.fmean(tail), 1)}


def verdict(rows):
    """(exit code, lines). 0 confirmed, 2 not confirmed, 1 not answered."""
    kept = [r for r in rows if r["round"] > 0]
    out = []
    if not kept or any(r[f"{c}_ptp"] is None for r in kept
                       for c in ("a0", "a1", "a2")):
        return 1, ["VERDICT: NOT ANSWERED - a capture was short or no round "
                   "survived the first-round drop"]
    m = {}
    for s, L in ARMS:
        sel = [r for r in kept if r["sync"] == s and r["layout"] == L]
        if not sel:
            return 1, [f"VERDICT: NOT ANSWERED - arm sync={s} L{L} is empty"]
        for c in ("a0", "a1", "a2"):
            m[(s, L, c)] = statistics.median(r[f"{c}_ptp"] for r in sel)
        out.append(f"median sync={s} L{L}: A0 {m[(s, L, 'a0')]}  "
                   f"A1 {m[(s, L, 'a1')]}  A2 {m[(s, L, 'a2')]}")
    control = all(m[("on", L, c)] >= BIG for L in (0, 1) for c in ("a0", "a1"))
    exch = (m[("off", 0, "a0")] >= BIG and m[("off", 0, "a1")] <= SMALL and
            m[("off", 1, "a1")] >= BIG and m[("off", 1, "a0")] <= SMALL)
    driven_min = min(m[("on", L, c)] for L in (0, 1) for c in ("a0", "a1"))
    a2_max = max(m[(s, L, "a2")] for s, L in ARMS)
    a2_bare = a2_max <= A2_FRACTION * driven_min
    out.append(f"positive control (sync on: A0 and A1 >= {BIG})        : "
               f"{control}")
    out.append(f"sync off: the sine follows the layout, DC pin <= {SMALL} : "
               f"{exch}")
    out.append(f"A2 below {A2_FRACTION:.0%} of driven with both DACs at full "
               f"scale : {a2_bare} (A2 max {a2_max}, driven min {driven_min})")
    if not control:
        out.append("VERDICT: NOT ANSWERED - the positive control did not "
                   "fire, so a small reading would mean nothing")
        return 1, out
    ok = exch and a2_bare
    out.append("VERDICT: DAC0->A0, DAC1->A1, A2 bare is "
               + ("CONFIRMED electrically" if ok
                  else "NOT confirmed - read the rows"))
    return (0 if ok else 2), out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=4,
                    help="rounds of the four arms; the first is dropped")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--out", default=None, help="append rows to this JSONL")
    args = ap.parse_args()
    if args.rounds < 2:
        ap.error("--rounds must be at least 2: the first is dropped by index")

    decl = provenance.bench()
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        ident = measure.parse_identity(board.ask("v", secs=1.5))
        if not ident or ident.get("track") != "b":
            print(f"REFUSING: `=<n>N` is Track B only; the board says {ident}")
            return 1
        fields = provenance.run_fields(ident=ident)
        fields.update({"bench": decl.get("bench"),
                       "wiring_declared": decl.get("wiring"),
                       "wiring_since": decl.get("wiring_since"),
                       "tool": "tools/wiring_probe.py"})
        for rnd in range(args.rounds):
            order = ARMS if rnd % 2 == 0 else tuple(reversed(ARMS))
            for sync, layout in order:
                r1 = board.ask(f"={'0' if sync == 'off' else '1'}J",
                               secs=0.5).strip()
                r2 = board.ask(f"={layout}N", secs=0.5).strip()
                res = measure.run_capture(board, preset=PRESET,
                                          seconds=args.seconds)
                row = {"round": rnd, "sync": sync, "layout": layout,
                       "sync_reply": r1[-80:], "layout_reply": r2[-80:],
                       "frames": res.frames, "seq_gaps": res.seq_gaps,
                       "crc_bad": res.crc_bad,
                       "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                for name, tag in CHANS:
                    for k, v in stats(res.stream, tag).items():
                        row[f"{name}_{k}"] = v
                row.update(fields)
                rows.append(row)
                print(f"r{rnd} sync={sync} L{layout}: "
                      f"A0 {row['a0_ptp']} (edge {row['a0_edge']})  "
                      f"A1 {row['a1_ptp']} (edge {row['a1_edge']})  "
                      f"A2 {row['a2_ptp']} (edge {row['a2_edge']})",
                      flush=True)
    finally:
        try:
            board.stop()
            board.ask("=1J", secs=0.5)
            board.ask("=0N", secs=0.5)
        finally:
            board.close()

    code, lines = verdict(rows)
    for line in lines:
        print(line)
    if args.out:
        with open(args.out, "a", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                r["verdict_exit"] = code
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
