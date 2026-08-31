"""Track C control link: the failure needs IDLENESS, not calls.

First pass: 60 back-to-back load() calls in 0.06 s never failed, while
0.25 s gaps failed after 6 calls and 1.0 s gaps after 17. So the count
is not the variable and neither is elapsed time on its own - what the
two failing arms share is a PAUSE between requests, and the arm with no
pause is the one that survived.

This measures gaps-to-failure as a function of gap length, several
repetitions each, so "a Bernoulli trial per idle gap" can be told from
"a threshold in the gap length".

  per-gap Bernoulli   gaps-to-failure ~ geometric, mean independent
                      of the gap LENGTH
  length threshold    short gaps never fail, long gaps fail at once
"""
import sys, time, json
sys.path.insert(0, "host")
import ports, control, provenance

GAPS = [0.0, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0]
REPS = 4
BUDGET = 40

prov = None
out = []
for gap in GAPS:
    for rep in range(REPS):
        try:
            c = control.Control(ports.native_nodes()[1])
            ident = c.identity()
            if prov is None:
                # Over the link this tool already holds: opening the
                # programming port to label a row would reset the board
                # and destroy the measurement. issue #53.
                prov = provenance.run_fields(ident=ident)
        except Exception as e:
            print(f"  gap={gap} rep={rep}: OPEN FAILED {e}", flush=True)
            time.sleep(3.0)
            continue
        t0 = time.time()
        n, err = 0, None
        try:
            for _ in range(BUDGET):
                c.load()
                n += 1
                if gap:
                    time.sleep(gap)
        except Exception as e:
            err = type(e).__name__
        span = round(time.time() - t0, 2)
        try:
            c.close()
        except Exception:
            pass
        # provenance.run_fields() rather than a literal - issue #53,
        # where nine tools wrote track="b" and mislabelled every Track A
        # dataset they produced. This tool was written to run on Track C
        # and would have made the same mistake in the other direction.
        out.append(dict(gap=gap, rep=rep, calls_ok=n, span_s=span, err=err,
                        **prov))
        print(f"  gap={gap:<5} rep={rep}  calls_ok={n:>3}/{BUDGET} "
              f"span={span:6.2f}s  {err or 'survived'}", flush=True)
        time.sleep(2.0)

json.dump(out, open(sys.argv[1], "w"), indent=1)
