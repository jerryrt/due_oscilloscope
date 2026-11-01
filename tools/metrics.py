"""One command: run the metric set, and emit a report that can be quoted.

    python3 tools/metrics.py                     # full set, report to stdout
    python3 tools/metrics.py --out report.md     # and to a file
    python3 tools/metrics.py --quick             # fewer repeats, for a check
    python3 tools/metrics.py --only noise,loop

**No instrument is required.** The ADC is the instrument: the board is
opened directly, nothing imports `host/scope.py`, and no USBTMC is
involved. That is what makes this report reproducible on a bench that
has no oscilloscope, and `tests/test_metrics.py` asserts it in a
subprocess so a convenience import cannot take it away silently.

The deliverable is the **report**, not the run. Everything this project
has got wrong about its own numbers came from a figure that outlived the
conditions it was taken in, so a report that cannot state those
conditions exactly is not a report - and this refuses to emit one.

## What "exact version" means here, and why each field is present

**Firmware.** `fw_version` is bumped by hand and says what somebody
intended. It is not an answer: on 2026-08-27 two benches both reported
`fw 0.2.0` while running builds four hours and three DAC commits apart,
and one of them published a noise floor a whole bit wrong because of it.
So the report carries all of:

    track, fw_version, ctl_version, frame_version   the contracts
    build              FW_GIT_REV, off the device itself: the commit,
                       plus the working-tree delta hash when dirty
    fw_repo_rev        the commit that produced the image
    fw_sha256          the exact bytes that were flashed
    fw_flashed_at      when the image went on the board
    fw_provenance      which question was answered, or an admission

The commit is compiled into the firmware, so the board states it rather
than a reader inferring it - `lib/due_shared/src/fw_version.h` gives the
reasoning. `provenance.firmware()` then resolves it against
`tools/flash.py`'s log by equality, which is where the bytes, the
compiler and the flash time come from: those are facts about a build
that the image itself does not carry.

**This pipeline is firmware only, deliberately.** Every metric here
opens the board directly and measures the device; nothing runs through
the daemon, so no daemon version is collected or reported. Keeping the
scope to one program keeps the report's claims to one program - a figure
qualified by two version sets invites the reader to wonder which of them
it depended on. If the daemon path is ever profiled it wants its own
pipeline and its own report.

**Everything else** comes from `host/provenance.py`: host OS, the host
tree's own revision, the bench's declared identity and wiring, and the
instrument where one is used. `missing()` gates the run, so an
unattributable measurement is refused rather than published.

## Every figure carries n and its spread

A median with no spread beside it is a claim nobody can check, and this
project has twice mistaken a bimodality for repeatability. Metrics that
repeat are run `--repeats` times and reported as median plus observed
spread; metrics that do not repeat say so.
"""
import argparse
import cmath
import json
import math
import os
import statistics
import struct
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import calibration                                            # noqa: E402
import eqtime                                                 # noqa: E402
import measure                                                # noqa: E402
import pacing                                                 # noqa: E402
import noise as noisemod                                      # noqa: E402
import provenance as prov                                     # noqa: E402
import repeat as repeatmod                                    # noqa: E402
import noisetool                                              # noqa: E402

RECORDS = os.path.join(HERE, "records")

#: The playback ladder, as `docs/status.md` quotes it.
LADDER_RC = [195, 98, 65, 44, 39, 32, 28]


def _spread(vals):
    """Median and observed spread, or a single value said to be one."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    if len(vals) == 1:
        return {"value": vals[0], "n": 1, "spread": None}
    return {"value": statistics.median(vals), "n": len(vals),
            "spread": max(vals) - min(vals),
            "min": min(vals), "max": max(vals)}


# ------------------------------------------------------------------
# the metrics
# ------------------------------------------------------------------

def m_noise(board, args):
    """Effective resolution on a held level, the scope-free figure."""
    lsb_v, advref, source = noisetool.adc_lsb_v()
    bits, rms, lines = [], [], []
    for _ in range(args.repeats):
        res = noisetool.hold_gen_dc(board, 2048, "5", args.seconds)
        fs = res.stream.declared_rate_hz or measure.hz_for(86)
        a = noisetool.analyse(noisetool._series(res, measure.CH_A0), fs,
                              lsb_v, window=4096)
        if "error" in a:
            continue
        bits.append(a["effective_bits"]); rms.append(a["rms_lsb"])
        lines.append(len(a["lines"]))
    return {
        "effective_bits": _spread(bits),
        "noise_rms_codes": _spread(rms),
        "spectral_lines": _spread(lines),
        "advref_mv": advref, "advref_source": source,
        "units": "bits of 12; codes rms; count",
    }


#: RC 225 is 200 kHz at the 90 MHz default; the matched loop is taken here
#: unless a caller names another rung.
LOOP_RC = 225

#: Windows judged after the settle. The ladder's own count, so a loop
#: figure and a ladder rung rest on the same amount of signal.
LOOP_WINDOWS = 10

LOOP_WINDOW = 8192


def amplitude_limits():
    """The tone floor, window fraction and crosstalk ceiling the test suite
    judges against, read from `tests/baseline.json` so the report and the
    suite cannot disagree about what a clean loop is."""
    with open(os.path.join(HERE, "tests", "baseline.json"),
              encoding="utf-8") as f:
        return json.load(f)["amplitude"]


def loop_seconds(rc, windows=LOOP_WINDOWS):
    """A run long enough for `windows` full windows after the settle."""
    hz = measure.hz_for(rc)
    return max(pacing.SHORT,
               measure.SETTLE_US / 1e6 + pacing.GLANCE
               + windows * LOOP_WINDOW / hz)


def loop_figures(res, floor, channels):
    """The flat numbers of one matched-loop run, from a `run_loop` result
    (anything with `.stream` and `.tone_hz`). `None` where a figure cannot
    be formed: no full window, or no device timestamps."""
    st = res.stream
    a = [x for _, x in st.window_amplitudes(
        measure.CH_A0, res.tone_hz, size=LOOP_WINDOW,
        from_us=measure.SETTLE_US)]
    out = {"tone_median_codes": statistics.median(a) if a else None,
           "windows": len(a),
           "windows_at_or_above_floor":
               sum(1 for x in a if x >= floor) / len(a) if a else None,
           "overrun_frames": st.overrun_frames,
           "crosstalk_median_codes": None, "rate_ratio": None}
    if channels == 2:
        x = [v for _, v in st.window_amplitudes(
            measure.CH_A1, res.tone_hz, size=LOOP_WINDOW,
            from_us=measure.SETTLE_US)]
        out["crosstalk_median_codes"] = statistics.median(x) if x else None
    m = st.measured_rate_hz()
    if m and st.declared_rate_hz:
        out["rate_ratio"] = m / st.declared_rate_hz
    return out


def loop_once(board, rc=LOOP_RC, seconds=None, channels=2):
    """One matched DAC->ADC loop at the rate of `rc`, as a flat dict.

    DAC and ADC run at the same rate and the tone is `hz/256`, a whole
    number of cycles in every window, as the ladder does it. Shared by
    `m_loop`, which repeats it, and `tools/phase0.py`."""
    hz = measure.hz_for(rc)
    secs = max(seconds or 0.0, loop_seconds(rc))
    res = measure.run_loop(board, dac_sps=hz, adc_hz=hz, channels=channels,
                           tone=hz / 256.0, seconds=secs)
    if res.refused:
        raise SystemExit(f"RC {rc} ({hz} Hz, {channels} ch) was refused")
    out = loop_figures(res, amplitude_limits()["window_floor_codes"],
                       channels)
    out["rc"] = rc
    out["hz"] = hz
    return out


#: Samples per tone cycle for `tone_sweep_once`. Powers of two, so an
#: 8192-sample window holds 32, 128, 512 and 1024 whole cycles.
TONE_SWEEP_N = (256, 64, 16, 8)


def tone_sweep_once(board, rc=None, seconds=None, ns=TONE_SWEEP_N):
    """Amplitude on A0 and crosstalk on A1 against tone, as a flat dict.

    One matched loop (2 channels, DAC and ADC both at the rate of `rc`,
    RC 225 = 200 kHz by default) per tone `hz/N`, N samples per cycle.
    Each tone must hold a whole number of cycles in an 8192-sample window
    or its window figure leaks; one that does not is rejected before any
    run. Keys: `rc`, `fs`, and per N `amp_n<N>` (median window amplitude
    on A0, codes), `amp_n<N>_frac` (windows at or above the floor of
    `tests/baseline.json`) and `xtalk_n<N>` (median window amplitude on A1
    at the same tone, codes).

    The DAC's hold is not divided out. At N=8 the zero-order hold's sinc
    is in `amp_n8`, and the loop samples at a fixed phase inside each
    hold, so the figure also depends on the phase between the two timers.
    That phase is constant at matched rates and is a property of this
    loop, not of the converter: record it, do not correct for it."""
    rc = rc or LOOP_RC
    hz = measure.hz_for(rc)
    for n in ns:
        if LOOP_WINDOW % n:
            raise ValueError(f"N={n} does not divide the {LOOP_WINDOW}-sample"
                             f" window: the tone is not whole cycles")
    floor = amplitude_limits()["window_floor_codes"]
    secs = max(seconds or 0.0, loop_seconds(rc))
    out = {"rc": rc, "fs": hz}
    for n in ns:
        res = measure.run_loop(board, dac_sps=hz, adc_hz=hz, channels=2,
                               tone=hz / float(n), seconds=secs)
        if res.refused:
            raise SystemExit(f"RC {rc} ({hz} Hz, 2 ch, N={n}) was refused")
        a = [x for _, x in res.stream.window_amplitudes(
            measure.CH_A0, res.tone_hz, size=LOOP_WINDOW,
            from_us=measure.SETTLE_US)]
        x = [v for _, v in res.stream.window_amplitudes(
            measure.CH_A1, res.tone_hz, size=LOOP_WINDOW,
            from_us=measure.SETTLE_US)]
        out[f"amp_n{n}"] = statistics.median(a) if a else None
        out[f"amp_n{n}_frac"] = (sum(1 for v in a if v >= floor) / len(a)
                                 if a else None)
        out[f"xtalk_n{n}"] = statistics.median(x) if x else None
    return out


#: Table points per cycle on each DAC in `loop_skew_once`, and whole
#: cycles in the table. Two entries per point (DAC0 then DAC1), so a
#: cycle is 256 entries and, at the DAC rate `hz`, lasts 256/hz s: the
#: tone is `hz/256`, 32 whole cycles in an 8192-sample window.
SKEW_POINTS = 128
SKEW_CYCLES = 16


def build_sine_both(points=SKEW_POINTS, cycles=SKEW_CYCLES):
    """One full-scale sine on both DACs, host-fed, tagged entry by entry.

    Entry 2k is DAC0 and entry 2k+1 is DAC1, both carrying sample k, so
    the DACC writes DAC1 one trigger after DAC0 by construction. That
    lag is part of what `loop_skew_once` measures. Returns the bytes."""
    out = bytearray()
    for i in range(points * cycles):
        code = int(round(2047.5 + 2047.0 * math.sin(
            2.0 * math.pi * (i % points) / points)))
        code = max(0, min(4095, code))
        out += struct.pack("<H", (0 << 12) | code)
        out += struct.pack("<H", (1 << 12) | code)
    return bytes(out)


def _wrap(x):
    """`x` in radians folded into (-pi, pi]."""
    return math.pi - (math.pi - x) % (2.0 * math.pi)


def _phase(vals, fs, hz):
    """Phase of the `hz` bin of `vals`, radians, by a plain DFT."""
    w = 2.0 * math.pi * hz / fs
    mean = sum(vals) / len(vals)
    acc = sum((v - mean) * cmath.exp(-1j * w * n) for n, v in enumerate(vals))
    return cmath.phase(acc)


def loop_skew_once(board, rc=None, seconds=None):
    """The A1-after-A0 lag of one sine driven on both DACs, as a flat dict.

    A matched loop (2 channels, DAC and ADC at the rate of `rc`, RC 225
    by default) with the same sine on DAC0 and DAC1 (`build_sine_both`),
    tone `hz/256`. Per whole-cycle window the phase of the tone on A1
    less that on A0 is folded to (-pi, pi]; the windows are then folded
    about the first so a figure near +-pi cannot split in two, and the
    median is the answer. Positive `skew_s` means A1 lags A0. The lag is
    folded to half a tone period, so a lag of a whole period or more is
    not seen.

    It is ONE figure: DAC1's write after DAC0's plus the ADC's A1-before-A0
    spacing. `=0N`/`=1N` does not separate them and nothing here does.
    The ADC-only spacing is about 0.96 us *(derived, check)*, printed as
    a reference by the CLI and never judged. Keys: `skew_s`, `skew_ns`,
    `skew_frac_of_period` (of the sample period 1/fs), `phase_deg`,
    `phase_sd_deg`, `n_windows`, `tone_hz`, `rc`, `fs`."""
    rc = rc or LOOP_RC
    hz = measure.hz_for(rc)
    secs = max(seconds or 0.0, loop_seconds(rc))
    res = measure.run_loop(board, dac_sps=hz, adc_hz=hz, channels=2,
                           seconds=secs, wave=build_sine_both())
    if res.refused:
        raise SystemExit(f"RC {rc} ({hz} Hz, 2 ch) was refused")
    tone = hz / 256.0
    ps = res.stream
    v0 = ps.series.get(measure.CH_A0) or []
    v1 = ps.series.get(measure.CH_A1) or []
    start = max(ps._index_at(measure.CH_A0, measure.SETTLE_US),
                ps._index_at(measure.CH_A1, measure.SETTLE_US))
    ds = []
    for s in range(start, min(len(v0), len(v1)) - LOOP_WINDOW, LOOP_WINDOW):
        ds.append(_wrap(_phase(v1[s:s + LOOP_WINDOW], hz, tone)
                        - _phase(v0[s:s + LOOP_WINDOW], hz, tone)))
    if not ds:
        raise SystemExit("no full window after the settle")
    ds = [ref + _wrap(d - ref) for ref in (ds[0],) for d in ds]
    d = statistics.median(ds)
    skew = -d / (2.0 * math.pi * tone)
    return {"skew_s": skew, "skew_ns": skew * 1e9,
            "skew_frac_of_period": skew * hz,
            "phase_deg": math.degrees(d),
            "phase_sd_deg": math.degrees(statistics.pstdev(ds)),
            "n_windows": len(ds), "tone_hz": tone, "rc": rc, "fs": hz}


#: The five levels of `tests/test_integrity.py::test_dc_transfer_is_one_line`.
DC_CODES = (512, 1024, 2048, 3072, 3583)
#: Its DAC rate. A DC level needs no matched rate, so the DAC stays here
#: while the ADC rate varies.
DC_DAC_SPS = 200000


def dc_fit(points):
    """Least-squares line through [(dac_code, mean_a0_code)].

    The same fit as `dc_fit` in `tests/helpers.py` and returning the same
    four numbers (A0 codes per DAC code, A0 codes at DAC code 0, RMS and
    largest absolute residual); `tests/test_phase0.py` holds the two
    equal. It is here because tools do not import from tests."""
    assert len(points) >= 3, "a line needs at least three levels"
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    offset = my - slope * mx
    res = [y - (offset + slope * x) for x, y in points]
    rms = (sum(r * r for r in res) / n) ** 0.5
    return slope, offset, rms, max(abs(r) for r in res)


def dc_fit_once(board, rc=None, seconds=None):
    """One five-code DC sweep and its fit, as a flat dict.

    DAC at 200 ksps, two channels, the ADC at the rate of `rc` (RC 225,
    200 kHz, by default), each level the mean of the settled A0 samples.
    Keys: slope, offset, rms, worst and one `mean_c<code>` per level."""
    rc = rc or measure.rc_for(DC_DAC_SPS)
    hz = measure.hz_for(rc)
    points = []
    for code in DC_CODES:
        res = measure.run_loop(board, dac_sps=DC_DAC_SPS, adc_hz=hz,
                               channels=2, dc=code,
                               seconds=seconds or pacing.PROBE)
        if res.refused:
            raise SystemExit(f"RC {rc} ({hz} Hz, 2 ch) was refused")
        vals = res.stream.settled[measure.CH_A0]
        if not vals:
            raise SystemExit(f"no settled samples at DAC code {code}")
        points.append((code, sum(vals) / len(vals)))
    slope, offset, rms, worst = dc_fit(points)
    out = {"slope": slope, "offset": offset, "rms": rms, "worst": worst,
           "rc": rc, "hz": hz}
    for code, mean in points:
        out[f"mean_c{code}"] = mean
    return out


def m_loop(board, args):
    """The DAC->ADC loop: tone amplitude, window purity, crosstalk, overruns."""
    rc = getattr(args, "rc", None) or LOOP_RC
    lim = amplitude_limits()
    runs = []
    for _ in range(args.repeats):
        r = loop_once(board, rc, args.seconds)
        if r["tone_median_codes"] is not None:
            runs.append(r)

    def col(k):
        return _spread([r[k] for r in runs])
    return {
        "rc": rc, "rate_hz": measure.hz_for(rc),
        "tone_amplitude_codes": col("tone_median_codes"),
        "windows_at_or_above_floor": col("windows_at_or_above_floor"),
        "crosstalk_codes": col("crosstalk_median_codes"),
        "overrun_frames_per_run": col("overrun_frames"),
        "rate_measured_over_declared": col("rate_ratio"),
        "floor_codes": lim["window_floor_codes"],
        "window_fraction_required": lim["window_fraction"],
        "crosstalk_ceiling_codes": lim["crosstalk_ceiling_codes"],
        "units": "codes; fraction; codes; frames; ratio",
    }


def m_playback(board, args):
    """The ladder: underruns and byte conservation per rate."""
    rows = []
    for rc in (LADDER_RC[:3] if args.quick else LADDER_RC):
        r = measure.run_play(board, dac_sps=measure.hz_for(rc),
                             tone=1000.0, seconds=args.seconds)
        rows.append({"rc": rc, "sps": measure.hz_for(rc),
                     "underruns": r.play.underruns,
                     "host_tx_bytes": r.host_tx_bytes,
                     "device_bytes_in": r.play.bytes_in,
                     "refused": r.refused,
                     "via": r.play.via})
    return {"ladder": rows,
            "units": "underruns per run; bytes"}


def m_settling(board, args):
    """Settling by equivalent-time fold, and the fold's own noise floor."""
    import settletime
    out = {}
    try:
        a = settletime.cmd_rise(board, argparse.Namespace(
            points=8, seconds=args.seconds, pre=80, dac_hz=200000))
        out["rise_10_90_ns"] = _spread([a["rise_s"] * 1e9])
        out["fold_margin"] = a["margin"]
    except SystemExit as e:
        out["error"] = str(e)
    return out


METRICS = {
    "noise": ("Effective resolution and noise", m_noise),
    "loop": ("The DAC to ADC loop", m_loop),
    "playback": ("Host-fed playback ladder", m_playback),
    "settling": ("Settling, equivalent-time", m_settling),
}


# ------------------------------------------------------------------
# the report
# ------------------------------------------------------------------

def render(run):
    """The report. Provenance first, because it qualifies everything."""
    p = run["provenance"]
    L = []
    A = L.append
    A(f"# Metric report - {run['taken_at']}")
    A("")
    A("Generated by `tools/metrics.py`. Every figure below is qualified "
      "by the")
    A("conditions in this block; a figure quoted without them is not a "
      "figure.")
    A("")
    A("## Exact versions")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| **firmware track** | {p.get('track')} |")
    A(f"| **fw_version** | {p.get('fw_version')} "
      f"*(bumped by hand; not an identifier on its own)* |")
    A(f"| **firmware commit** | `{p.get('fw_repo_rev')}` |")
    A(f"| **firmware sha256** | `{(p.get('fw_sha256') or '')[:16]}...` |")
    A(f"| **build identity (`build=`)** | `{p.get('build')}` |")
    A(f"| flashed at | {p.get('fw_flashed_at')} |")
    A(f"| build/commit match | **{p.get('fw_provenance')}** |")
    bcur = p.get("fw_build_is_current")
    A("| image holds the newest fw source | " + (
        "**yes**" if bcur is True else
        "**NO - the image was not built from a tree holding the newest "
        "firmware source**" if bcur is False
        else "could not be checked") + " |")
    cur = p.get("fw_source_current")
    A("| firmware source since flashed | " + (
        "**unchanged** - the board runs current firmware however far the "
        "host tree has moved" if cur is True else
        "**CHANGED - the board is not running current firmware**" if cur
        is False else "could not be checked") + " |")
    A(f"| ctl / frame version | {p.get('ctl_version')} / "
      f"{p.get('frame_version')} |")
    A("| scope | **firmware only** - the board is opened directly and "
      "no daemon is in the path |")
    A("| instrument | **none required** - the ADC is the instrument, so "
      "this report is reproducible on any bench with a board |")
    A(f"| host tree | `{p.get('repo_rev')}` |")
    A(f"| host | {p.get('host_os')} ({p.get('host_machine')}), "
      f"python {p.get('python')} |")
    A(f"| bench | **{p.get('bench')}** |")
    A(f"| wiring | {p.get('wiring')} *({p.get('wiring_source')})* |")
    if p.get("instrument"):
        A(f"| instrument | {p['instrument']} |")
    A("")
    for warn in p.get("warnings", []) or []:
        A(f"> **warning:** {warn}")
    A("")

    for key, block in run["metrics"].items():
        title, _ = METRICS[key]
        A(f"## {title}")
        A("")
        if "error" in block:
            A(f"> refused: {block['error']}")
            A("")
            continue
        if key == "playback":
            A("| RC | sps | underruns | host wrote | device got | "
              "deficit |")
            A("|---|---|---|---|---|---|")
            for r in block["ladder"]:
                h, d = r["host_tx_bytes"], r["device_bytes_in"]
                def_ = (f"{h-d:,} B ({(h-d)/h*100:.3f}%)"
                        if (h and d is not None) else "-")
                A(f"| {r['rc']} | {r['sps']:,} | {r['underruns']} | "
                  f"{h:,} | {d if d is None else format(d, ',')} | "
                  f"{def_} |")
            A("")
            continue
        A("| metric | value | n | spread |")
        A("|---|---|---|---|")
        for name, v in block.items():
            if isinstance(v, dict):
                sp = "-" if v.get("spread") is None else f"{v['spread']:.4g}"
                A(f"| {name} | {v['value']:.6g} | {v['n']} | {sp} |")
        # Scalars and verdicts get their own rows rather than being
        # dropped. The first version of this rendered only the dicts,
        # so a failed verdict field - the kind that says
        # whether a figure may be read at all - vanished
        # from the report while the figure it disqualified stayed in.
        for name, v in block.items():
            if isinstance(v, dict) or name == "units":
                continue
            mark = ""
            if isinstance(v, bool):
                mark = "" if v else "  **<- fails; the figures above "\
                                    "must not be quoted**"
            A(f"| {name} | {v}{mark} | - | - |")
        A("")
        A(f"*units: {block.get('units','-')}*")
        A("")
    A("---")
    A("")
    A("A median with no spread beside it is a claim nobody can check. "
      "Where `n` is 1,")
    A("the figure is one observation and is not a result - this project "
      "has had four")
    A("false positives caught by taking a second one.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the report here as well as stdout")
    ap.add_argument("--json", dest="json_out",
                    help="write the machine-readable run here")
    ap.add_argument("--only", help="comma-separated subset of "
                                   + ",".join(METRICS))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--rc", type=int, default=None,
                    help="loop: the rung to take it at (default RC "
                         f"{LOOP_RC}, 200 kHz at the 90 MHz default)")
    ap.add_argument("--quick", action="store_true",
                    help="one repeat and a short ladder")
    args = ap.parse_args()
    if args.quick:
        args.repeats = 1
    want = ([k.strip() for k in args.only.split(",")] if args.only
            else list(METRICS))
    for k in want:
        if k not in METRICS:
            raise SystemExit(f"unknown metric {k!r}; have "
                             + ", ".join(METRICS))

    board = measure.Board(settle=3.0)
    try:
        board.stop(); board.drain_console(0.5)
        p = prov.collect(board=board,
                         extra={"metrics": want, "repeats": args.repeats})
        gaps = prov.missing(p)
        if gaps:
            raise SystemExit(
                f"refusing to report: provenance is missing {gaps}. A "
                f"figure without its conditions is not a figure. If "
                f"`fw_repo_rev` is missing, the board was flashed by "
                f"something that does not log - re-flash with "
                f"tools/flash.py.")
        run = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "provenance": p, "metrics": {}}
        for k in want:
            title, fn = METRICS[k]
            print(f"# {title} ...", file=sys.stderr)
            try:
                run["metrics"][k] = fn(board, args)
            except SystemExit as e:
                run["metrics"][k] = {"error": str(e)}
            except Exception as e:                            # noqa: BLE001
                # One metric failing must not cost the whole run. The
                # first version caught only the metrics' own refusals,
                # so a macOS `close()` wedge in the playback ladder -
                # objective 0c, a known host defect - killed a Track A
                # run that had already produced three good metrics and
                # emitted no report at all. A failed metric is a
                # recorded condition, not a reason to lose the rest.
                run["metrics"][k] = {"error": f"{type(e).__name__}: {e}"}
            finally:
                board.stop(); board.drain_console(0.2)
    finally:
        try:
            board.stop(); measure.set_sync(board, "cycle")
        finally:
            board.close()

    text = render(run)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nreport written to {args.out}", file=sys.stderr)
    path = args.json_out or os.path.join(RECORDS, "metrics.jsonl")
    repeatmod.Recorder(path).add(run)
    print(f"run recorded in {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
