"""Phase against elapsed time at a fixed start gap.

Issue #5. K does not select the residue class, so what does? If the
landing is set by something counted and the run start samples it, a long
single-K run should show structure in the sequence - runs of one value,
or a return period - rather than an independent draw each time.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure

N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
rows = []
b = measure.Board(settle=3.0)
try:
    b.stop(); b.drain_console(0.5)
    b.poll_console(); b.cmd("=0K"); b.drain_console(0.4)
    for i in range(N):
        t = time.time()
        res = measure.run_capture(b, preset="M", seconds=2.0)
        ps = res.stream
        vals = ps.series.get(measure.CH_A0)
        if not vals:
            continue
        vals = vals[ps._index_at(measure.CH_A0, measure.SETTLE_US):]
        f = measure.pair_fold(vals)
        # A null fold reports phase 0 with peak 0. Recording that as an
        # observation is how "phase 0 in 60 of 60" happened once - the
        # capture was shorter than measure.SETTLE_US and nothing
        # survived the trim.
        if not f["peak"] or not f.get("hold_ok", True):
            print("%3d  refused: peak=%.2f hold_ok=%s"
                  % (i, f["peak"], f.get("hold_ok")), flush=True)
            continue
        rows.append({"i": i, "t_wall": t, "phase": f["peak_phase"],
                     "peak": abs(f["peak"])})
finally:
    b.close()
with open(os.path.join(ROOT, "records", "issue5-phase-vs-time.jsonl"), "w",
          newline="\n") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
t0 = rows[0]["t_wall"]
print("i   dt_s    phase  mod21  |peak|")
for r in rows:
    print("%3d %6.1f  %5d  %5d  %5.2f"
          % (r["i"], r["t_wall"] - t0, r["phase"], r["phase"] % 21, r["peak"]))
