"""Is there a room-temperature signal left once build and activity are fixed?

Issue #18 step 1. The sensor is known to read the workload (+1.57 codes
idle to max-rate capture) and the build (0.6-0.8 codes between tracks),
both larger than its 0.20-code short-term noise. If nothing above that
noise survives with those two held fixed, there is nothing to condition
a calibration on and the issue closes with a documented negative.

One build (Track B, a99146e), one activity (idle between reads), one
board, one session. The first samples are the die warming after the
flash and are kept rather than trimmed, because where the warm-up ends
is itself part of the answer.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
EVERY_S = 20.0
# Output name is an argument because this opens with "w". It used to be
# hardcoded to records/temp-soak.jsonl, so a second run silently
# truncated the first one's committed record - and this is an
# eight-hour measurement, which is the worst kind to overwrite.
OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else "temp-soak.jsonl"

b = measure.Board(settle=3.0)
out = os.path.join(ROOT, "records", OUT_NAME)
n = 0
# Append and flush per reading rather than writing at the end. The run
# this is for is hours long, and a file that only exists on a clean exit
# is a file that does not exist: `--calibrate` writing at session end
# cost the other bench twelve minutes on issue #6, and the same shape
# would cost a night here.
fh = open(out, "w", buffering=1, newline="\n")
try:
    b.stop(); b.drain_console(0.5)
    link = b.ctl()
    if link is None:
        raise SystemExit("no control channel")
    t0 = time.time()
    while time.time() - t0 < MINUTES * 60.0:
        t = time.time()
        r = link.temperature(samples=1024)
        if not r["tson"]:
            raise SystemExit("TSON clear - not the sensor")
        fh.write(json.dumps({"t_s": round(t - t0, 1), "code": r["code"],
                             "code_min": r["code_min"],
                             "code_max": r["code_max"],
                             "adc_mr": "%08x" % r["adc_mr"]},
                            sort_keys=True) + "\n")
        fh.flush()
        n += 1
        print("%7.1f s  %8.3f" % (t - t0, r["code"]), flush=True)
        # Idle is the fixed activity: nothing but the wait between reads.
        while time.time() - t < EVERY_S:
            time.sleep(0.5)
finally:
    try:
        b.close()
    finally:
        fh.close()
        print("\nwrote %s, %d rows" % (out, n))
