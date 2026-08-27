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
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import measure                                                # noqa: E402
import noise as noise_mod                                     # noqa: E402
import noisetool                                              # noqa: E402


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


def _run(board, code, seconds, window, *, preset=None, host_rate=None):
    lsb_v, _, _ = noisetool.adc_lsb_v()
    if host_rate is not None:
        res = noisetool.hold_host_dc(board, code, host_rate, seconds)
        fs = res.stream.declared_rate_hz or host_rate
    else:
        res = noisetool.hold_gen_dc(board, code, preset, seconds)
        fs = res.stream.declared_rate_hz or noisetool.PRESETS[preset]
    a = noisetool.analyse(noisetool._series(res, measure.CH_A0), fs, lsb_v,
                          window=window)
    if "error" in a:
        raise SystemExit(a["error"])
    return _flat(a)


def cmd_noise_dc(board, inst, args):
    """The internal generator holds the level: no USB in the DAC path."""
    return _run(board, args.code, args.seconds, args.window, preset="3")


def cmd_noise_fast(board, inst, args):
    """The same, with the conversion cadence and bulk IN at maximum."""
    return _run(board, args.code, args.seconds, args.window, preset="5")


def cmd_noise_host(board, inst, args):
    """The level fed from the host, so the OUT path is working too."""
    return _run(board, args.code, args.seconds, args.window,
                host_rate=200000)
