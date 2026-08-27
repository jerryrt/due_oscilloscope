"""Drive every supported waveform at every supported rate, and watch.

A visual check with numbers attached. The board plays one waveform at
one rate for a few seconds while the scope is framed for it, the tool
reads back what the instrument actually sees, then the output stops so
the transition is visible - and on to the next combination.

Two instruments, deliberately. A person watching the screen catches
what no assertion was written for: ringing, a level that is not where it
should be, a shape that degrades at the top of the ladder. The scope
readings alongside catch what a person will not notice, and turn "it
looked right" into a table someone can disagree with later.

Playback only - preset `P`, no capture. The ADC is the instrument under
suspicion in issue #5 and has its own rate ceiling; neither belongs in a
measurement of what the DAC puts on a pin.

    python3 tools/dso_sweep.py                 # everything, ~3 minutes
    python3 tools/dso_sweep.py --waveform sine
    python3 tools/dso_sweep.py --seconds 10 --rc 195 --rc 28
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))

import measure                                                # noqa: E402
import scope as dso                                           # noqa: E402

TC_HZ = 39_000_000

# The AWG ladder, as tests/test_rates.py pins it. RC is what the timer
# actually holds, so these are the rates that exist rather than round
# numbers that truncate into a different one.
AWG_RC = [195, 98, 65, 44, 39, 32, 28]

# Samples per cycle for the sine. Fixed rather than a fixed frequency so
# the shape on screen is identical at every rate and only the speed
# changes - which is what makes degradation at the top of the ladder
# visible as degradation rather than as "a faster sine".
SINE_SAMPLES_PER_CYCLE = 32

# DAC codes per sample in the ramp, and so 4096/step samples per cycle.
RAMP_STEP = measure.RAMP_STEP

# Mid-scale, in DAC codes. The DAC is not rail to rail: measured on this
# bench the output settles at 0.52 V and 2.82 V, so mid is about 1.65 V.
DC_CODE = 2048
DAC_MID_V = 1.67
DAC_SPAN_V = 2.4


def rate_of(rc):
    return TC_HZ // rc


def combinations(waveforms, rcs):
    """(name, kwargs for run_play, cycle period in seconds or None)."""
    for name in waveforms:
        for rc in rcs:
            sps = rate_of(rc)
            if name == "sine":
                tone = sps / SINE_SAMPLES_PER_CYCLE
                yield name, rc, sps, {"tone": tone}, 1.0 / tone
            elif name == "ramp":
                period = (4096 / RAMP_STEP) / sps
                yield name, rc, sps, {"ramp": RAMP_STEP}, period
            elif name == "dc":
                # No period, and so no edge to trigger on - see frame().
                yield name, rc, sps, {"dc": DC_CODE}, None


def frame(inst, ch, period, volts_per_div=0.5):
    """Point the scope at one waveform, and say how it was pointed.

    Three periods across the screen: enough to see the shape repeat and
    judge whether it is the same shape each time, without so many that
    an edge is one pixel wide.

    DC gets AUTO sweep and everything else gets NORMAL, which is not a
    detail. Under NORMAL the scope sweeps only on a trigger, so a still
    trace is evidence the trigger found the edge and a blank screen is
    evidence it did not - but a DC level has no edge, and NORMAL would
    leave the screen blank on a signal that is perfectly correct.
    """
    inst.channel_scale(ch, volts_per_div)
    inst.channel_offset(ch, -DAC_MID_V)
    inst.coupling(ch, "DC")
    if period:
        inst.timebase(period * 3.0 / 12.0)
        inst.trigger_edge(source=f"CHAN{ch}", slope="POS", level=DAC_MID_V,
                          sweep="NORMAL")
    else:
        inst.timebase(1e-3)
        inst.trigger_edge(source=f"CHAN{ch}", level=DAC_MID_V, sweep="AUTO")
    inst.run()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--waveform", action="append", default=[],
                    choices=("sine", "ramp", "dc"),
                    help="repeatable; default all three")
    ap.add_argument("--rc", action="append", type=int, default=[],
                    help="repeatable; default the whole AWG ladder")
    ap.add_argument("--seconds", type=float, default=5.0,
                    help="how long to hold each combination (default 5)")
    ap.add_argument("--off", type=float, default=1.5,
                    help="silence between combinations, so the transition "
                         "is visible (default 1.5)")
    ap.add_argument("--channel", type=int, default=1,
                    help="scope channel watching DAC0 (default 1)")
    ap.add_argument("--no-scope", action="store_true",
                    help="drive the board without touching the instrument")
    args = ap.parse_args()

    waveforms = args.waveform or ["sine", "ramp", "dc"]
    rcs = args.rc or AWG_RC

    inst = None
    if not args.no_scope:
        try:
            inst = dso.open_scope()
            print(f"scope: {' '.join(inst.identify())}")
            print(f"probe on CH{args.channel}: x{inst.probe(args.channel):g} "
                  f"- this is what the scope has been TOLD, not what is "
                  f"fitted")
        except dso.ScopeUnavailable as e:
            print(f"scope: {e}\n  continuing without it; the board still "
                  f"plays and you can still watch")

    rows = []
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        for name, rc, sps, kw, period in combinations(waveforms, rcs):
            shape = (f"{1/period:,.0f} Hz" if period else "level "
                     f"{DC_CODE}")
            print(f"\n=== {name:4s}  RC {rc:3d}  {sps:>9,} sps  {shape} ===",
                  flush=True)
            if inst:
                frame(inst, args.channel, period)
            print(f"    playing {args.seconds:g}s ...", flush=True)

            res = measure.run_play(board, dac_sps=sps, seconds=args.seconds,
                                   **kw)

            got = {}
            if inst:
                # Read while the output is still up: the instrument
                # measures what is on the pin now, not what was there.
                got = inst.measure_all(args.channel)
                fmt = {k: ("-" if v is None else f"{v:.4g}")
                       for k, v in got.items()}
                print(f"    scope: Vpp {fmt['VPP']}  Vmax {fmt['VMAX']}  "
                      f"Vmin {fmt['VMIN']}  freq {fmt['FREQ']}", flush=True)

            rows.append((name, rc, sps, period, got))
            board.stop()
            board.drain_console(0.2)
            print(f"    off {args.off:g}s", flush=True)
            time.sleep(args.off)
    finally:
        try:
            board.stop()
        finally:
            board.close()
            if inst:
                inst.close()

    print("\n" + "=" * 74)
    print(f"{'wave':5s} {'RC':>4s} {'sps':>10s} {'expected':>12s} "
          f"{'measured':>12s} {'Vpp':>8s}")
    print("-" * 74)
    for name, rc, sps, period, got in rows:
        exp = f"{1/period:,.0f} Hz" if period else "DC"
        f = got.get("FREQ")
        vpp = got.get("VPP")
        print(f"{name:5s} {rc:4d} {sps:10,} {exp:>12s} "
              f"{('-' if f is None else f'{f:,.0f} Hz'):>12s} "
              f"{('-' if vpp is None else f'{vpp:.3f} V'):>8s}")
    print("=" * 74)
    print("A dash under measured is not a failure for DC: the instrument "
          "reports\nno frequency because there is none. It is a failure "
          "for anything else.")


if __name__ == "__main__":
    main()
