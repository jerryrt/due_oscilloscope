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

There are two generators on this board and this tool drives both.

    streamed   the host authors every sample and feeds them over USB.
               The rate axis is the AWG ladder, and the shape can be
               anything - it is `measure.build_selected`.
    internal   the device plays its own table with no USB in the path.
               The rate axis is resolution, because the trigger fixes
               the update rate and points-per-cycle decides how many
               updates a cycle spends. See docs/awg.md.

Same shapes, same framing, same readings, so the two are comparable -
which is the whole reason the internal one is worth watching through the
same instrument.

    python3 tools/dso_sweep.py                 # streamed, ~4 minutes
    python3 tools/dso_sweep.py --waveform sine
    python3 tools/dso_sweep.py --seconds 10 --rc 195 --rc 28
    python3 tools/dso_sweep.py --internal      # the device's own table
    python3 tools/dso_sweep.py --internal --points 8 --waveform square
"""
import argparse
import os
import sys
import threading
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

# Samples per cycle for the shapes that have a frequency. Fixed rather
# than a fixed frequency so the shape on screen is identical at every
# rate and only the speed changes - which is what makes degradation at
# the top of the ladder visible as degradation rather than as "a faster
# sine".
#
# The square gets the same count deliberately: the two shapes then ask
# the DAC for the same number of updates per cycle and differ only in
# what those updates are, so anything that appears on one and not the
# other is about the step size rather than about the rate.
SAMPLES_PER_CYCLE = 32

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
                tone = sps / SAMPLES_PER_CYCLE
                yield name, rc, sps, {"tone": tone}, 1.0 / tone
            elif name == "square":
                tone = sps / SAMPLES_PER_CYCLE
                yield name, rc, sps, {"square": tone}, 1.0 / tone
            elif name == "ramp":
                period = (4096 / RAMP_STEP) / sps
                yield name, rc, sps, {"ramp": RAMP_STEP}, period
            elif name == "dc":
                # No period, and so no edge to trigger on - see frame().
                yield name, rc, sps, {"dc": DC_CODE}, None


# Resolutions swept in --internal mode, and the frequency axis there.
# Powers of two because nothing else divides the table; four of them
# because two octaves either side of the default is enough to see the
# staircase coarsen and the frequency rise together.
INTERNAL_POINTS = [256, 64, 16, 4]

# Trigger presets, which are the only commands that start a capture
# without also starting host-fed playback - and playback would be a
# second claimant on the DACC. `L` takes an arbitrary rate and is
# therefore the wrong command here.
TRIGGER_PRESETS = {50_000: "1", 100_000: "2", 200_000: "3", 400_000: "4"}


def internal_combinations(waveforms, points_list, trigger_hz):
    """(name, points, trigger, output Hz, cycle period) for the device's
    own generator.

    A 2-point sine is degenerate and is skipped rather than reported as
    a failure: both of its samples land on a zero crossing, so the table
    holds mid-scale twice and the output is a flat line. That is Nyquist
    doing exactly what it says, not the converter failing - measured,
    and the square at the same resolution makes a clean 50 kHz.
    """
    for name in waveforms:
        for pts in points_list:
            p = measure.gen_points_for(pts)
            if name == "sine" and p == 2:
                print(f"    skipping sine at 2 pts/cycle: both samples "
                      f"sit on a zero crossing, so the output is flat "
                      f"by construction")
                continue
            hz = measure.gen_output_hz(trigger_hz, p)
            yield name, p, trigger_hz, hz, (None if name == "dc"
                                            else 1.0 / hz)


def frame(inst, ch, period, volts_per_div=0.5, ext=False):
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
    inst.timebase(period * 3.0 / 12.0 if period else 1e-3)
    if ext:
        apply_ext(inst, ext)
    elif period:
        inst.trigger_coupling("DC")
        inst.trigger_edge(source=f"CHAN{ch}", slope="POS", level=DAC_MID_V,
                          sweep="NORMAL")
    else:
        inst.trigger_coupling("DC")
        inst.trigger_edge(source=f"CHAN{ch}", level=DAC_MID_V, sweep="AUTO")
    inst.run()


def wait_triggered(inst, timeout=3.0):
    """Wait for a real acquisition before believing a measurement.

    Under NORMAL sweep the instrument does not redraw until it triggers,
    and `:MEAS:` answers from whatever the screen still holds - so a
    measurement taken too early is not wrong-looking, it is a plausible
    number from the previous combination. Returns the last status seen,
    so a caller can say which it got rather than guessing.
    """
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = inst.io.ask(":TRIG:STAT?")
        if status == "T'D":
            return status
        time.sleep(0.1)
    return status


def arm_ext(board, inst, preset):
    """Find the EXT trigger level once, with the output running.

    Once per run and not once per combination, for two reasons. The
    probe and the sync do not change between combinations, so a search
    per combination is repeated work; and a search that outlives the
    window it was started in keeps driving the instrument while the next
    acquisition is using it, which is a USBTMC collision and reads as a
    timeout rather than as the ordering mistake it is.

    The window is about 100 mV wide and moves with the probe ratio -
    x10 puts it at 0.1-0.2 V DC, and x1 needs AC because the DAC's
    1.67 V midpoint is past the input's 1.2 V clamp. So it is
    discovered; a failure means no signal is arriving rather than a
    level to guess harder at. See docs/awg.md.
    """
    measure.set_sync(board, "cycle")
    measure.set_gen(board, "square", 32)   # fastest sync edges to find
    board.cmd(preset)
    time.sleep(1.0)
    got = inst.ext_trigger_autoset()
    board.stop()
    board.drain_console(0.3)
    if got:
        print(f"EXT trigger armed: {got['coupling']} coupled, level "
              f"{got['level']:+.2f} V", flush=True)
    else:
        print("EXT did not trigger at any level - no signal is reaching "
              "it. Check the cable, and that the sync is on (=1J).",
              flush=True)
    return got


def apply_ext(inst, armed):
    """Re-assert the settings arm_ext() found. Cheap: no search."""
    inst.trigger_coupling(armed["coupling"])
    inst.trigger_edge(source="EXT", slope=armed["slope"],
                      level=armed["level"], sweep="NORMAL")


def hold_and_measure(inst, ch, period, seconds, run, label, ext=False):
    """Frame the scope, start the output, read it *while* it runs.

    Reading afterwards samples whatever is left on the pin, which for
    streamed playback is sometimes the tail of the waveform and
    sometimes a dead pin - the DAC runs out its last buffer and is
    abandoned after 500 ms. It cost one dash in twenty-one on the first
    full sweep, and a dash is what this tool calls a failure.

    The instrument is a separate USB device from the board, so the
    reader thread contends with nothing; one thread owns the scope,
    which is all UsbTmc asks.
    """
    if inst:
        frame(inst, ch, period, ext=ext)
    print(f"    {label} {seconds:g}s ...", flush=True)
    got, trig = {}, None
    reader = None
    if inst:
        def read_during():
            nonlocal got, trig
            time.sleep(min(2.0, seconds * 0.4))
            trig = wait_triggered(inst) if (period or ext) else "AUTO"
            got = inst.measure_all(ch)
        reader = threading.Thread(target=read_during, daemon=True)
        reader.start()
    run()
    if reader:
        reader.join(timeout=10.0)
    if inst:
        fmt = {k: ("-" if v is None else f"{v:.4g}") for k, v in got.items()}
        print(f"    scope: Vpp {fmt.get('VPP','?')}  "
              f"Vmax {fmt.get('VMAX','?')}  Vmin {fmt.get('VMIN','?')}"
              f"  freq {fmt.get('FREQ','?')}", flush=True)
        if trig not in ("T'D", "AUTO"):
            print(f"    NOT TRIGGERED (status {trig}) - the numbers above "
                  f"are from whatever the screen held", flush=True)
    return got


def build_parser():
    """Separate from main() so a test can read the defaults without
    driving a board - notably that the measured channel is DAC0. DAC1
    carries the bench trigger now and is not a channel to look at."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--waveform", action="append", default=[],
                    choices=("sine", "square", "ramp", "triangle", "dc"),
                    help="repeatable; default all but triangle, which the "
                         "streamed path does not build")
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
    ap.add_argument("--internal", action="store_true",
                    help="sweep the device's own table generator instead "
                         "of streaming samples to it")
    ap.add_argument("--points", action="append", type=int, default=[],
                    help="--internal only: resolutions to sweep, repeatable "
                         f"(default {INTERNAL_POINTS})")
    ap.add_argument("--trigger", type=int, default=200_000,
                    choices=sorted(TRIGGER_PRESETS),
                    help="--internal only: trigger rate (default 200000)")
    ap.add_argument("--ext-trigger", action="store_true",
                    help="trigger on the DAC1 sync through EXT instead of "
                         "on the signal; the level is discovered, not "
                         "assumed - see docs/awg.md")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()

    if args.ext_trigger and not args.internal:
        # The streamed path cannot make a sync. build_waveform tags every
        # sample for DAC0, and the one attempt to interleave DAC1 is a
        # recorded, unexplained failure - "the analog result behaved as
        # though both samples reached channel 0" - so there is nothing on
        # the spare pin to trigger from. Refusing beats running a whole
        # sweep that never triggers, which is what the first attempt at
        # this did.
        sys.exit("--ext-trigger needs the sync, which only the internal "
                 "generator makes: add --internal, or drop --ext-trigger")

    if args.internal:
        waveforms = args.waveform or ["sine", "square", "ramp", "triangle",
                                      "dc"]
    else:
        waveforms = args.waveform or ["sine", "square", "ramp", "dc"]
        if "triangle" in waveforms:
            sys.exit("triangle exists only on the internal generator; "
                     "add --internal or drop it")
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
        armed = None
        if args.internal:
            preset = TRIGGER_PRESETS[args.trigger]
            if args.ext_trigger:
                armed = arm_ext(board, inst, preset) if inst else None
            for name, pts, trig_hz, out_hz, period in internal_combinations(
                    waveforms, args.points or INTERNAL_POINTS, args.trigger):
                shape = f"{out_hz:,.1f} Hz" if period else "level 2048"
                print(f"\n=== {name:8s}  {pts:3d} pts/cycle  trigger "
                      f"{trig_hz:>7,} Hz  {shape} ===", flush=True)
                if armed:
                    # One square per waveform cycle, so every shape -
                    # including DC, which has no edge of its own - gets a
                    # real trigger rather than AUTO sweep.
                    measure.set_sync(board, "cycle")
                said = measure.set_gen(board, name, pts)
                for line in said.splitlines():
                    if line.startswith("# gen shape"):
                        print(f"    device: {line[2:]}", flush=True)

                def run():
                    board.cmd(preset)
                    time.sleep(args.seconds)

                got = hold_and_measure(inst, args.channel, period,
                                       args.seconds, run, "running",
                                       ext=armed)
                rows.append((name, pts, trig_hz, period, got))
                board.stop()
                board.drain_console(0.2)
                print(f"    off {args.off:g}s", flush=True)
                time.sleep(args.off)
            # Leave the generator as every other tool expects to find it.
            measure.set_gen(board, "sine", measure.GEN_TABLE_POINTS)
        else:
            for name, rc, sps, kw, period in combinations(waveforms, rcs):
                shape = (f"{1/period:,.0f} Hz" if period else "level "
                         f"{DC_CODE}")
                print(f"\n=== {name:6s}  RC {rc:3d}  {sps:>9,} sps  "
                      f"{shape} ===", flush=True)

                def run():
                    measure.run_play(board, dac_sps=sps,
                                     seconds=args.seconds, **kw)

                got = hold_and_measure(inst, args.channel, period,
                                       args.seconds, run, "playing",
                                       ext=armed)
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

    axis = "pts" if args.internal else "RC"
    unit = "trigger" if args.internal else "sps"
    print("\n" + "=" * 78)
    print(f"{'wave':9s} {axis:>4s} {unit:>10s} {'expected':>12s} "
          f"{'measured':>12s} {'Vpp':>8s}")
    print("-" * 78)
    for name, x, sps, period, got in rows:
        exp = f"{1/period:,.0f} Hz" if period else "DC"
        f = got.get("FREQ")
        vpp = got.get("VPP")
        print(f"{name:9s} {x:4d} {sps:10,} {exp:>12s} "
              f"{('-' if f is None else f'{f:,.0f} Hz'):>12s} "
              f"{('-' if vpp is None else f'{vpp:.3f} V'):>8s}")
    print("=" * 78)
    print("A dash under measured is not a failure for DC: the instrument "
          "reports\nno frequency because there is none. It is a failure "
          "for anything else.")


if __name__ == "__main__":
    main()
