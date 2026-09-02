"""Is the residue class a function of K, or of when the run started?

Issue #5. Three passes over the same K values with a wall clock on each
capture. A function of K repeats across passes; a function of elapsed
time does not, and the timestamp says which.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure

KS = list(range(0, 11))
rows = []
b = measure.Board(settle=3.0)
try:
    b.stop(); b.drain_console(0.5)
    for p in range(3):
        for k in KS:
            b.poll_console(); b.cmd("=%dK" % k); b.drain_console(0.4)
            t = time.time()
            res = measure.run_capture(b, preset="M", seconds=1.5)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0)
            if not vals:
                continue
            vals = vals[ps._index_at(measure.CH_A0, measure.SETTLE_US):]
            f = measure.pair_fold(vals)
            rows.append({"pass": p, "k_us": k, "t_wall": t,
                         "phase": f["peak_phase"], "peak": abs(f["peak"])})
            print("p%d K=%-2d phase=%-4d mod21=%-3d |peak|=%5.2f"
                  % (p, k, f["peak_phase"], f["peak_phase"] % 21,
                     abs(f["peak"])), flush=True)
finally:
    try:
        b.poll_console(); b.cmd("=0K"); b.drain_console(0.4)
    finally:
        b.close()
with open(os.path.join(ROOT, "records", "issue5-k-passes.jsonl"), "w",
          newline="\n") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
print("\nwrote records/issue5-k-passes.jsonl", len(rows), "rows")
