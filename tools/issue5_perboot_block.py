"""One block of #5's per-boot test: n=12 at a fixed FWS and rate.

Each block is its own process so it opens fresh ports, and each one
bounces the native port first.

**The bounce is not caution, it is required.** A processor reset (`z`)
leaves the native port wedged host-side - the device runs the preset
and prints its banner, `frames` reads 0, and every capture comes back
with an empty channel set. Reflashing does NOT clear it; `=<ms>Z`
does, immediately (0 frames -> 587). That extends CLAUDE.md's note,
which says `=<ms>Z` releases a wedged host `close()` but does not say
it is also the only recovery from a `z`-wedged native port.

`z` is used to change the boot rather than a reflash because it
re-runs main() and re-initialises the peripherals, which is the thing
under test, and costs seconds rather than half a minute. `uptime_ms`
is recorded so "the boot changed" is evidence rather than assumption.
"""
import sys, collections, json, os, time
sys.path.insert(0, "host")
import measure, provenance

HZ, FWS, CAPS = 200000, 5, 12
label, path = sys.argv[1], sys.argv[2]

b = measure.Board(settle=3.0)
got = []
try:
    b.cmd("=200Z")
    b.drain_console(0.5, cap=8.0)
    time.sleep(3.0)

    b.cmd(f"={FWS}q")
    txt = b.drain_console(0.5) or ""
    if f"fws: {FWS}" not in txt:
        raise SystemExit(f"{label}: FWS readback {txt.strip()[:40]!r}")

    fails = 0
    for _ in range(CAPS * 3):
        if len(got) >= CAPS:
            break
        if fails >= 3 and not got:
            raise SystemExit(f"{label}: 3 failures, no capture - port gone")
        try:
            r = measure.run_capture(b, preset=f"={HZ},{HZ}M", seconds=3.0)
            f = measure.pair_fold(r.stream.series[measure.CH_A0])
        except Exception as e:
            print(f"    (dropped: {type(e).__name__}: {e})", flush=True)
            fails += 1
            b.stop()
            continue
        fails = 0
        got.append((f["peak_phase"], round(f["peak"], 1)))
        b.stop()
finally:
    b.stop()
    b.close()

print(f"  {label}: {dict(collections.Counter(p for p, _ in got))}", flush=True)
all_ = json.load(open(path)) if os.path.exists(path) else {}
# issue #53: ask the board, never write a track literal.
all_[label] = {"captures": got, **provenance.run_fields(b)}
json.dump(all_, open(path, "w"), indent=1)
