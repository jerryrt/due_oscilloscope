"""Device metrics for the DAC, measured with an instrument that is not
the ADC.

Everything this project knew about its own converter came from the
converter under investigation. These four are what a scope can say
instead, and all four need a trigger that does not move: the sync on the
spare DAC pin, through EXT. `docs/awg.md` has why, and the two silent
ways a DS1102E refuses to trigger on it.

    clock    the square at two points a cycle, which is the update
             clock over two and the fastest output on the ADC's timer
    ceiling  the same square with the DAC on its own timer instead,
             swept past the DACC's measured ceiling
    step     full-scale step response - slew rate, overshoot, settling
    skew     the TAG interleave, separated from the instrument's own
             trigger-path delay by measuring it at four rates
    lin      transfer-function linearity across the span, with the
             8-bit ceiling stated rather than pretended away
    wrap     is the PDC reload visible in the analog output (issue #5)

    python3 tools/dso_metrics.py step
    python3 tools/dso_metrics.py skew
    python3 tools/dso_metrics.py lin --average 128
    python3 tools/dso_metrics.py wrap

Wiring, and it is not the old one: CH1 on DAC0, DAC1 into EXT TRIG with
a x1 probe. DAC1 is no longer a channel to look at - the ADC's A1 is
what can still see it.
"""
import argparse
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))

import measure                                                # noqa: E402
import scope as dso                                           # noqa: E402

# Preset 5 is the fastest trigger the capture path will accept -
# (MCK/2)/ACQ_MIN_RC, 39 MHz over 86 - and the internal generator runs
# off the same TIOA0, so it is also the fastest the generator goes on
# this path. Worth having here because the square's ceiling is a
# division of it.
TRIGGER_PRESETS = {50_000: "1", 100_000: "2", 200_000: "3", 400_000: "4",
                   453_488: "5"}

# At two points a cycle the table holds one sample per half cycle, so
# the output toggles on every DAC0 update. Only the square means
# anything there; the rest collapse, and saying which is the difference
# between a screenshot and a mislabelled screenshot.
DEGENERATE_AT_2 = {
    "sine": "flat - both samples land on a zero crossing (Nyquist)",
    "ramp": "collapses to a half-amplitude square: codes 0 and 2048",
    "triangle": "collapses to a full-amplitude square: codes 0 and 4095",
}

# Measured on this bench, and the DAC is not rail to rail: full scale
# lands at 0.52 V and 2.82 V. Used only to turn volts into codes for
# reporting, never to decide anything.
DAC_LO_V, DAC_HI_V = 0.52, 2.82
DAC_SPAN_V = DAC_HI_V - DAC_LO_V
DAC_MID_V = (DAC_LO_V + DAC_HI_V) / 2.0
V_PER_CODE = DAC_SPAN_V / 4095.0


def arm(board, inst, preset, shape="square", pts=32):
    """Start the generator and find the EXT trigger, in that order.

    The autoset looks for an edge, so the output has to be running. Done
    the other way round it searches a dead input and reports a cable
    fault on a good cable - which cost three runs before it was written
    down.
    """
    measure.set_sync(board, "cycle")
    measure.set_gen(board, shape, pts)
    board.cmd(preset)
    time.sleep(1.0)
    board.drain_console(0.3)
    got = inst.ext_trigger_autoset()
    if not got:
        raise SystemExit(
            "EXT did not trigger at any level. No signal is reaching it: "
            "check the cable to EXT TRIG, and that the sync is on (=1J).")
    print(f"EXT trigger: {got['coupling']} coupled, level "
          f"{got['level']:+.2f} V", flush=True)
    return got


def capture(inst, ch, average=0):
    """One averaged trace, and the seconds-per-sample that go with it.

    Averaging is only meaningful because the trigger does not move. On a
    signal-triggered setup the same averaging smears the edge by exactly
    the trigger jitter - up to 90 us on a sine here - and turns a
    measurement of the converter into a measurement of the trigger.
    """
    if average:
        inst.averaging(average)
        time.sleep(0.1 + average * 0.01)
    else:
        inst.averaging(None)
        time.sleep(0.2)
    v = inst.waveform(ch)
    dt = inst.timebase() * 12.0 / max(1, len(v))
    return v, dt


def edges(v, lo, hi, frac):
    """Indices where the trace crosses lo + frac*(hi-lo), rising."""
    lvl = lo + frac * (hi - lo)
    out = []
    for i in range(1, len(v)):
        a, b = v[i - 1], v[i]
        if a < lvl <= b:
            out.append(i - 1 + (lvl - a) / (b - a) if b != a else i)
    return out


# ------------------------------------------------------------------
# step: what a full-scale transition actually looks like
# ------------------------------------------------------------------

def _edge_time(inst, ch, average):
    """Seconds from the trigger point to the first rising mid crossing,
    or None if the record holds no edge."""
    v, dt = capture(inst, ch, average)
    if not v:
        return None
    lo, hi = min(v), max(v)
    if hi - lo < 0.5:
        return None
    e = edges(v, lo, hi, 0.5)
    if not e:
        return None
    centre = len(v) / 2.0
    return (min(e, key=lambda x: abs(x - centre)) - centre) * dt


def cmd_step(board, inst, args):
    """Slew rate, overshoot and settling on a full-scale step.

    A sine never asks the converter for a step, so however fast it is
    played the settling behaviour never appears in the output. A square
    asks for one twice a cycle. Four points per cycle keeps DAC0 at each
    rail for two trigger periods, which is long enough for the tail to
    finish before the next edge.
    """
    preset = TRIGGER_PRESETS[args.trigger]
    arm(board, inst, preset, "square", args.points)
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")

    # Find the edge before zooming on it.
    #
    # DAC0 leads its own sync by one trigger period - the TAG interleave
    # - so the edge is not at the trigger point, and at 0.2 us/div the
    # whole 2.4 us window fits inside one flat level. Guessing an offset
    # put the edge off screen at every zoom and reported "20 mV step",
    # which is the noise. So: locate it at a timebase that covers a
    # whole cycle, learn the instrument's offset sign from a probe move,
    # and only then zoom.
    out_hz = measure.gen_output_hz(args.trigger, args.points)
    coarse = 1.0 / out_hz / 8.0
    inst.timebase(coarse)
    inst.timebase_offset(0.0)
    te = _edge_time(inst, args.channel, args.average)
    if te is None:
        raise SystemExit("no rising edge at the coarse timebase; is the "
                         "output running?")
    probe = coarse
    inst.timebase_offset(probe)
    te2 = _edge_time(inst, args.channel, args.average)
    inst.timebase_offset(0.0)
    # An event at a fixed time appears at screen position (te - offset)
    # when a positive offset means "the screen centre is later", so the
    # observed shift is the negative of the applied one. The multiplier
    # that puts the edge four divisions left of centre is therefore
    # -sign(shift), and getting that backwards moves the view away from
    # the edge instead of onto it - which reads as "no step on screen".
    if te2 is None:
        sign = 1.0
        print("could not learn the offset sign; assuming a positive "
              "offset moves the screen centre later")
    else:
        sign = -1.0 if (te2 - te) > 0 else 1.0
    print(f"DAC0 edge sits {te*1e6:+.3f} us from the sync "
          f"(one trigger period is {1e6/args.trigger:.2f} us)")

    print(f"\n{'us/div':>8s} {'rise 10-90%':>12s} {'slew':>12s} "
          f"{'overshoot':>11s} {'settle to 1%':>13s}")
    print("-" * 62)
    step = 0.0
    for tb in args.timebase:
        inst.timebase(tb)
        # Put the edge four divisions left of centre, so most of the
        # record is the settling being measured.
        want = sign * (te + tb * 4.0)
        got_off = inst.timebase_offset(want)
        if abs(got_off - want) > max(1e-9, abs(want) * 0.05):
            # The instrument clamps the offset range per timebase and
            # says so only in the readback. Without this the zoom lands
            # somewhere else and the numbers describe a flat level.
            print(f"{tb*1e6:8.2f}  offset clamped: asked "
                  f"{want*1e6:+.3f}us, got {got_off*1e6:+.3f}us")
        v, dt = capture(inst, args.channel, args.average)
        if not v:
            print(f"{tb*1e6:8.2f}  no trace"); continue
        lo, hi = min(v), max(v)
        step = hi - lo
        if step < 0.5:
            print(f"{tb*1e6:8.2f}  no step on screen ({step*1000:.0f} mV)")
            continue
        e10 = edges(v, lo, hi, 0.10)
        e90 = edges(v, lo, hi, 0.90)
        if not e10 or not e90:
            print(f"{tb*1e6:8.2f}  no rising edge found"); continue
        t10, t90 = e10[0] * dt, e90[0] * dt
        rise = t90 - t10
        slew = (0.8 * step) / rise if rise > 0 else float("nan")
        # The flat top after the edge, and the worst excursion in it.
        start = int(e90[0]) + 1
        tail = v[start:]
        if len(tail) < 8:
            print(f"{tb*1e6:8.2f}  edge too close to the screen edge")
            continue
        final = statistics.median(tail[len(tail) // 2:])
        over = (max(tail) - final) / step * 100.0
        band = 0.01 * step
        settle = None
        for i in range(len(tail) - 1, -1, -1):
            if abs(tail[i] - final) > band:
                settle = (i + 1) * dt
                break
        # A settling time longer than the window is not a settling time,
        # it is the window. Reporting the number anyway makes it look
        # like a measurement that shortens as you zoom in - which is
        # exactly what the first run of this printed.
        window = len(tail) * dt
        if settle is not None and settle > 0.9 * window:
            shown = f">{window*1e9:.0f}ns"
        elif settle is None:
            shown = "-"
        else:
            shown = f"{settle*1e9:.0f}ns"
        print(f"{tb*1e6:8.2f} {rise*1e9:10.0f}ns "
              f"{slew/1e6:9.3f}V/us {over:10.2f}% {shown:>13s}",
              flush=True)
    print(f"\nStep was {step*1000:.0f} mV = {step/V_PER_CODE:.0f} codes.")
    print(f"1% of it is {step*10:.0f} mV, against ~20 mV RMS of noise on "
          f"the pin - so the 1%\nband needs the averaging to be doing "
          f"its job, and a '>' means the tail never\nleft the band "
          f"within the record rather than that it settled at the edge.")
    print(f"\nThe number that matters elsewhere: a full-scale step takes "
          f"about {rise*1e9:.0f} ns to\ngo 10-90%. The DACC's own "
          f"ceiling is 1,392,857 updates/s, which is 718 ns per\nupdate "
          f"with both channels interleaved - so at the top of the ladder "
          f"a full-scale\nstep does not finish before the next one is "
          f"due. That is a property of the\nconverter, not of the feed.")


# ------------------------------------------------------------------
# skew: the TAG interleave, separated from the instrument
# ------------------------------------------------------------------

def cmd_skew(board, inst, args):
    """How far DAC0 leads its own sync, and what that is made of.

    DACC TAG mode interleaves the two channels on one PDC stream, so the
    sample the table holds at index i reaches DAC0 one trigger period
    before it reaches DAC1. The sync therefore lags the waveform by
    exactly one trigger period - in principle.

    In practice a scope adds its own delay between the EXT trigger path
    and the channel path, and that delay is not calibrated and does not
    depend on the rate. So the two are separated by measuring at four
    rates: the part that scales with 1/trigger is the interleave, in
    units of trigger periods, and the constant part is the instrument's.
    A single-rate measurement cannot tell them apart and would report
    the sum as if it were the device's.
    """
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    rows = []
    print(f"\n{'trigger':>9s} {'period':>9s} {'DAC0 edge vs sync':>14s} "
          f"{'ratio':>15s}")
    print("-" * 72)
    # Hold the *waveform* frequency constant while the trigger rate
    # varies, by scaling the resolution with it.
    #
    # The EXT trigger has to be AC coupled - the DAC's 1.67 V midpoint
    # is past the input's 1.2 V clamp - and an AC-coupled comparator
    # shifts its crossing by an amount that depends on the signal's
    # frequency. Sweeping the trigger rate at a fixed resolution sweeps
    # the sync frequency with it, so that shift lands differently at
    # every point and contaminates the very fit that is supposed to
    # separate the instrument from the device. Measured: 50 kHz read
    # -1.55 trigger periods while 100/200/400 kHz all read about -1.07.
    #
    # At a constant sync frequency the shift is the same at every point,
    # so it moves into the intercept with the rest of the instrument's
    # delay and leaves the slope alone.
    base_hz, base_pts = min(TRIGGER_PRESETS), 4
    for hz, preset in sorted(TRIGGER_PRESETS.items()):
        if args.trigger_list and hz not in args.trigger_list:
            continue
        pts = measure.gen_points_for(base_pts * hz // base_hz)
        arm(board, inst, preset, "square", pts)
        out_hz = measure.gen_output_hz(hz, pts)
        inst.timebase(1.0 / out_hz / 12.0)
        inst.timebase_offset(0.0)
        v, dt = capture(inst, args.channel, args.average)
        if not v:
            continue
        lo, hi = min(v), max(v)
        if hi - lo < 0.5:
            print(f"{hz:9,} no step"); continue
        e = edges(v, lo, hi, 0.5)
        if not e:
            print(f"{hz:9,} no edge"); continue
        centre = len(v) / 2.0
        # The trigger sits at screen centre, so an edge's offset from
        # centre is its time relative to the sync.
        off = min(e, key=lambda x: abs(x - centre))
        skew = (off - centre) * dt
        period = 1.0 / hz
        rows.append((hz, period, skew))
        print(f"{hz:9,} {period*1e6:8.2f}us {skew*1e6:12.3f}us "
              f"{skew/period:7.3f} periods   sync {out_hz:,.0f} Hz",
              flush=True)
        board.stop(); board.drain_console(0.2)
    if len(rows) < 2:
        print("\nNeed at least two rates to separate the two terms.")
        return
    # Least squares of skew against the trigger period.
    xs = [p for _, p, _ in rows]
    ys = [s for _, _, s in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((xs[i] - mx) * (ys[i] - my)
                for i in range(len(xs))) / den if den else float("nan")
    icept = my - slope * mx
    print(f"\nskew = {slope:+.3f} x (trigger period) {icept*1e9:+.0f} ns")
    print(f"  the rate-dependent term is the interleave: "
          f"{slope:+.3f} trigger periods")
    print(f"  the constant term is the instrument's trigger-path delay: "
          f"{icept*1e9:+.0f} ns")
    print(f"  TAG interleave predicts exactly -1.000 trigger periods "
          f"(DAC0 leads DAC1)")


# ------------------------------------------------------------------
# lin: transfer-function linearity, honestly bounded
# ------------------------------------------------------------------

def cmd_lin(board, inst, args):
    """Deviation from a straight line, measured in vertical slices.

    What defeats the obvious version. The instrument digitises the whole
    screen to 8 bits, so at 0.5 V/div one level is about 28 DAC codes,
    and `:WAV:DATA?` hands back those levels - the averaging happens
    before the quantiser, so it beats the noise down and does nothing
    about the step size. Run across the full 2.3 V span it reports an
    rms deviation of ~30 codes, which is one screen level: the number is
    the ruler, not the converter. That is what the first version of this
    printed.

    So the span is measured a slice at a time. The ramp is monotonic, so
    a *time* window selects a *code* window: put a fraction of one ramp
    on screen and the vertical gain can come up by the same factor
    without clipping. Eight slices at 0.2 V/div puts one screen level at
    about 11 codes, and the residual within a slice is then a statement
    about the converter over that part of its range.

    Still integral linearity over a slice, not per-code DNL. A 12-bit
    DNL needs an instrument with more than 8 bits; this says how
    straight the transfer function is, and where it is not.
    """
    preset = TRIGGER_PRESETS[args.trigger]
    arm(board, inst, preset, "ramp", args.points)
    out_hz = measure.gen_output_hz(args.trigger, args.points)
    period = 1.0 / out_hz
    inst.coupling(args.channel, "DC")
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)

    # Where the ramp starts, relative to the sync, so the slices can be
    # placed on the monotonic run rather than across its wrap.
    inst.timebase(period / 12.0)
    inst.timebase_offset(0.0)
    v, dt = capture(inst, args.channel, args.average)
    if not v:
        raise SystemExit("no trace")
    lo_v, hi_v = min(v), max(v)
    span = hi_v - lo_v
    drop = None
    for i in range(1, len(v)):
        if v[i] - v[i - 1] < -span * 0.4:
            drop = i
            break
    if drop is None:
        raise SystemExit("no ramp wrap found; is the shape a ramp?")
    centre = len(v) / 2.0
    t_wrap = (drop - centre) * dt

    n_slices = args.slices
    vdiv = args.vdiv or 0.2
    print(f"\nramp {out_hz:,.0f} Hz, {args.points} pts/cycle, "
          f"span {span*1000:.0f} mV = {span/V_PER_CODE:.0f} codes")
    print(f"{n_slices} slices, {vdiv:g} V/div, averaged "
          f"{args.average or 1}x")
    print(f"one 8-bit screen level = {vdiv*8/256/V_PER_CODE:.1f} DAC "
          f"codes at this gain\n")
    print(f"{'slice':>5s} {'codes covered':>18s} {'rms dev':>16s} "
          f"{'worst dev':>16s} {'non-mono':>9s}")
    print("-" * 70)
    inst.channel_scale(args.channel, vdiv)
    slice_s = period / n_slices
    worst_all, rms_all = 0.0, []
    for k in range(n_slices):
        # The middle of this slice, in time and so in code.
        t_mid = t_wrap + slice_s * (k + 0.5)
        frac = (k + 0.5) / n_slices
        v_mid = lo_v + span * frac
        inst.channel_offset(args.channel, -v_mid)
        inst.timebase(slice_s / 12.0)
        inst.timebase_offset(t_mid)
        vv, ddt = capture(inst, args.channel, args.average)
        if not vv or len(vv) < 32:
            print(f"{k:5d}  no trace"); continue
        # Reject a slice that clipped or caught the wrap.
        d = [vv[i] - vv[i - 1] for i in range(1, len(vv))]
        if min(d) < -span * 0.2:
            print(f"{k:5d}  slice caught the wrap; skipped"); continue
        n = len(vv)
        mx = (n - 1) / 2.0
        my = sum(vv) / n
        den = sum((i - mx) ** 2 for i in range(n))
        if den == 0:
            continue
        slope = sum((i - mx) * (vv[i] - my) for i in range(n)) / den
        resid = [vv[i] - (my + slope * (i - mx)) for i in range(n)]
        worst = max(resid, key=abs)
        rms = math.sqrt(sum(r * r for r in resid) / n)
        rms_all.append(rms)
        worst_all = max(worst_all, abs(worst))
        nonmono = sum(1 for i in range(1, n) if vv[i] < vv[i - 1] - 1e-3)
        c0 = (min(vv) - lo_v) / V_PER_CODE
        c1 = (max(vv) - lo_v) / V_PER_CODE
        print(f"{k:5d} {c0:8.0f}..{c1:<8.0f} "
              f"{rms*1000:7.2f}mV {rms/V_PER_CODE:5.2f}c "
              f"{worst*1000:+7.2f}mV {worst/V_PER_CODE:+5.2f}c "
              f"{nonmono:9d}", flush=True)
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.timebase_offset(0.0)
    if rms_all:
        m = statistics.median(rms_all)
        print(f"\nmedian rms deviation across slices "
              f"{m*1000:.2f} mV = {m/V_PER_CODE:.2f} codes")
        print(f"worst single deviation            "
              f"{worst_all*1000:.2f} mV = {worst_all/V_PER_CODE:.2f} codes")
        floor = vdiv * 8 / 256 / V_PER_CODE
        print(f"\nThe instrument's own floor here is {floor:.1f} codes per "
              f"screen level. A result at or\nbelow that is the ruler "
              f"and not the converter - lower --vdiv and raise --slices\n"
              f"until the number stops following the gain, or use a meter.")


# ------------------------------------------------------------------
# wrap: is the PDC reload visible in the analog output
# ------------------------------------------------------------------

def cmd_wrap(board, inst, args):
    """Does the table wrap show up on the pin?

    The generator's PDC reload has been exactly one waveform period in
    every build this project has run, so "follows the table" and
    "follows the waveform" have never been separable - which is the
    whole reason GEN_LAYOUT_TWOCYCLE exists. The resolution knob
    separates them too, and more generally: at N points per cycle the
    table holds 256/N cycles, and any artifact locked to the *reload*
    appears once per 256/N cycles rather than once per cycle.

    So: trigger on the wrap sync, average, and compare the residual at
    the wrap against the residual everywhere else. Issue #5's signature
    is a metronome at the table length, and this is that question asked
    of the analog pin instead of the ADC.
    """
    preset = TRIGGER_PRESETS[args.trigger]
    measure.set_sync(board, "wrap")
    measure.set_gen(board, "sine", args.points)
    board.cmd(preset)
    time.sleep(1.0); board.drain_console(0.3)
    got = inst.ext_trigger_autoset()
    if not got:
        raise SystemExit("EXT did not trigger; check the cable and =2J")
    print(f"EXT trigger: {got['coupling']} coupled, level "
          f"{got['level']:+.2f} V", flush=True)
    cycles = measure.GEN_TABLE_POINTS // measure.gen_points_for(args.points)
    out_hz = measure.gen_output_hz(args.trigger, args.points)
    wrap_hz = out_hz / cycles
    print(f"{args.points} pts/cycle -> {cycles} cycles per table wrap, "
          f"waveform {out_hz:,.0f} Hz, wrap {wrap_hz:,.1f} Hz")
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    inst.timebase(1.0 / wrap_hz / 12.0)
    inst.timebase_offset(0.0)
    v, dt = capture(inst, args.channel, args.average)
    inst.averaging(None)
    if not v:
        raise SystemExit("no trace")
    n = len(v)
    # From the timebase the instrument ADOPTED, not the one requested.
    # A DS1102E snaps the timebase to a 1-2-5 ladder, so the screen does
    # not hold the whole number of cycles the request implied - and
    # folding at n/cycles then folds at the wrong period and reports the
    # waveform's own swing as if it were cycle-to-cycle spread. That is
    # what the first run of this printed: 602 mV of "spread" on a clean
    # sine.
    per = (1.0 / out_hz) / dt
    cycles_seen = n / per
    print(f"screen holds {cycles_seen:.2f} cycles at the adopted "
          f"{inst.timebase()*1e6:.1f} us/div")
    if per < 8:
        raise SystemExit(f"only {per:.1f} screen points per cycle; "
                         f"use fewer points per cycle")
    # Fold the record at the cycle period. A defect locked to the wrap
    # survives folding at the wrap and not at the cycle; one locked to
    # the cycle does the opposite.
    nbins = int(per)
    folded = [[] for _ in range(nbins)]
    for i, x in enumerate(v):
        # Fold on the real period, so a bin collects one phase and not a
        # slowly-sliding one.
        folded[int((i % per))].append(x)
    spread = [statistics.pstdev(b) if len(b) > 1 else 0.0 for b in folded]
    med = statistics.median(spread)
    worst_i = max(range(len(spread)), key=lambda i: spread[i])
    print(f"\nfolded at the cycle, {cycles_seen:.2f} cycles deep, "
          f"{nbins} bins")
    print(f"  median bin spread {med*1000:6.2f} mV = "
          f"{med/V_PER_CODE:5.2f} codes")
    print(f"  worst bin  {worst_i:3d}   {spread[worst_i]*1000:6.2f} mV = "
          f"{spread[worst_i]/V_PER_CODE:5.2f} codes  "
          f"({spread[worst_i]/med if med else float('nan'):.1f}x median)")
    print(f"\nA cycle that differs from its neighbours only at the wrap "
          f"shows up here as\none bin far above the median. Even spread "
          f"means the reload is not visible\nat this gain - which is a "
          f"bound, not an absence: {med/V_PER_CODE:.2f} codes is what "
          f"this\nsetup can see.")


# ------------------------------------------------------------------
# clock: the square at two points, which is the update clock
# ------------------------------------------------------------------

def cmd_clock(board, inst, args):
    """The highest frequency this converter can put on a pin, and where
    it stops being a square.

    Two points a cycle is not "the coarsest resolution", it is a
    different thing: the table holds one sample per half cycle, so the
    output toggles on every DAC0 update and the waveform *is* the update
    clock divided by two. Nothing faster exists on this path - a third
    point per cycle would be a slower wave, not a faster one.

    TAG mode spends every other update on DAC1, so DAC0 updates at
    trigger/2 and the square lands at trigger/4. That is the ceiling
    with a sync running; giving up the sync and tagging every sample for
    DAC0 would double it, which is what the streamed path already does
    and is a trade rather than a bug.

    What the sweep is for: the step response says a full-scale
    transition takes 789-938 ns to go 10-90%, so as the half period
    closes on that the amplitude has to fall. This finds where.
    """
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    inst.averaging(None)
    rows = []
    print(f"\n{'trigger':>9s} {'DAC0 updates':>13s} {'half period':>12s} "
          f"{'expected':>11s} {'measured':>11s} {'Vpp':>8s} {'of max':>7s}")
    print("-" * 80)
    for hz, preset in sorted(TRIGGER_PRESETS.items()):
        if args.trigger_list and hz not in args.trigger_list:
            continue
        arm(board, inst, preset, "square", 2)
        want = measure.gen_output_hz(hz, 2)
        inst.timebase(3.0 / want / 12.0)
        inst.timebase_offset(0.0)
        inst.menu_display(False)
        inst.run()
        time.sleep(0.6)
        g = inst.measure_all(args.channel, names=("VPP", "FREQ"))
        vpp, f = g.get("VPP"), g.get("FREQ")
        rows.append((hz, want, f, vpp))
        board.stop(); board.drain_console(0.2)
    if not rows:
        return
    ref = max((v for _, _, _, v in rows if v), default=None)
    for hz, want, f, vpp in rows:
        half_us = 1e6 / (2.0 * want)
        pct = (vpp / ref * 100.0) if (vpp and ref) else float("nan")
        print(f"{hz:9,} {hz//2:11,}/s {half_us:10.2f}us "
              f"{want:9,.0f}Hz "
              f"{('-' if f is None else f'{f:,.0f}Hz'):>11s} "
              f"{('-' if vpp is None else f'{vpp:.3f}V'):>8s} "
              f"{pct:6.1f}%", flush=True)
    print(f"\nThe square at two points is the DAC0 update clock over two, "
          f"and nothing on this\npath is faster. A full-scale step needs "
          f"789-938 ns to go 10-90% (dso_metrics step),\nso amplitude "
          f"holds while the half period is comfortably above that and "
          f"falls when\nit is not - that is the converter, not the "
          f"table.")


# ------------------------------------------------------------------
# ceiling: how far the DAC really goes, off the ADC's leash
# ------------------------------------------------------------------

# The DACC's own measured update ceiling. RC 28 on the playback path is
# 1,392,857 updates/s and the converter needs about 54.7 MCK cycles for
# each, so faster is not a rate it can make - the trigger will run there
# happily and the DAC simply will not keep up. See drivers/play.h.
DACC_CEILING_HZ = 1_392_857

# What `clock` can reach, and why it is not the DAC's limit: the
# internal generator runs off TIOA0, the ADC's trigger, so it inherits
# the ADC's in-spec floor of ACQ_MIN_RC = 86 -> 453,488 Hz.
GEN_TIOA0_MAX_HZ = 453_488


def cmd_ceiling(board, inst, args):
    """The square's real ceiling, with the DAC on its own timer.

    `clock` tops out at 113 kHz and that is the *ADC's* limit, not the
    converter's: every ordinary path leaves the DACC triggered from
    TIOA0 so that generation and capture are phase-coherent, and TIOA0
    is capped at 453,488 Hz by ACQ_MIN_RC. The DACC's own measured
    ceiling is 1,392,857 updates/s - three times higher - and `=<dac>M`
    is the one path that selects TIOA1 and asks for an arbitrary rate.

    So this sweeps past both, with the square at two points a cycle, and
    watches for the two different ways it can stop working: the trigger
    outrunning the converter (amplitude collapses, the DACC cannot
    convert that fast) and the analog slew running out (amplitude falls
    smoothly as the half period closes on the 789-938 ns rise time).
    They look different and the sweep is wide enough to show which.
    """
    solo = args.solo
    measure.set_sync(board, "solo" if solo else "cycle")
    measure.set_gen(board, "square", 2)
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    inst.averaging(None)
    print(f"\nDACC measured ceiling {DACC_CEILING_HZ:,} updates/s; "
          f"TIOA0 caps the generator at {GEN_TIOA0_MAX_HZ:,}")
    div = 2 if solo else 4
    if solo:
        print(f"SOLO: every table entry tagged DAC0, so DAC0 updates on "
              f"every trigger and the\nsquare lands at dac_hz / 2. No "
              f"sync, so the scope triggers on the signal - which for a "
              f"square\nis the best trigger available anyway (0.007 us "
              f"of jitter, against the sync's 1.471).\n")
    else:
        print(f"square at 2 pts = dac_hz / 4, because TAG spends every "
              f"other update on DAC1\n")
    print(f"{'dac_hz':>10s} {'DAC0 upd':>11s} {'half per':>10s} "
          f"{'expected':>11s} {'measured':>11s} {'Vpp':>8s} {'of max':>7s} "
          f"{'note'}")
    print("-" * 92)
    rows = []
    for dac_hz in args.rates:
        board.stop(); board.drain_console(0.2)
        board.cmd(f"={dac_hz},200000,2M")
        time.sleep(1.0); board.drain_console(0.4)
        want = dac_hz / float(div)
        inst.timebase(3.0 / want / 12.0)
        inst.timebase_offset(0.0)
        got = None if solo else inst.ext_trigger_autoset()
        if not got:
            # No sync edge the instrument can find. Fall back to the
            # signal itself: a square is the one shape whose own edge
            # triggers as well as a sync does.
            inst.trigger_coupling("DC")
            inst.trigger_edge(source=f"CHAN{args.channel}", slope="POS",
                              level=DAC_MID_V, sweep="NORMAL")
        inst.menu_display(False)
        inst.run()
        time.sleep(0.6)
        g = inst.measure_all(args.channel, names=("VPP", "FREQ"))
        rows.append((dac_hz, want, g.get("FREQ"), g.get("VPP"),
                     bool(got)))
    board.stop(); board.drain_console(0.3)
    ref = max((v for _, _, _, v, _ in rows if v), default=None)
    for dac_hz, want, f, vpp, synced in rows:
        half_us = 1e6 / (2.0 * want)
        pct = (vpp / ref * 100.0) if (vpp and ref) else float("nan")
        note = []
        if dac_hz > DACC_CEILING_HZ:
            note.append("past the DACC ceiling")
        if half_us < 0.938:
            note.append("half period < rise time")
        elif half_us < 2.0:
            note.append("half period < 2x rise")
        if not synced and not solo:
            note.append("triggered on the signal, no sync edge")
        upd = dac_hz if solo else dac_hz // 2
        print(f"{dac_hz:10,} {upd:9,}/s {half_us:8.3f}us "
              f"{want:9,.0f}Hz "
              f"{('-' if f is None else f'{f:,.0f}Hz'):>11s} "
              f"{('-' if vpp is None else f'{vpp:.3f}V'):>8s} "
              f"{pct:6.1f}% {'; '.join(note)}", flush=True)
    print(f"\nTwo different failures to tell apart. The converter "
          f"outrun: past {DACC_CEILING_HZ:,}\nupdates/s the DACC cannot "
          f"convert in time and the output stops following the table at "
          f"all.\nThe analog slew: a full-scale step needs 789-938 ns to "
          f"go 10-90%, so amplitude\nfalls smoothly once the half period "
          f"closes on that - around 530-630 kHz of square.")


# ------------------------------------------------------------------
# shots: what each waveform actually looks like, at three zooms
# ------------------------------------------------------------------

# One cycle shows the shape and its staircase; five shows whether it is
# the *same* shape each time; ten shows the envelope. A defect that only
# appears at one of those three is common - a wrap artifact hides inside
# one cycle, and a staircase disappears at ten.
SHOT_CYCLES = (1, 5, 10)


def shots_solo(board, inst, args):
    """The clock square at the hardware's own limit, off every leash.

    Solo, so DAC0 updates on every trigger; two points a cycle, so it
    toggles on every update; and `=<dac>M` so the rate is the DAC's own
    timer rather than the ADC's. That is every constraint removed except
    the converter itself, and the pictures are what the converter does
    as it runs out - which is the point of taking them rather than only
    tabulating Vpp, because "amplitude fell to 68%" and "the square
    became a triangle" are the same number and different findings.

    No sync exists in solo, so the scope triggers on the signal. For a
    square that is the best trigger available anyway: measured, its own
    edge gives 0.007 us of jitter against the sync's 1.471.
    """
    measure.set_sync(board, "solo")
    measure.set_gen(board, "square", 2)
    inst.channel_enable(2, False)
    inst.channel_enable(args.channel, True)
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    inst.averaging(None)
    inst.trigger_coupling("DC")

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    shots = []
    for dac_hz in args.dac_hz:
        board.stop(); board.drain_console(0.2)
        board.cmd(f"={dac_hz},200000,2M")
        time.sleep(1.0); board.drain_console(0.4)
        hz = dac_hz / 2.0
        inst.trigger_edge(source=f"CHAN{args.channel}", slope="POS",
                          level=DAC_MID_V, sweep="NORMAL")
        for cyc in SHOT_CYCLES:
            inst.timebase(cyc / hz / 12.0)
            tb = inst.timebase()
            shown = tb * 12.0 * hz
            inst.timebase_offset(0.0)
            inst.menu_display(False)
            inst.run()
            time.sleep(0.6)
            ok = inst.triggered()
            g = inst.measure_all(args.channel, names=("VPP", "FREQ"))
            png = inst.screenshot()
            name = f"clock_{dac_hz//1000:04d}k_{hz/1000:.0f}kHz_{cyc:02d}cyc.png"
            with open(os.path.join(out, name), "wb") as f:
                f.write(png)
            shots.append({"shape": "square", "points": 2, "solo": True,
                          "dac_hz": dac_hz, "hz": hz, "is_clock": True,
                          "cycles_asked": cyc, "cycles_shown": shown,
                          "timebase_s": tb, "file": name,
                          "bytes": len(png), "triggered": ok,
                          "vpp": g.get("VPP"), "freq": g.get("FREQ")})
            print(f"  {name:40s} {len(png):6d} B  {tb*1e9:8.0f}ns/div  "
                  f"Vpp {g.get('VPP')}  f {g.get('FREQ')}  "
                  f"{'triggered' if ok else 'NOT TRIGGERED'}", flush=True)
    board.stop(); board.drain_console(0.3)
    import json
    with open(os.path.join(out, "shots_solo.json"), "w") as f:
        json.dump({"solo": True, "shots": shots}, f, indent=1)
    print(f"\n{len(shots)} solo shots in {out}")


def cmd_shots(board, inst, args):
    """One screenshot per waveform, per frequency, per zoom.

    The instrument's own screen rather than a re-plot of :WAV:DATA?,
    because they are not the same picture: the screen carries the
    graticule, the trigger marker, the scale factors and the on-screen
    measurements, and those are most of what makes a screenshot worth
    keeping when someone reads it a month later.

    Frequency comes from the resolution, because that is how the
    internal generator's frequency works - the trigger fixes the update
    rate and points-per-cycle decides how many updates a cycle spends.
    So the sweep over resolutions is a sweep over frequency AND over
    staircase coarseness at once, which is worth seeing in one place.
    """
    if args.dac_hz:
        return shots_solo(board, inst, args)
    preset = TRIGGER_PRESETS[args.trigger]
    arm(board, inst, preset, "square", 32)
    # An unconnected CH2 draws a flat line that a reader cannot tell
    # from a real signal that happens to be flat. DAC1 is on EXT now.
    inst.channel_enable(2, False)
    # Every SCPI write that touches a menu leaves it on screen, covering
    # about a fifth of the graticule - so a shot taken right after
    # setting the timebase has the timebase menu sitting over the
    # right-hand divisions of the trace. The first sweep produced 48 of
    # those before anyone looked at one.
    inst.menu_display(False)
    inst.channel_enable(args.channel, True)
    inst.channel_scale(args.channel, 0.5)
    inst.channel_offset(args.channel, -DAC_MID_V)
    inst.coupling(args.channel, "DC")
    inst.averaging(None)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    shots = []
    for shape in args.shape:
        for pts in args.points_list:
            p = measure.gen_points_for(pts)
            if p == 2 and shape in DEGENERATE_AT_2:
                # Captured anyway for square; for the others the shot
                # would be a square with the wrong name on it.
                print(f"  skipping {shape} at 2 pts: "
                      f"{DEGENERATE_AT_2[shape]}")
                continue
            hz = measure.gen_output_hz(args.trigger, p)
            measure.set_gen(board, shape, p)
            board.cmd(preset)
            time.sleep(0.6)
            board.drain_console(0.2)
            for cyc in SHOT_CYCLES:
                # Ask for the timebase that shows `cyc` cycles, then
                # record what the instrument adopted. A DS1102E snaps to
                # a 1-2-5 ladder, so "5 cycles" is a request and 7.5 is
                # what arrives - and a caption that says 5 is wrong
                # about the picture it is under.
                inst.timebase(cyc / hz / 12.0)
                tb = inst.timebase()
                shown = tb * 12.0 * hz
                inst.timebase_offset(0.0)
                inst.menu_display(False)
                inst.run()
                time.sleep(0.5)
                ok = inst.triggered()
                png = inst.screenshot()
                name = f"{shape}_{p:03d}pts_{hz:.0f}Hz_{cyc:02d}cyc.png"
                with open(os.path.join(out, name), "wb") as f:
                    f.write(png)
                shots.append({"shape": shape, "points": p, "hz": hz,
                              "is_clock": p == 2,
                              "cycles_asked": cyc, "cycles_shown": shown,
                              "timebase_s": tb, "file": name,
                              "bytes": len(png), "triggered": ok})
                print(f"  {name:44s} {len(png):6d} B  "
                      f"{tb*1e6:8.2f}us/div  {shown:5.2f} cycles  "
                      f"{'triggered' if ok else 'NOT TRIGGERED'}",
                      flush=True)
            board.stop(); board.drain_console(0.2)
    import json
    with open(os.path.join(out, "shots.json"), "w") as f:
        json.dump({"trigger_hz": args.trigger, "channel": args.channel,
                   "shots": shots}, f, indent=1)
    n_bad = sum(1 for x in shots if not x["triggered"])
    print(f"\n{len(shots)} shots in {out}")
    print(f"{n_bad} did not trigger" if n_bad
          else "every shot triggered")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("step", "skew", "lin", "wrap",
                                    "clock", "ceiling", "shots"))
    ap.add_argument("--channel", type=int, default=1,
                    help="scope channel on DAC0 (default 1). DAC1 is the "
                         "trigger and is not a channel to measure")
    ap.add_argument("--trigger", type=int, default=200_000,
                    choices=sorted(TRIGGER_PRESETS))
    ap.add_argument("--trigger-list", type=int, action="append", default=[],
                    help="skew only: restrict which rates are swept")
    ap.add_argument("--points", type=int, default=None,
                    help="generator resolution; per-command default")
    ap.add_argument("--average", type=int, default=64,
                    help="acquisitions to average (default 64). Only "
                         "meaningful on a trigger that does not move")
    ap.add_argument("--timebase", type=float, action="append", default=[],
                    help="step only: seconds/div, repeatable")
    ap.add_argument("--slices", type=int, default=8,
                    help="lin only: vertical slices across the span "
                         "(default 8). More slices means more gain and a "
                         "finer ruler")
    ap.add_argument("--vdiv", type=float, default=None,
                    help="lin only: volts/div within a slice "
                         "(default 0.2)")
    ap.add_argument("--shape", action="append", default=[],
                    choices=("sine", "square", "ramp", "triangle"),
                    help="shots only: repeatable; default all four")
    ap.add_argument("--points-list", action="append", type=int, default=[],
                    help="shots only: resolutions, and so frequencies, "
                         "repeatable (default 256 64 16 4)")
    ap.add_argument("--out", default="shots",
                    help="shots only: directory for the PNGs")
    ap.add_argument("--rates", action="append", type=int, default=[],
                    help="ceiling only: DAC update rates to sweep, "
                         "repeatable")
    ap.add_argument("--dac-hz", action="append", type=int, default=[],
                    help="shots only: capture the solo clock square at "
                         "these DAC update rates, via =<dac>M, instead of "
                         "sweeping resolutions")
    ap.add_argument("--solo", action="store_true",
                    help="ceiling only: give up DAC1 and the sync, so "
                         "DAC0 updates every trigger and the output "
                         "frequency doubles")
    args = ap.parse_args()

    if not args.shape:
        args.shape = ["sine", "square", "ramp", "triangle"]
    if not args.points_list:
        # 2 is the top rung and is not optional: it is the update clock
        # over two, the fastest thing the converter can be asked for,
        # and leaving it out stops the sweep one step short of the
        # ceiling it exists to show.
        args.points_list = [256, 64, 16, 4, 2]

    if not args.rates:
        # Through the generator's TIOA0 cap, through the DACC's own
        # measured ceiling, and out the far side, so both failures are
        # in one table.
        args.rates = [400_000, 800_000, 1_200_000, 1_392_857, 1_800_000,
                      2_200_000, 2_800_000, 3_600_000]

    defaults = {"step": 4, "skew": 4, "lin": 256, "wrap": 32,
                "clock": 2, "ceiling": 2, "shots": 32}
    if args.points is None:
        args.points = defaults[args.what]
    if args.what == "step" and not args.timebase:
        args.timebase = [1e-6, 500e-9, 200e-9]

    inst = dso.open_scope()
    print(f"scope: {' '.join(inst.identify())}")
    print(f"probe on CH{args.channel}: x{inst.probe(args.channel):g} "
          f"- what the scope has been TOLD, not what is fitted")
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        {"step": cmd_step, "skew": cmd_skew, "lin": cmd_lin,
         "wrap": cmd_wrap, "clock": cmd_clock,
         "ceiling": cmd_ceiling,
         "shots": cmd_shots}[args.what](board, inst, args)
    finally:
        try:
            board.stop()
            measure.set_sync(board, "cycle")
        finally:
            board.close()
            inst.averaging(None)
            inst.close()


if __name__ == "__main__":
    main()
