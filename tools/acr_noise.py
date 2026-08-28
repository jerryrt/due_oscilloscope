"""Does DACC_ACR's bias setting move the noise floor?

The third corner of the same question. IBCTL is a slew-rate control, so
the three figures a bench can reach without an instrument answer
different halves of it:

    saturated update rate   how fast the converter can be clocked
    settling edge           how long one transition takes
    effective_bits          how quiet a *held* level is

`tools/acr_rise.py` measures the second and found 2.71x. This measures
the third, because `effective_bits` is what `docs/metric-baseline-*.md`
reports and what a re-take would move - and a slew control has no
obvious reason to touch a level that is not moving. Worth knowing rather
than assuming, since the whole argument for the 2/1 default is that the
part should run at its characterised condition.

ABBA interleaved within one session, because the die warms: an
un-interleaved sweep here drifts monotonically and reads as a
dependence. Same trap as the temperature sensor in issue #11.
"""
import argparse, json, os, statistics, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))
import measure, noisetool                              # noqa: E402

ARMS = {"0x000": (0, 0), "0x10A": (2, 1)}


def one(board, arm, lsb_v, seconds):
    ch, core = ARMS[arm]
    board.poll_console()
    board.cmd("=%d,%dI" % (ch, core))
    board.drain_console(0.4)
    res = noisetool.hold_gen_dc(board, 2048, "5", seconds)
    fs = res.stream.declared_rate_hz or 453488
    a = noisetool.analyse(noisetool._series(res, measure.CH_A0), fs,
                          lsb_v, window=4096)
    if "error" in a:
        return None
    return {"arm": arm, "effective_bits": a["effective_bits"],
            "rms_lsb": a["rms_lsb"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--json", default=None, help="append rows here")
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    board.stop()
    board.drain_console(0.5)
    lsb_v, advref, source = noisetool.adc_lsb_v()
    print("lsb %.1f uV  advref %s mV (%s)" % (lsb_v * 1e6, advref, source))

    rows, deltas = [], []
    by_arm = {k: [] for k in ARMS}
    print("round   0x000 bits   0x10A bits      B - A")
    for r in range(args.rounds):
        # ABBA, so a linear drift cancels inside the round
        got = {}
        for arm in ("0x000", "0x10A", "0x10A", "0x000"):
            row = one(board, arm, lsb_v, args.seconds)
            if row is None:
                continue
            row["round"] = r
            rows.append(row)
            by_arm[arm].append(row["effective_bits"])
            got.setdefault(arm, []).append(row["effective_bits"])
        if len(got.get("0x000", [])) == 2 and len(got.get("0x10A", [])) == 2:
            a = statistics.mean(got["0x000"])
            b = statistics.mean(got["0x10A"])
            deltas.append(b - a)
            print("%5d  %11.4f  %11.4f  %+9.4f" % (r, a, b, b - a))

    if len(deltas) > 1:
        m = statistics.mean(deltas)
        sd = statistics.stdev(deltas)
        print("\neffective_bits, 0x10A - 0x000: %+.4f bits, sd %.4f, "
              "n=%d, se %.4f" % (m, sd, len(deltas), sd / len(deltas) ** 0.5))
    for arm in ARMS:
        v = by_arm[arm]
        if len(v) > 1:
            print("  ACR %s: %.4f +- %.4f bits, n=%d"
                  % (arm, statistics.mean(v), statistics.stdev(v), len(v)))

    if args.json:
        with open(args.json, "a") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
