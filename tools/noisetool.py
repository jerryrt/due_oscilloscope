"""What the digital side costs the analog side, measured on this board.

    python3 tools/noisetool.py dc          one held level, in bits
    python3 tools/noisetool.py activity    what each digital load costs
    python3 tools/noisetool.py alias       which lines are real

Named `noisetool` rather than `noise` because `host/noise.py` owns that
name and both directories are on the path in `tools/phase0.py`. A tool
shadowing the library it imports fails in a way that reads as the
library being wrong.

The board wires a 78 MHz core, a high-speed USB PHY and two DMA engines
to the same ground and the same rail as its converters. That is a fact
about the hardware, not a defect to fix. What it must not be is a
guess - so this measures it, in bits, so that an AFE or an external
converter can later be judged by how far the number moves.

**The ADC is the instrument here, not the scope.** One code is 0.80 mV
against the DS1102E's 3.1 mV at its best usable gain, it samples
453,488 times a second, and a spectrum of a held level separates
random noise from coupled noise in a single capture - which the scope
cannot do at all. The suite already calls this Tier 3; this is the first
thing to use it.

## What each command is for

`dc` holds one level and reports what the converter delivered: rms in
codes and volts, effective and noise-free bits, how far above the
quantisation floor it sits, and which spectral lines stand above the
broadband floor.

`activity` is the headline. The same measurement under three loads that
differ only in what the *digital* side is doing:

    gen-dc      the internal generator holds the level, no USB in the
                path at all, ADC at a modest rate
    gen-dc-fast the same, at the full 453 ksps on two channels - so
                the conversion cadence and the bulk-IN stream are both
                at maximum
    host-dc     the level is fed from the host over USB, so the OUT
                path, its DMA and its ring are all working too

The differences are attributable, which is the whole point: the first
step is what the conversion rate and the inbound stream cost, the
second is what the outbound playback path costs.

`alias` is the control arm without which no line may be named. There is
no anti-alias filter anywhere on this board, so anything the digital
side does above Nyquist folds down and lands somewhere. A real line sits
at the same frequency at two different sample rates; an alias moves.

## What this cannot do, stated up front

**There is no quiet arm.** Measuring the ADC requires running the ADC
and shipping the result over USB, so every arm here has digital activity
in it. What is measured is a *difference* between loads, never an
absolute floor, and a residual common to all three arms is invisible to
this method.

**It cannot separate the DAC's noise from the ADC's.** A0 is wired to
DAC0, so a held level carries both converters' contributions plus
whatever the board couples in between. Separating them needs a source
that is not this board's DAC.

**Mains is out of reach here.** At 453 ksps over 4096 samples a bin is
110 Hz wide, so 50/60 Hz sits below the first usable bin. Finding it
needs a much longer record, which is a different measurement.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))

import calibration                                            # noqa: E402
import measure                                                # noqa: E402
import noise                                                  # noqa: E402
import provenance as prov                                     # noqa: E402
import repeat                                                 # noqa: E402

RECORDS = os.path.join(HERE, "records")

#: ADC full scale. The ADC's LSB is ADVREF/4096 and is NOT the DAC's
#: 0.5355 mV - they are different converters sharing one reference, and
#: mixing the two would scale every figure here by 1.49.
ADC_BITS = 12
ADC_FULL_SCALE = 4096

#: Trigger presets, and the per-channel rate each yields with two
#: channels converting. `5` is the ADC's in-spec floor, ACQ_MIN_RC = 86.
PRESETS = {"1": 50_000, "2": 100_000, "3": 200_000, "4": 400_000,
           "5": 453_488}


def adc_lsb_v():
    advref, source = calibration.advref_mv()
    return advref / 1000.0 / ADC_FULL_SCALE, advref, source


def _series(res, tag):
    """One channel's codes, in the order they were converted."""
    vals = res.stream.series.get(tag)
    return list(vals) if vals else []


def _drop_head(vals, frac=0.1):
    """The first tenth of a run is thrown away.

    A stream that has just started carries the priming of everything
    upstream of it, and this project has read a stale kernel buffer as a
    live capture before now.
    """
    return vals[int(len(vals) * frac):] if len(vals) > 100 else vals


def hold_gen_dc(board, code, preset, seconds, channels=2):
    """The internal generator holds the level: no USB in the DAC path.

    `=4,...W` is the generator's `dc` shape, so the DAC is fed from the
    device's own table and the host is only reading. This is as close to
    a quiet arm as this board has.
    """
    amp = max(0, min(255, int(round(code * 255.0 / 4095.0))))
    measure.set_sync(board, "off")
    measure.set_gen(board, "dc", 2, amp=amp)
    time.sleep(0.3)
    return measure.run_capture(board, preset=preset, seconds=seconds)


def hold_host_dc(board, code, rate_hz, seconds, channels=2):
    """The host feeds the level over USB: OUT path, DMA and ring active."""
    return measure.run_loop(board, dac_sps=rate_hz, adc_hz=rate_hz,
                            channels=channels, dc=code, seconds=seconds)


def analyse(vals, fs, lsb_v, *, window=4096):
    """Everything the module can say about one held level.

    All of the record, not one window of it. The first version analysed
    4,096 samples of a 900,000-sample capture - 0.5% of what the bench
    time bought - and Phase 0 measured a 42% run-to-run spread on the
    rms it returned, which is wider than any difference worth chasing.
    Welch averaging over every window costs nothing extra and divides
    the estimator's variance by the number of windows.
    """
    vals = _drop_head(vals)
    if len(vals) < 512:
        return {"error": f"only {len(vals)} samples"}
    seg = [float(v) for v in vals]
    out = noise.describe(seg, lsb_v=lsb_v, full_scale_bits=ADC_BITS)
    freqs, amps, k = noise.welch(seg, fs, window=window, lsb_v=lsb_v)
    out["lines"] = noise.peaks(freqs, amps)
    out["split"] = noise.line_split(freqs, amps)
    out["stability"] = noise.stability(seg, window=window)
    out["fs_hz"] = fs
    out["window_n"] = window
    out["windows"] = k
    out["bin_hz"] = fs / window if window else 0
    return out


def report(name, a, lsb_v):
    if "error" in a:
        print(f"{name:>12s}  {a['error']}")
        return
    s = a["split"]
    print(f"\n=== {name} ===")
    st = a.get("stability") or {}
    print(f"  {a['n']:,} samples at {a['fs_hz']:,.0f} sps, "
          f"bin {a['bin_hz']:.0f} Hz, {a.get('windows', 0)} windows "
          f"averaged")
    print(f"  level        {a['mean_code']:.1f} codes = "
          f"{a['mean_v']*1000:.2f} mV")
    print(f"  noise        {a['rms_lsb']:.2f} codes rms = "
          f"{a['rms_v']*1e6:.0f} uV rms, "
          f"{a['p99_9_minus_p0_1_lsb']:.1f} codes p99.9-p0.1")
    if st:
        print(f"  fast vs slow {st['within_rms_lsb']:.2f} codes rms inside "
              f"a window ({st['within_rms_min']:.2f}-"
              f"{st['within_rms_max']:.2f}), "
              f"{st['drift_rms_lsb']:.2f} codes of drift across "
              f"{st['windows']} of them")
    print(f"  vs ideal     {a['excess_over_quantisation']:.1f}x the "
          f"quantisation floor of {a['quantisation_floor_lsb']:.3f} codes")
    print(f"  resolution   {a['effective_bits']:.2f} effective bits, "
          f"{a['noise_free_bits']:.2f} noise-free, of {ADC_BITS}")
    if s:
        frac = s["line_power_fraction"]
        print(f"  split        {s['line_rms_lsb']:.2f} codes in lines, "
              f"{s['floor_rms_lsb']:.2f} codes broadband "
              f"({frac*100:.0f}% of the power is lines)")
    if a["lines"]:
        print(f"  lines        (candidates - not identified until seen "
              f"at two rates)")
        for p in a["lines"][:6]:
            print(f"      {p['hz']:10,.0f} Hz  {p['amp_lsb']:7.3f} codes  "
                  f"{p['over_floor']:6.1f}x floor")


def cmd_dc(board, args):
    """One held level on A0, and the same capture's A1 as a control.

    A1 costs nothing: the run converts both channels anyway, and it is
    the one comparison this board can make for free. A0 carries the DAC
    *and* the converter; A1 carries the converter and an undriven pin.
    If they read alike, the noise is the ADC's and the DAC is not the
    story; if A0 is much the quieter, an undriven pin is picking up more
    than a driven one, which is what an unterminated input does and is
    not evidence about either converter.

    What it cannot do is prove the DAC innocent - a floating pin is a
    worse antenna than a driven one, so this bounds the comparison in
    one direction only.

    **And it turns out A1 is not an independent arm at all.** Undriven,
    it reads within 4 codes of A0's level - 2054.3 against 2050.0 - and
    that is not a coincidence about the two pins. There is one converter
    behind a 16:1 mux, so an undriven input is read through a
    sample-and-hold still carrying charge from the conversion before it,
    which was A0. A1 is reporting a smeared copy of its neighbour plus
    25% more noise.

    That is worth knowing well beyond this measurement: **an unused
    channel in the sequence does not read nothing, it reads its
    neighbour.** Anything using A1 in the same frame as a reference is
    using a signal derived from A0 unless something is driving A1.
    """
    lsb_v, advref, source = adc_lsb_v()
    print(f"ADC LSB {lsb_v*1e6:.1f} uV (ADVREF {advref} mV, {source})")
    res = hold_gen_dc(board, args.code, args.preset, args.seconds)
    fs = res.stream.declared_rate_hz or PRESETS[args.preset]
    a = analyse(_series(res, measure.CH_A0), fs, lsb_v, window=args.window)
    report(f"A0 (DAC0 drives it) - gen-dc code {args.code}", a, lsb_v)
    b = analyse(_series(res, measure.CH_A1), fs, lsb_v, window=args.window)
    if "error" not in b:
        report("A1 (undriven, same capture)", b, lsb_v)
        print(f"\nA0 {a['rms_lsb']:.2f} codes rms against A1's "
              f"{b['rms_lsb']:.2f} - ratio {a['rms_lsb']/b['rms_lsb']:.2f}. "
              f"Same converter,\nsame reference, same instant; what "
              f"differs is what is on the pin.")
    return a


def cmd_activity(board, args):
    """The headline: what each digital load costs, in bits.

    **Interleaved, not blocked.** The arms are measured round-robin and
    compared within rounds, because the level of this board's noise
    wanders about 40% between runs with nothing changed - Phase 0
    measured that - and a difference of 0.1 bits cannot be seen against
    it by comparing one block of runs to another. Whatever wanders is
    common to both arms inside a round and cancels in the paired
    difference.

    The same lesson, from the other direction, is on issue #6: a 42%
    throughput gap between the two firmware tracks evaporated when the
    arms were interleaved instead of run in blocks.
    """
    lsb_v, advref, source = adc_lsb_v()
    print(f"ADC LSB {lsb_v*1e6:.1f} uV (ADVREF {advref} mV, {source})")
    print(f"{args.rounds} interleaved rounds of 3 arms\n")

    arms = [
        ("gen-dc 200k", lambda: hold_gen_dc(board, args.code, "3",
                                            args.seconds), 200000),
        ("gen-dc 453k", lambda: hold_gen_dc(board, args.code, "5",
                                            args.seconds), 453488),
        ("host-dc 200k", lambda: hold_host_dc(board, args.code, 200000,
                                              args.seconds), 200000),
    ]
    # Recorded per arm per round, flushed as it goes, with provenance -
    # the same rule every other measurement here follows. A figure that
    # reaches prose by hand is a figure nobody can re-examine.
    rec = repeat.Recorder(os.path.join(RECORDS, "noise-activity.jsonl"))
    p = prov.collect(board=board, extra={"metric": "noise-activity",
                                         "code": args.code,
                                         "seconds": args.seconds,
                                         "window": args.window})
    gaps = prov.missing(p)
    if gaps:
        raise SystemExit(f"refusing to record: provenance missing {gaps}")

    rounds = []
    for r in range(args.rounds):
        row = {}
        for name, run, nominal in arms:
            res = run()
            fs = res.stream.declared_rate_hz or nominal
            a = analyse(_series(res, measure.CH_A0), fs, lsb_v,
                        window=args.window)
            row[name] = a
            rec.add({"metric": "noise-activity", "arm": name, "round": r,
                     "axis": "interleaved",
                     "values": {k: v for k, v in a.items()
                                if isinstance(v, (int, float))
                                and not isinstance(v, bool)},
                     "split": a.get("split"), "stability": a.get("stability"),
                     "n_lines": len(a.get("lines", [])),
                     "provenance": p})
            bits = a.get("effective_bits")
            print(f"  round {r+1}/{args.rounds} {name:<13s} "
                  f"{a.get('rms_lsb', 0):5.2f} codes rms, "
                  f"{bits:.2f} bits" if bits else f"  {name}: {a}")
        rounds.append(row)

    names = [n for n, _, _ in arms]
    print(f"\n{'arm':<14s} {'rms codes':>10s} {'eff bits':>9s} "
          f"{'spread':>8s} {'lines':>7s}")
    print("-" * 54)
    for name in names:
        vals = [r[name] for r in rounds if "error" not in r[name]]
        if not vals:
            continue
        bits = sorted(v["effective_bits"] for v in vals)
        rmss = sorted(v["rms_lsb"] for v in vals)
        lines = max(len(v["lines"]) for v in vals)
        print(f"{name:<14s} {rmss[len(rmss)//2]:10.2f} "
              f"{bits[len(bits)//2]:9.2f} {bits[-1]-bits[0]:8.2f} "
              f"{lines:7d}")

    print(f"\nPaired against {names[0]}, within rounds:")
    base = names[0]
    for name in names[1:]:
        pairs = [(r[base].get("effective_bits"), r[name].get("effective_bits"))
                 for r in rounds]
        p = noise.paired_delta([(a, b) for a, b in pairs
                                if a is not None and b is not None])
        if not p:
            continue
        print(f"  {name:<14s} {p['verdict']} bits  "
              f"(n={p['n_rounds']}, sd {p['stdev']:.3f})")
    print("\nA bound is a result. 'Not resolved' means the arms differ by "
          "less than the\nstated figure, not that they are the same.")
    return rounds


def cmd_codes(board, args):
    """Noise against output level: is what is left additive or scaled?

    The only question about ADVREF this board can still put to itself.
    The DAC->ADC loop is ratiometric - one reference feeding both
    converters - so the reference's *level* cancels and cannot be
    measured from inside. Its *signature* does not cancel: reference
    noise, like any gain noise, is multiplicative and grows with the
    output level, while the ADC's input and comparator noise is additive
    and does not.

    The DAC spans about 0.55 to 2.75 V, which is a 5x lever on the
    level, and no rewiring or firmware is needed to pull it.

    What this cannot do, said before the numbers arrive: it cannot tell
    ADVREF's noise from the DAC's own gain noise. Both are
    multiplicative. Separating them needs an input that is not derived
    from ADVREF - the on-chip temperature sensor, or an external
    reference - and this board has neither wired.

    Interleaved, because the arms have to be compared within rounds on a
    bench whose level wanders; blocked comparisons have already been
    wrong here twice.
    """
    lsb_v, advref, source = adc_lsb_v()
    print(f"ADC LSB {lsb_v*1e6:.1f} uV (ADVREF {advref} mV, {source})")
    codes = args.codes or [0, 512, 1024, 2048, 3072, 4095]
    print(f"{len(codes)} codes x {args.rounds} interleaved rounds\n")

    rec = repeat.Recorder(os.path.join(RECORDS, "noise-codes.jsonl"))
    p = prov.collect(board=board, extra={"metric": "noise-codes",
                                         "seconds": args.seconds,
                                         "window": args.window})
    gaps = prov.missing(p)
    if gaps:
        raise SystemExit(f"refusing to record: provenance missing {gaps}")

    rounds = []
    for r in range(args.rounds):
        row = {}
        for c in codes:
            # Host-fed, because the internal generator cannot hold an
            # arbitrary level: `gen_set_amp` scales a waveform about mid
            # scale and a DC shape has no amplitude to scale, so every
            # code came out at 2050. The USB OUT path is therefore active
            # for every arm here - constant across the sweep, so it does
            # not bias a comparison between codes.
            res = hold_host_dc(board, c, 200000, args.seconds)
            fs = res.stream.declared_rate_hz or 200000
            a = analyse(_series(res, measure.CH_A0), fs, lsb_v,
                        window=args.window)
            row[c] = a
            rec.add({"metric": "noise-codes", "code": c, "round": r,
                     "axis": "interleaved",
                     "values": {k: v for k, v in a.items()
                                if isinstance(v, (int, float))
                                and not isinstance(v, bool)},
                     "provenance": p})
            print(f"  round {r+1}/{args.rounds} code {c:4d} -> level "
                  f"{a.get('mean_code', 0):7.1f}, "
                  f"{a.get('rms_lsb', 0):5.3f} codes rms")
        rounds.append(row)

    print(f"\n{'code':>6s} {'level':>9s} {'level mV':>9s} {'rms codes':>10s} "
          f"{'spread':>8s}")
    print("-" * 48)
    pts = []
    for c in codes:
        vals = [r[c] for r in rounds if "error" not in r[c]]
        if not vals:
            continue
        lv = sorted(v["mean_code"] for v in vals)
        rm = sorted(v["rms_lsb"] for v in vals)
        med_lv, med_rm = lv[len(lv) // 2], rm[len(rm) // 2]
        pts.append((med_lv, med_rm))
        print(f"{c:6d} {med_lv:9.1f} {med_lv*lsb_v*1000:9.1f} "
              f"{med_rm:10.3f} {rm[-1]-rm[0]:8.3f}")

    f = noise.scaling_fit(pts)
    if not f:
        return rounds
    if f.get("refused"):
        print(f"\n  no fit: {f['refused']}")
        return rounds
    print(f"\n  additive term        {f['additive']:.3f} codes rms")
    print(f"  multiplicative term  {f['multiplicative_at_top']:+.3f} codes "
          f"at the top of the range ({f['level_hi']:.0f} codes)")
    print(f"  lever                {f['lever']:.1f}x in level")
    print(f"  fit residual         {f['fit_residual']:.3f} codes")
    frac = f["fraction_multiplicative"]
    print(f"\n  {frac*100:.0f}% of the noise at full output scales with "
          f"the level.")
    if abs(f["multiplicative_at_top"]) < 2 * f["fit_residual"]:
        print("  That is inside the fit's own residual, so it is NOT "
              "resolved.\n  The residual is additive as far as this can "
              "see, which is what a\n  ratiometric loop predicts - and it "
              "means ADVREF's noise is not\n  what is left.")
    else:
        print("  That is outside the fit's residual: the noise scales "
              "with the\n  output, which is the signature of the "
              "reference or the DAC's gain.\n  This cannot tell those "
              "two apart.")
    return rounds


def cmd_alias(board, args):
    """No line is named until it has been seen at two sample rates."""
    lsb_v, _, _ = adc_lsb_v()
    out = []
    for preset in ("3", "5"):
        r = hold_gen_dc(board, args.code, preset, args.seconds)
        fs = r.stream.declared_rate_hz or PRESETS[preset]
        a = analyse(_series(r, measure.CH_A0), fs, lsb_v, window=args.window)
        report(f"gen-dc preset {preset}", a, lsb_v)
        out.append((fs, a))
    (fa, aa), (fb, ab) = out
    rows = noise.alias_check(aa.get("lines", []), fa,
                             ab.get("lines", []), fb)
    print(f"\n{'line':>12s} {'amp':>8s} {'at other rate':>15s} "
          f"{'verdict':>24s}")
    print("-" * 64)
    for r in rows:
        m = "-" if r["matched_hz"] is None else f"{r['matched_hz']:,.0f} Hz"
        print(f"{r['hz']:>9,.0f} Hz {r['amp_lsb']:8.3f} {m:>15s} "
              f"{r['verdict']:>24s}")
    print("\nStationary means the line is real. Moved means it folded in "
          "from above\nNyquist, and nothing on this board filters that.")
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("dc", "activity", "alias", "codes"))
    ap.add_argument("--codes", type=int, action="append", default=[],
                    help="codes: DAC codes to sweep, repeatable")
    ap.add_argument("--code", type=int, default=2048,
                    help="DAC code to hold (default mid scale)")
    ap.add_argument("--preset", default="5", choices=sorted(PRESETS))
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--rounds", type=int, default=5,
                    help="activity: interleaved rounds per arm")
    ap.add_argument("--window", type=int, default=4096,
                    help="samples per spectrum; a power of two")
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        {"dc": cmd_dc, "activity": cmd_activity, "codes": cmd_codes,
         "alias": cmd_alias}[args.what](board, args)
    finally:
        try:
            board.stop()
            measure.set_sync(board, "cycle")
        finally:
            board.close()


if __name__ == "__main__":
    main()
