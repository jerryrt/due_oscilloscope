"""Does the DAC output-stage bias move issue #5's artifact?

Issue #5 is one sample per DAC table wrap displaced by a few codes,
"a DAC output pin, not a splice". Issue #13 measured DACC_ACR's bias
moving the settling edge 2.71x (records/acr-rise.jsonl), and until
2026-08-28 gen_apply_acr() zeroed that bias on every capture - so every
issue-#5 observation on record was taken at the *slowest slew the part
offers*.

If the displaced sample is the ADC catching the converter mid-transition
at the PDC reload, a 2.71x faster edge should move the displacement. If
it does not, the artifact is not the edge and a whole family of
hypotheses is dead.

pair_fold() is the instrument the suite already uses: gen holds each DAC
level for two ADC samples, so differencing within the pair cancels the
staircase and leaves the one-sample event at full height, with no
threshold anywhere in it.

ABBA interleaved within one session, because the binary selects which
state issue #5 draws and the die warms - a sweep is confounded with both.
"""
import argparse, json, os, statistics, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
import measure                                          # noqa: E402

ARMS = {"0x000": (0, 0), "0x10A": (2, 1)}


def one(board, arm, seconds):
    ch, core = ARMS[arm]
    board.poll_console()
    board.cmd("=%d,%dI" % (ch, core))
    board.drain_console(0.4)
    res = measure.run_capture(board, preset="M", seconds=seconds)
    ps = res.stream
    vals = ps.series.get(measure.CH_A0)
    if not vals:
        return None
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    vals = vals[start:]
    fold = measure.pair_fold(vals)
    census = measure.level_census(vals)
    return {"arm": arm, "peak": fold["peak"], "z": fold["z"],
            # Wall clock per capture, so the landing phase can be tested
            # against elapsed time rather than argued about. Issue #5:
            # the phases sit on a lattice of 21 and a lattice is what a
            # periodic process looks like when the run start is
            # arbitrary - which is testable only if the start is
            # recorded.
            "t_wall": time.time(),
            "control_z": fold["control_z"], "phase": fold["peak_phase"],
            "hold_ok": bool(fold["hold_ok"]),
            "pair_spread": fold["pair_spread"],
            "census": census["count"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    board.stop()
    board.drain_console(0.5)

    rows, by = [], {k: [] for k in ARMS}
    print("round   0x000 peak    z   |  0x10A peak    z   |   |B|-|A|")
    for r in range(args.rounds):
        got = {}
        # Counterbalanced, not merely interleaved. ABBA aliases arm
        # with position-in-round perfectly - 0x000 only ever ran 1st
        # and 4th, 0x10A only 2nd and 3rd, in all 44 committed rows -
        # so "the arm never lands at 188" and "positions 1 and 4 never
        # land at 188" were the same sentence, and the record could not
        # tell "the arm reaches the start relationship" from "the
        # cadence does". Alternating ABBA with BAAB gives each arm
        # every position; with t_wall per capture that is the design
        # that separates them. Issue #5.
        order = (("0x000", "0x10A", "0x10A", "0x000") if r % 2 == 0
                 else ("0x10A", "0x000", "0x000", "0x10A"))
        for pos, arm in enumerate(order):
            row = one(board, arm, args.seconds)
            if row is None:
                print("  capture failed"); continue
            row["round"] = r
            row["pos"] = pos
            rows.append(row)
            by[arm].append(row)
            got.setdefault(arm, []).append(row)
        if len(got.get("0x000", [])) == 2 and len(got.get("0x10A", [])) == 2:
            a = statistics.mean(abs(x["peak"]) for x in got["0x000"])
            az = statistics.mean(x["z"] for x in got["0x000"])
            b = statistics.mean(abs(x["peak"]) for x in got["0x10A"])
            bz = statistics.mean(x["z"] for x in got["0x10A"])
            print("%5d  %10.2f %6.1f  |%10.2f %6.1f  | %+9.2f"
                  % (r, a, az, b, bz, b - a))

    for arm in ARMS:
        v = by[arm]
        if len(v) > 1:
            mag = [abs(x["peak"]) for x in v]
            print("  ACR %s: |peak| %.2f +- %.2f codes, z %.1f, "
                  "hold_ok %d/%d, n=%d"
                  % (arm, statistics.mean(mag), statistics.stdev(mag),
                     statistics.mean(x["z"] for x in v),
                     sum(1 for x in v if x["hold_ok"]), len(v), len(v)))
    if args.json:
        with open(args.json, "a") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
