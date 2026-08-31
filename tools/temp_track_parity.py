"""Do the two tracks now read the die sensor the same?

Issue #15 measured them 0.844 +- 0.180 codes apart because they idled at
different ADC_MR - Track A at TRACKTIM 0 from acq_init(), Track B at 15
from adc_init() - and CTL_OP_TEMP converted at whatever the idle config
happened to be.

The fix was not to converge the idle configs, which would only have moved
the variable (both tracks *stream* at TRACKTIM 0, so a read after a
capture would still differ from one after boot). The measurement now sets
its own ADC_MR and restores it, so the reading no longer depends on what
the board was doing beforehand.

Protocol is #15's, because it is the only one that works here: ABBA with
a **reflash between every read**, since the die drifts 1-3 codes/min
under load and a flash-read-flash-read pair reads ~10x the true
difference.
"""
import argparse, json, os, re, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
import measure                                           # noqa: E402
import serial                                            # noqa: E402

PROG = "/dev/cu.usbmodem141201"


def read_temp(samples):
    s = serial.Serial(PROG, 115200, timeout=0.3)
    time.sleep(4.0)                      # the open resets; let it settle
    s.reset_input_buffer()
    s.write(("=%de" % samples).encode())
    s.flush()
    time.sleep(3.0)
    out = s.read(200000).decode("utf8", "replace")
    s.close()
    m = re.search(r"code (\d+)\.(\d+) \(min (\d+) max (\d+), n=(\d+)\)"
                  r" adcmr=([0-9a-f]+)", out)
    if not m:
        return None
    return {"code": float(m.group(1)) + float(m.group(2)) / 100,
            "n": int(m.group(5)), "adcmr": m.group(6)}


def arm(track, samples):
    # measure.flash() rather than a per-track argv table.
    #
    # This held its own {"a": sketch.sh, "b": flash.sh} map, which is a
    # second place that knows how each track is built - and #55 has just
    # spent a session establishing that a second way to build Track A is
    # exactly the thing to remove. It was also about to break: sketch.sh
    # is being deleted, and a hardcoded caller is how a deletion turns
    # into a broken tool nobody notices until they next need it.
    measure.flash(track=track, build=True)
    return read_temp(samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quartets", type=int, default=4)
    ap.add_argument("--samples", type=int, default=1024)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rows, deltas = [], []
    print("quartet   Track A     Track B     B - A    adcmr A / B")
    for q in range(args.quartets):
        got = {"a": [], "b": []}
        for t in ("a", "b", "b", "a"):
            r = arm(t, args.samples)
            if r is None:
                print("  read failed"); continue
            r["track"] = t
            r["quartet"] = q
            rows.append(r)
            got[t].append(r)
        if len(got["a"]) == 2 and len(got["b"]) == 2:
            a = statistics.mean(x["code"] for x in got["a"])
            b = statistics.mean(x["code"] for x in got["b"])
            deltas.append(b - a)
            print("%7d  %9.2f  %9.2f  %+8.3f    %s / %s"
                  % (q, a, b, b - a, got["a"][0]["adcmr"], got["b"][0]["adcmr"]))

    if len(deltas) > 1:
        m = statistics.mean(deltas); sd = statistics.stdev(deltas)
        se = sd / len(deltas) ** 0.5
        print("\nTrack B - Track A = %+.3f +- %.3f codes (se), n=%d quartets"
              % (m, se, len(deltas)))
        print("  %.1f sigma" % (abs(m) / se if se else 0.0))
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
