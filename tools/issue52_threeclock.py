"""Issue #52: separate the board's crystal from the host controller's.

`mck_meas_hz` is MCK counted against the host's USB SOF, so it is a
RATIO of two crystals and cannot say which one is off.  A third clock
breaks the tie, and on Linux the host has one: chrony steers
CLOCK_REALTIME to UTC, residual frequency -0.019 ppm and skew 0.169 -
two orders below the ~10 ppm effect.

  dev_us  is MCK-derived   -> board crystal vs UTC
  frames  counts host SOF  -> host controller crystal vs UTC

Both counters are latched at the same SOF edge, so the pair is
coherent; the only error is when that edge fell relative to the host
timestamp, bounded by one SOF period.  Regressing 30 samples over 15
minutes puts that well below the effect.
"""
import sys, time, json
sys.path.insert(0, 'host')
import ports, control

def _utc_now():
    """The UTC-disciplined system clock, on every platform.

    This file used `time.clock_gettime(time.CLOCK_REALTIME)`, which
    does not exist on Windows - the tool aborted at import on windows-desk with
    AttributeError before taking a sample. Same class as #53's os.path
    problem and flash.py's os.path.exists(COM10): a POSIX name standing in
    for a portable idea.

    time.time() IS CLOCK_REALTIME. It is the UTC-disciplined system clock
    everywhere, which is exactly the third clock this measurement needs -
    the one thing that must NOT be substituted here is monotonic or
    perf_counter, because those are free-running and the whole method
    rests on the reference being steered to UTC.

    Resolution differs and matters. On Linux the call is nanosecond-ish;
    on windows-desk the observed step of time.time() is ~1 ms against a
    nominal 15.625 ms, and the round-trip column in each row is what says
    whether that is small enough for the sample it took.
    """
    return time.time()


nodes = ports.native_nodes()
c = control.Control(nodes[1])
print("identity", c.identity()['track'], c.identity()['build'], flush=True)

rows = []
t_end = time.time() + 15 * 60
while time.time() < t_end:
    t0 = _utc_now()
    s = c.heartbeat()['sof']
    t1 = _utc_now()
    rows.append(dict(t=(t0 + t1) / 2.0, rt_us=(t1 - t0) * 1e6, **s))
    time.sleep(30)
c.close()

# least squares slope, no numpy
def slope(xs, ys):
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den

t0 = rows[0]['t']
xs = [r['t'] - t0 for r in rows]
mck_ppm = (slope(xs, [r['dev_us'] for r in rows]) / 1e6 - 1.0) * 1e6
sof_ppm = (slope(xs, [r['frames'] for r in rows]) / 1e3 - 1.0) * 1e6
ratio = [(r['mck_meas_hz'] - 78000000) / 78.0 for r in rows if r['mck_meas_hz']]

print(f"\nn={len(rows)}  span={xs[-1]:.1f} s  "
      f"max round trip {max(r['rt_us'] for r in rows):.0f} us")
print(f"  board MCK   vs UTC : {mck_ppm:+.2f} ppm")
print(f"  host  SOF   vs UTC : {sof_ppm:+.2f} ppm")
print(f"  MCK vs SOF (device): {ratio[-1]:+.2f} ppm cumulative")
print(f"  predicted ratio    : {mck_ppm - sof_ppm:+.2f} ppm  "
      f"(board - host, should match the device)")
# The output path is optional: the run costs 15 minutes and losing it to
# an IndexError after the numbers are already on screen is a poor trade.
# It threw here on the first Windows run, after printing everything.
out = sys.argv[1] if len(sys.argv) > 1 else None
payload = dict(rows=rows, mck_ppm=mck_ppm, sof_ppm=sof_ppm, ratio_ppm=ratio,
               closure_ppm=(mck_ppm - sof_ppm) - ratio[-1],
               span_s=xs[-1], max_round_trip_us=max(r['rt_us'] for r in rows))
if out:
    json.dump(payload, open(out, 'w'), indent=1)
    print(f"  wrote {out}")
else:
    print("  (no output path given; pass one to keep the rows)")
