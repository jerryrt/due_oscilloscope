"""Does the die sensor read the workload rather than the room?

Issue #15: the two tracks read the sensor ~0.8 codes apart, and closing
the ADC_MR divergence did not remove it - it inverted to -0.6. The
candidate is that the sensor measures the die and the two tracks are
different workloads: Track A's main loop went 75.1 k -> 132.6 k
passes/s the same day, which is a power change.

This tests the mechanism without needing two builds, which removes the
reflash and the build from the comparison entirely. One image, one
session: read the sensor after the board has been idle, and after it has
been streaming at the maximum in-spec rate - the largest workload
difference the board has - and interleave the two.

If the workload term is real and this size, a track-to-track or
build-to-build temperature comparison measures the *firmware*, not the
environment, and docs/measurement-suite.md item 3 has to say so.
"""
import argparse, json, os, re, statistics, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
import serial                                            # noqa: E402

PROG = "/dev/cu.usbmodem141201"


def read_temp(s, samples):
    s.reset_input_buffer()
    s.write(("=%de" % samples).encode())
    s.flush()
    time.sleep(2.5)
    out = s.read(200000).decode("utf8", "replace")
    m = re.search(r"code (\d+)\.(\d+) .* adcmr=([0-9a-f]+)", out)
    if not m:
        return None
    return float(m.group(1)) + float(m.group(2)) / 100


def arm(s, busy, load_s, samples):
    """`busy` runs the max-rate capture for load_s; otherwise idle."""
    if busy:
        s.write(b"5"); s.flush()
        time.sleep(load_s)
        s.write(b"0"); s.flush()
        time.sleep(0.6)
    else:
        time.sleep(load_s)
    s.read(400000)
    return read_temp(s, samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--load", type=float, default=20.0)
    ap.add_argument("--samples", type=int, default=1024)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    s = serial.Serial(PROG, 115200, timeout=0.3)
    time.sleep(4.0)
    s.reset_input_buffer()

    rows, deltas = [], []
    print("round     idle    streaming     busy - idle")
    for r in range(args.rounds):
        got = {}
        for busy in (False, True, True, False):   # ABBA
            v = arm(s, busy, args.load, args.samples)
            if v is None:
                print("  read failed"); continue
            rows.append({"round": r, "busy": busy, "code": v,
                         "load_s": args.load})
            got.setdefault(busy, []).append(v)
        if len(got.get(False, [])) == 2 and len(got.get(True, [])) == 2:
            i = statistics.mean(got[False]); b = statistics.mean(got[True])
            deltas.append(b - i)
            print("%5d  %8.2f  %10.2f  %+14.3f" % (r, i, b, b - i))

    if len(deltas) > 1:
        m = statistics.mean(deltas); sd = statistics.stdev(deltas)
        se = sd / len(deltas) ** 0.5
        print("\nstreaming - idle = %+.3f +- %.3f codes (se), n=%d"
              % (m, se, len(deltas)))
        print("  %.1f sigma" % (abs(m) / se if se else 0.0))
    s.close()
    if args.json:
        with open(args.json, "a") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
