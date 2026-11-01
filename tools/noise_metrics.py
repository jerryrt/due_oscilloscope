"""The noise measurements, in the shape Phase 0 can repeat.

`tools/noise.py` is the command a person runs and reads. This is the
same measurement returning a flat result, so `tools/phase0.py` can take
seven of them and say what the spread is - which is the only thing that
decides whether a difference between two arms is a finding or a
coincidence.

That question is live rather than procedural. The first activity sweep
put the full-rate arm 0.05 bits below the modest-rate one and the
host-fed arm 0.03 bits below it, and single runs of the *same* arm
ranged over 3.91 to 4.78 codes rms across the session. A difference
four times smaller than the scatter of its own measurement is not a
difference yet.

The raw line list is deliberately not returned. Line frequencies are not
comparable run to run - they are candidates until an alias check has
seen them twice - so recording them as metric keys would invite exactly
the reading the alias check exists to prevent. The *count* and the power
fraction are recorded, because those are comparable.
"""
import argparse
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import measure                                                # noqa: E402
import noise as noise_mod                                     # noqa: E402
import noisetool                                              # noqa: E402
import metrics as mt                                          # noqa: E402


def default_args(what, **overrides):
    """The Namespace the CLI would build, without a command line."""
    ns = argparse.Namespace(code=2048, seconds=2.0, window=4096,
                            preset="5", what=what)
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _flat(a):
    """Scalars only, and no line frequencies. See the module docstring."""
    out = {k: v for k, v in a.items()
           if isinstance(v, (int, float)) and not isinstance(v, bool)}
    out["n_lines"] = len(a.get("lines", []))
    for k, v in (a.get("split") or {}).items():
        if isinstance(v, (int, float)):
            out[f"split.{k}"] = v
    return out


def _run(board, code, seconds, window, *, preset=None, host_rate=None, rc=None):
    """One noise run. `rc` repeats the metric at one ladder rate: the trigger
    is the RC's rate, whichever of the generator or the host holds the level."""
    lsb_v, _, _ = noisetool.adc_lsb_v()
    if rc is not None:
        host_rate = measure.hz_for(rc) if host_rate is not None else None
        if host_rate is None:
            preset = "=%d,%dM" % (measure.hz_for(rc), measure.hz_for(rc))
    if host_rate is not None:
        res = noisetool.hold_host_dc(board, code, host_rate, seconds)
        fs = res.stream.declared_rate_hz or host_rate
    else:
        res = noisetool.hold_gen_dc(board, code, preset, seconds)
        fs = (res.stream.declared_rate_hz or noisetool.PRESETS.get(preset)
              or measure.hz_for(rc or 86))
    a = noisetool.analyse(noisetool._series(res, measure.CH_A0), fs, lsb_v,
                          window=window)
    if "error" in a:
        raise SystemExit(a["error"])
    return _flat(a)


def cmd_noise_dc(board, inst, args):
    """The internal generator holds the level: no USB in the DAC path."""
    return _run(board, args.code, args.seconds, args.window, preset="3",
                rc=getattr(args, "rc", None))


def cmd_noise_fast(board, inst, args):
    """The same, with the conversion cadence and bulk IN at maximum."""
    return _run(board, args.code, args.seconds, args.window, preset="5",
                rc=getattr(args, "rc", None))


def cmd_noise_host(board, inst, args):
    """The level fed from the host, so the OUT path is working too."""
    return _run(board, args.code, args.seconds, args.window,
                host_rate=200000, rc=getattr(args, "rc", None))


def add_known_noise(values, rms_lsb, seed=1):
    """`values` plus independent gaussian noise of `rms_lsb` codes rms.

    Takes the series *before* it is rounded to integer codes, because the
    board's noise is added in the analog domain ahead of the converter's
    rounding. Adding it to codes already rounded would leave a small
    amount of noise unable to move most samples, and the figure would
    miss the root-sum-square by the quantisation, not by the noise.
    Stdlib `random`, as `noise.py`'s tests do; a fixed seed makes the
    result repeatable.
    """
    rng = random.Random(seed)
    return [v + rng.gauss(0.0, rms_lsb) for v in values]


def rss_response(values, extra_rms_lsb, fs, *, seed=1, window=4096):
    """What `noisetool.analyse` says before and after known noise is added.

    `values` is the pre-rounding series; both arms are rounded to integer
    codes here, as the converter does. Returns the two analyses and the
    root-sum-square prediction for the noisy arm's `rms_lsb`:
    sqrt(baseline^2 + extra^2). The prediction uses the baseline as
    measured, so the sampling error of the baseline cancels out of it.
    """
    lsb_v = 1.0   # codes in, codes out: the volt scale is not under test
    base = noisetool.analyse([round(v) for v in values], fs, lsb_v,
                             window=window)
    noisy = noisetool.analyse(
        [round(v) for v in add_known_noise(values, extra_rms_lsb, seed)],
        fs, lsb_v, window=window)
    predicted = math.sqrt(base["rms_lsb"] ** 2 + extra_rms_lsb ** 2)
    return base, noisy, predicted


#: The matched loop's tone is `hz / 256`, so a window of 8192 holds 32 cycles.
SINAD_WINDOW = 8192


def sinad_once(board, rc, seconds=None):
    """SINAD, THD and ENOB of the matched DAC->ADC loop, as a flat dict.

    The run is `tools/metrics.py` `loop_once`'s: DAC and ADC at the rate of
    `rc`, tone `hz/256`, two channels, long enough for ten windows after the
    settle. The series is A0 from the first sample at or after
    `measure.SETTLE_US` (the `settled` list is capped at 16384 samples, too
    short for ten windows). It is a loop figure: the DAC's staircase and the
    converter's noise are both in it."""
    rc = rc or mt.LOOP_RC
    hz = measure.hz_for(rc)
    secs = max(seconds or 0.0, mt.loop_seconds(rc))
    res = measure.run_loop(board, dac_sps=hz, adc_hz=hz, channels=2,
                           tone=hz / 256.0, seconds=secs)
    if res.refused:
        raise SystemExit(f"RC {rc} ({hz} Hz, 2 ch) was refused")
    st = res.stream
    vals = st.series.get(measure.CH_A0)
    if not vals:
        raise SystemExit("no A0 samples")
    vals = list(vals)[st._index_at(measure.CH_A0, measure.SETTLE_US):]
    r = noise_mod.sinad(vals, hz, res.tone_hz, window=SINAD_WINDOW)
    out = {k: v for k, v in r.items() if k != "harmonic_bins"}
    out.update(tone_hz=res.tone_hz, rc=rc, fs=hz)
    return out
