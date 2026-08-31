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
    build              __DATE__ " " __TIME__ off the device itself
    fw_repo_rev        the commit that produced the image
    fw_sha256          the exact bytes that were flashed
    fw_flashed_at      when, so the build stamp can be matched to it
    fw_provenance      "matched", or an admission

The commit is deliberately *not* baked into the firmware -
`lib/due_shared/src/fw_version.h` argues that two toolchains would need
build plumbing that can silently disagree, and it is right. It is
recorded by `tools/flash.py` instead, which is the one place that knows
the binary and the tree at the same instant, and matched back here
against the build stamp the board reports.

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
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "host"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import calibration                                            # noqa: E402
import eqtime                                                 # noqa: E402
import measure                                                # noqa: E402
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
        fs = res.stream.declared_rate_hz or 453488
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


def m_loop(board, args):
    """The DAC->ADC loop: tone amplitude, window purity, overruns."""
    med, frac, over, ratio = [], [], [], []
    for _ in range(args.repeats):
        r = measure.run_loop(board, dac_sps=200000, adc_hz=400000,
                             channels=2, tone=1000.0, seconds=args.seconds)
        st = r.stream
        a = [x for _, x in st.window_amplitudes(measure.CH_A0, 1000.0)]
        if not a:
            continue
        med.append(statistics.median(a))
        frac.append(sum(1 for x in a if x >= 1340) / len(a))
        over.append(st.overrun_frames)
        m = st.measured_rate_hz()
        if m and st.declared_rate_hz:
            ratio.append(m / st.declared_rate_hz)
    return {
        "tone_amplitude_codes": _spread(med),
        "windows_at_or_above_1340": _spread(frac),
        "overrun_frames_per_run": _spread(over),
        "rate_measured_over_declared": _spread(ratio),
        "units": "codes; fraction; frames; ratio",
    }


def m_playback(board, args):
    """The ladder: underruns and byte conservation per rate."""
    rows = []
    for rc in (LADDER_RC[:3] if args.quick else LADDER_RC):
        r = measure.run_play(board, dac_sps=int(39_000_000 / rc),
                             tone=1000.0, seconds=args.seconds)
        rows.append({"rc": rc, "sps": int(39_000_000 / rc),
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
        # Named for what it is: a comparison against a figure the DSO
        # bench stored (789-938 ns), not a live instrument. No scope is
        # attached or needed for this run, and on a different board that
        # stored range is a sanity check rather than a verdict.
        out["agrees_with_stored_dso_range"] = a["agrees"]
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
    A(f"| **build stamp** | {p.get('build')} |")
    A(f"| flashed at | {p.get('fw_flashed_at')} |")
    A(f"| build/commit match | **{p.get('fw_provenance')}** |")
    bcur = p.get("fw_build_is_current")
    A("| image built after newest fw commit | " + (
        "**yes**" if bcur is True else
        "**NO - the image predates a firmware commit; a build cache "
        "probably served a stale object**" if bcur is False
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
        # so `agrees_with_scope: False` - the one field that says
        # whether the settling figure may be read at all - vanished
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
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"\nreport written to {args.out}", file=sys.stderr)
    path = args.json_out or os.path.join(RECORDS, "metrics.jsonl")
    repeatmod.Recorder(path).add(run)
    print(f"run recorded in {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
