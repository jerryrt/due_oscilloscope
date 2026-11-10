#!/usr/bin/env python3
"""A PAM-N pattern through one board's loop, read by its ADC and, optionally, a Rigol.

    ets_pam.py plan --pam 4 [--same-board]
    ets_pam.py loop --pam 4 --seconds 4 --eye-out pam4.json [--rigol] [--out rows.jsonl]
    ets_pam.py analyze RAW.bin --pam 4 --rc-dac 28 --rc-adc 45 --eye-out pam4.json

`loop` plays the pattern of `docs/ets-pam.md` from the host on the DAC's own
clock, captures A0 on one channel, and reads the levels, the ladder and the
eyes against the gates (`host/etspam.py`). The two-board capture of the same
pattern is `ets_cross.py ... --pam N`. `--rigol` reads the DAC0 pin on the
bench scope while the loop runs, in a second process so the scope's USB
traffic stays off the feeder, and compares its level spacing with the ADC's.
`tools/ets_pam_page.py` draws the eye file. Pure Python on purpose.
"""
import argparse
import array
import json
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("host", "tools", "tests"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import dsp  # noqa: E402
import eqtime  # noqa: E402
import ets_cross  # noqa: E402
import ets_phase0  # noqa: E402
import etspam  # noqa: E402
import etspattern  # noqa: E402
import etsplan  # noqa: E402
import measure  # noqa: E402
import provenance  # noqa: E402

#: The capture starts before the feed does; this many samples at the start are
#: left out of the analysis (80 ms at 1 Msps, the start-up stretch was 2-12 ms).
HEAD_TRIM = 80_000
TAIL_TRIM = 2_000
#: With the scope the measured run is held this long, and the scope reads it
#: this many seconds in: after the throw-away run (3 s plus set-up) and well
#: before the run ends.
HOLD_S = 14.0
SCOPE_AT_S = 10.0
ADC_MV_PER_CODE = 3300.0 / 4095


def wave_bytes(pat):
    """The host buffer: whole periods, a multiple of 512 bytes (512 * length)."""
    period = array.array("H", [c & 0xFFF for c in pat.symbol_codes()])
    if sys.byteorder == "big":
        period.byteswap()                      # the wire is little-endian
    out = period.tobytes() * ets_phase0.WAVE_PERIODS
    assert len(out) % 512 == 0
    return out


def pair(pam, rc_dac=None, swing_mv=None):
    pat = etspattern.pattern(pam, swing_mv=swing_mv)
    pl = etsplan.plan(rc_dac=rc_dac, same_board=True, length=pat.length)
    return pat, pl


def capture(board, pat, pl, seconds):
    hz = measure.hz_for(pl["rc_dac"])
    res = measure.run_loop(board, dac_sps=hz, adc_hz=measure.hz_for(pl["rc_adc"]),
                           channels=1, seconds=seconds, wave=wave_bytes(pat))
    ps = res.stream
    vals = ps.series.get(measure.CH_A0) or array.array("H")      # already array('H'): no copy
    declared = eqtime.rc_from_hz(ps.declared_rate_hz)
    meta = {"underruns": res.play.underruns, "via": res.play.via,
            "host_tx_bytes": res.host_tx_bytes, "play_bytes_in": res.play.bytes_in,
            "bad": eqtime.check_contiguous(ps), "declared_rc": declared}
    return vals, meta


def analyse(vals, pat, rc_dac, rc_adc, want_eye):
    lo, hi = HEAD_TRIM, len(vals) - TAIL_TRIM
    seg = dsp.np.frombuffer(vals, dtype=dsp.np.uint16)[lo:hi]         # a view: no copy
    return etspam.analyze(seg, rc_adc, pat, rc_dac, start=lo, want_eye=want_eye)


def summary(res):
    return {k: res.get(k) for k in (
        "pam", "samples", "rc_dac", "rc_adc", "delta_ppm", "model_adequate", "lattice_gcd",
        "time_axis_sigma_ns", "spacing_codes", "slope_adc_per_dac", "residual_max_codes",
        "min_separation_sigma", "eye_height_min", "eye_width_min", "monotone", "error")} | {
        "gates": {k: v["passed"] for k, v in res.get("gates", {}).items()},
        "gate_reasons": {k: v["why"] for k, v in res.get("gates", {}).items()},
        "levels_mean_codes": [round(lv["mean"], 2) for lv in res.get("levels", []) if lv["mean"] is not None],
        "levels_std_codes": [round(lv["std"], 2) for lv in res.get("levels", []) if lv["std"] is not None],
        "eyes": [{"height_codes": round(e["height_codes"], 1), "width_symbols": round(e["width_symbols"], 3)}
                 for e in res.get("eyes", [])]}


def _cluster(v, pam):
    """The flat samples and their `pam` Lloyd centroids. The centroids stay in order,
    so each sample's nearest one is a search over the midpoints between them."""
    np = dsp.np
    mv = np.asarray(v, dtype=np.float64) * 1000.0
    flat = mv[2:-2][np.abs(mv[4:] - mv[:-4]) < 18.0]
    srt = np.sort(flat)
    lo, hi = srt[int(0.002 * len(srt))], srt[int(0.998 * len(srt)) - 1]
    cent = lo + (hi - lo) * np.arange(pam) / (pam - 1)
    for _ in range(40):
        near = np.searchsorted((cent[:-1] + cent[1:]) / 2.0, flat, side="left")
        cnt = np.bincount(near, minlength=pam)
        tot = np.bincount(near, weights=flat, minlength=pam)
        new = np.where(cnt > 0, tot / np.maximum(cnt, 1), cent)
        done = np.abs(new - cent).max() < 0.01
        cent = new
        if done:
            break
    return flat, cent.tolist()


def rigol_levels(v, pam):
    """The level voltages the scope sees, from its flat stretches.

    A sample is on a level when the trace is flat across it, about two scope
    steps; the flat samples are then clustered into `pam` groups by Lloyd's
    iteration from evenly spaced starts. Returns means in mV, spacing, counts.
    """
    flat, cent = _cluster(v, pam)
    spacing = (cent[-1] - cent[0]) / (pam - 1)
    n = len(cent)
    mx, my = (n - 1) / 2.0, sum(cent) / n
    slope = sum((i - mx) * (c - my) for i, c in enumerate(cent)) / sum((i - mx) ** 2 for i in range(n))
    resid = [c - (my + slope * (i - mx)) for i, c in enumerate(cent)]
    return {"scope_levels_mv": [round(c, 1) for c in cent], "scope_spacing_mv": spacing,
            "scope_residual_mv": [round(r, 1) for r in resid],
            "scope_flat_samples": len(flat)}


def scope_scale(swing_mv):
    """Volts per division whose 8 divisions cover the swing with 0.3 V to spare."""
    swing_v = (swing_mv or 1000.0) / 1000.0
    for scale in (0.2, 0.5, 1.0):
        if 8 * scale >= swing_v + 0.3:
            return scale
    return 2.0


def rigol(pam, swing_mv=None):
    import scope as scopemod
    inst = scopemod.open_scope()
    try:
        info = {"scope_model": inst.identify(), "scope_probe": inst.probe(1)}
        inst.channel_enable(1, True)
        inst.coupling(1, "DC")
        info["scope_scale_v"] = inst.channel_scale(1, scope_scale(swing_mv))
        info["scope_offset_v"] = inst.channel_offset(1, -1.65)
        inst.timebase(5e-6)
        inst.trigger_edge(source="CHAN1", level=1.65, slope="POS", sweep="AUTO")
        v, dt = inst.capture(1)
        if not v:
            info["scope_error"] = "no record"
            return info
        info.update(rigol_levels(v, pam))
        info["scope_points"] = len(v)
        return info
    finally:
        inst.close()


def row_for(res, meta, pat, pl, label, extra=None):
    row = {"what": "ets_pam", "label": label, "pam": pat.pam, "order": pat.n,
           "symbols": pat.length, "swing_mv": pat.swing_mv,
           "pair_notes": pl["notes"], "pair_problems": pl["problems"]}
    row.update(summary(res))
    row.update(meta)
    row.update(extra or {})
    return row


def cmd_plan(a):
    pat, pl = pair(a.pam, a.rc, a.swing_mv)
    pl["pattern_symbols"] = pat.length
    pl["capture_seconds_20_per_tick"] = etspattern.capture_seconds(pat, pl["rc_dac"], pl["rc_adc"])
    print(json.dumps(pl))


def cmd_analyze(a):
    pat, pl = pair(a.pam, a.rc_dac, a.swing_mv)
    raw = array.array("H")
    with open(a.raw_in, "rb") as f:
        raw.frombytes(f.read())
    rc_dac = a.rc_dac or pl["rc_dac"]
    rc_adc = a.rc_adc or pl["rc_adc"]
    res = analyse(raw, pat, rc_dac, rc_adc, bool(a.eye_out))
    write_eye(a, res, a.raw_in)
    print(json.dumps(summary(res)))


def write_eye(a, res, raw_path):
    if a.eye_out and "eye" in res:
        prov = ets_cross._analysis_provenance(raw_path, a.label)
        prov["analysis"] = prov["analysis"].replace("ets_cross.py eye", "ets_pam.py")
        prov["bench"] = a.bench
        with open(a.eye_out, "w", encoding="utf-8") as f:
            json.dump({"provenance": prov, "eye": res["eye"]}, f, separators=(",", ":"))


def cmd_loop(a):
    pat, pl = pair(a.pam, a.rc, a.swing_mv)
    for note in pl["notes"]:
        print("note:", note, file=sys.stderr)
    if pl["problems"]:
        raise SystemExit("refusing the pair: %s" % "; ".join(pl["problems"]))
    board = measure.Board()
    ident = board.ask("v", secs=1.0).strip()
    capture(board, pat, pl, min(a.seconds, 3.0))            # run 0 is thrown away
    vals, meta = capture(board, pat, pl, a.seconds)
    raw = os.path.join(a.rawdir, "ets-pam%d-%s.bin" % (pat.pam, time.strftime("%Y%m%d-%H%M%S")))
    with open(raw, "wb") as f:
        f.write(vals.tobytes())
    meta["ident"] = ident
    meta["raw"] = raw
    if meta["bad"] or meta["declared_rc"] != pl["rc_adc"]:
        print(json.dumps({"error": "capture not analysable", **meta}))
        return
    res = analyse(vals, pat, pl["rc_dac"], pl["rc_adc"], bool(a.eye_out))
    write_eye(a, res, raw)
    row = row_for(res, meta, pat, pl, a.label)
    row.update(provenance.run_fields(board=board))
    print(json.dumps(row))
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def cmd_loop_with_rigol(a):
    """The loop in a child, the scope here, on the same signal."""
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "loop", "--pam", str(a.pam),
         "--seconds", str(max(a.seconds, HOLD_S)), "--rawdir", a.rawdir, "--bench", a.bench,
         "--label", a.label or "", "--eye-out", a.eye_out or ""]
        + (["--rc", str(a.rc)] if a.rc else [])
        + (["--swing-mv", str(a.swing_mv)] if a.swing_mv else []),
        stdout=subprocess.PIPE, text=True)
    time.sleep(SCOPE_AT_S)             # run 0 is over and the measured run is steady
    info = rigol(a.pam, a.swing_mv or etspattern.DEFAULT_SWING_MV[a.pam])
    text, _ = child.communicate(timeout=a.seconds + 240)
    rows = [json.loads(x) for x in text.splitlines() if x.startswith("{")]
    row = rows[-1] if rows else {"error": "the loop child printed no row"}
    adc_spacing_mv = (row.get("spacing_codes") or 0) * ADC_MV_PER_CODE
    row.update(info)
    if adc_spacing_mv and info.get("scope_spacing_mv"):
        row["adc_spacing_mv"] = adc_spacing_mv
        row["spacing_ratio_adc_over_scope"] = adc_spacing_mv / info["scope_spacing_mv"]
    print(json.dumps(row))
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=("plan", "loop", "analyze"))
    ap.add_argument("raw_in", nargs="?")
    ap.add_argument("--pam", type=int, required=True)
    ap.add_argument("--swing-mv", type=float, default=None, dest="swing_mv",
                    help="peak to peak swing in mV; the level count's default when left out")
    ap.add_argument("--rc", type=int, help="DAC RC; the playback floor, 28, by default")
    ap.add_argument("--rc-dac", type=int, dest="rc_dac")
    ap.add_argument("--rc-adc", type=int, dest="rc_adc")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--rigol", action="store_true")
    ap.add_argument("--eye-out", dest="eye_out")
    ap.add_argument("--label")
    ap.add_argument("--bench", default="")
    ap.add_argument("--rawdir", default="/tmp")
    ap.add_argument("--out")
    ap.add_argument("--same-board", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.what == "plan":
        cmd_plan(a)
    elif a.what == "analyze":
        cmd_analyze(a)
    elif a.rigol:
        cmd_loop_with_rigol(a)
    else:
        cmd_loop(a)


if __name__ == "__main__":
    main()
