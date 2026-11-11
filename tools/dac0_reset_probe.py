"""DAC0 through a full internal reset, read on the bench scope (AFE AW-8).

    python3 tools/dac0_reset_probe.py POSITIVE 2.30 0.5 records/x.json

Holds DAC0 at the generator's DC code, arms a single-shot edge trigger on
the scope's CH1 (wired to DAC0), resets the Due with the `f` console
command - a forced fault, whose handler resets with PROCRST | PERRST, so
the DAC controller is reset as well as the processor - and reads the
acquisition memory in peak-detect mode. Prints a summary and a 60-bin
min/max envelope. VDIV, VOFF and TOFF set the vertical scale, offset and
trigger delay. A DTR toggle on the programming port does not reset the
board on every host, and `z` resets the processor only, which leaves the
DAC running; neither is a fair reset for this question.

A diagnostic: it reads the pin and decides nothing.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402
import scope  # noqa: E402

slope = sys.argv[1] if len(sys.argv) > 1 else "NEGATIVE"
level = float(sys.argv[2]) if len(sys.argv) > 2 else 1.40
tb = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
out = sys.argv[4] if len(sys.argv) > 4 else None

# 1. hold DAC0 at the DC code (layout all-DC, generator DC, sync off)
b = measure.Board()
ident = b.ask("v", secs=1.0).strip()
measure.set_sync(b, "off")
b.ask("=3N", secs=0.5)
measure.set_gen(b, "dc", 2)
h86 = measure.hz_for(86)
measure.run_capture(b, preset="=%d,%dM" % (h86, h86), seconds=1.0)

with scope.open_scope() as s:
    s.channel_enable(1, True)
    s.coupling(1, "DC")
    probe = s.probe(1)
    s.channel_scale(1, float(os.environ.get("VDIV", "0.5")))
    s.channel_offset(1, float(os.environ.get("VOFF", "-1.6")))
    s.timebase(tb)
    s.timebase_offset(float(os.environ.get("TOFF", "0.0")))
    s.io.write(":ACQ:TYPE PEAKDETECT", settle=0.2)
    acq = s.io.ask(":ACQ:TYPE?")
    s.memory_depth("NORMAL")
    s.trigger_edge(source="CHAN1", level=level, slope=slope, sweep="SINGLE")
    pre = s.level(1)  # screen reading while running, before arming
    s.run()
    time.sleep(1.5)
    status_armed = s.io.ask(":TRIG:STAT?")
    # 2. full internal reset: the fault command (PROCRST | PERRST)
    t_reset = time.time()
    b.poll_console()
    b.cmd("f")
    time.sleep(tb * 8)
    status = s.io.ask(":TRIG:STAT?")
    banner = b.drain_console(0, quiet=1.0, cap=6.0)
    if status != "STOP":
        s.stop()
        time.sleep(0.4)
    v = s.waveform(1, points="RAW")
    sr = s.sample_rate(1)
    s.io.write(":WAV:POIN:MODE NORMAL", settle=0.1)
    s.io.write(":ACQ:TYPE NORMAL", settle=0.1)
    s.trigger_edge(sweep="AUTO")
    s.run()

try:
    b.close()
except Exception as e:
    print("close:", e)
dt = 1.0 / sr
n = len(v)
lo, hi = min(v), max(v)
res = {"ident_before": ident, "slope": slope, "level_v": level,
       "timebase_s_per_div": tb, "probe": probe, "acq": acq,
       "status_armed": status_armed, "status_after": status,
       "triggered": status == "STOP", "pre_level_v": pre, "points": n,
       "sample_rate": sr, "span_s": n * dt, "min_v": lo, "max_v": hi, "console_after": str(banner)[-400:]}
# decimated envelope: 60 bins of min/max with time from record start
bins = 60
env = []
for k in range(bins):
    seg = v[k * n // bins:(k + 1) * n // bins]
    if seg:
        env.append((round(k * n // bins * dt, 4), round(min(seg), 3),
                    round(max(seg), 3)))
res["envelope_t_min_max"] = env
print(json.dumps({k: res[k] for k in res if k != "envelope_t_min_max"},
                 indent=1))
for t, a, c in env:
    print(f"{t:8.4f} s  {a:7.3f} .. {c:7.3f} V")
if out:
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f)
