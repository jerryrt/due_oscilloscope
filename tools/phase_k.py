"""Does the artifact's landing phase move with M's ADC-to-DAC start gap?

Issue #5's open question: peak_phase is 244 in all 40 captures on this
bench and takes three values on the macOS one. If the phase is where in
the DAC table the capture began, `=<us>K` - which is exactly that gap -
should move it deterministically, and the two benches differ in how
repeatable their start is rather than in anything analog.
"""
import os, sys
REPO = r"C:\Jerry.Projects\due_oscilloscope"
sys.path.insert(0, os.path.join(REPO, "host"))
import measure

b = measure.Board(settle=3.0)
try:
    b.stop(); b.drain_console(0.5)
    print("  K us   phase   |peak|      z")
    for us in [u for u in (1, 4, 6, 7, 10) for _ in range(3)]:
        b.poll_console(); b.cmd("=%dK" % us); b.drain_console(0.5)
        res = measure.run_capture(b, preset="M", seconds=2.0)
        ps = res.stream
        vals = ps.series.get(measure.CH_A0)
        if not vals:
            print("  %4d   capture failed" % us); continue
        vals = vals[ps._index_at(measure.CH_A0, measure.SETTLE_US):]
        f = measure.pair_fold(vals)
        print("  %4d   %5d   %6.2f  %6.1f"
              % (us, f["peak_phase"], abs(f["peak"]), f["z"]))
finally:
    try:
        b.poll_console(); b.cmd("=0K"); b.drain_console(0.4)
    finally:
        b.close()
