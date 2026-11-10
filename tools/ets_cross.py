#!/usr/bin/env python3
"""A PRBS7 from one Due, captured by another, folded with its own clock.

    ets_cross.py both --rc 28 --seconds 16 [--play-dut dut1 --cap-dut dut2]
    ets_cross.py analyze RAW.bin --rc-dac 28 --rc-adc 45
    ets_cross.py resolution RAW.bin --rc-dac 28 --rc-adc 45 [--k 10 --kp 2]
    ets_cross.py sweep --rc-adc 46 --vpps 1000,700,500,350,250,175

The source board's DAC0 is wired to the capturing board's A0, so the two
timers have separate crystals: the pattern's period in the capturing
board's ticks is not an integer and differs from the nominal one by tens of
ppm. `host/etsperiod.py` finds that ratio from the samples, and the fold
then runs on it. `tools/ets_phase0.py` is the same measurement with both
roles on one board, where the ratio is exactly 1.

`both` starts the source in one process and the capture in another, each
pinned to a board by DUE_DUT (bench.json's "duts"), and analyses the raw
capture. `play` and `capture` are the two halves, for a bench that wants to
run them by hand. Pure Python on purpose: the venv carries no numpy.
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
import eqtime  # noqa: E402
import ets_phase0 as e  # noqa: E402
import etsperiod  # noqa: E402
import measure  # noqa: E402
import provenance  # noqa: E402

#: One channel's trigger floor and the capture rate the analysis assumes.
ADC_RC = 45
#: The most samples analysed; the tracker's precision grows with the span.
MAX_SAMPLES = 8_000_000
#: Seconds the source runs before the capture starts.
LEAD_S = 6.0


def play(rc_dac, seconds, vpp_mv):
    board = measure.Board()
    bits = e.prbs7()
    lo, hi = e.levels(vpp_mv)
    hz = measure.hz_for(rc_dac)
    res = measure.run_loop(board, dac_sps=hz, adc_hz=measure.hz_for(ADC_RC),
                           channels=1, seconds=seconds,
                           wave=e.wave_bytes(bits, lo, hi))
    row = {"role": "play", "rc_dac": rc_dac, "dac_hz": hz,
           "lo_code": lo, "hi_code": hi, "vpp_mv": vpp_mv,
           "underruns": res.play.underruns, "via": res.play.via,
           "host_tx_bytes": res.host_tx_bytes,
           "play_bytes_in": res.play.bytes_in,
           "ident": board.ask("v", secs=1.0).strip()}
    row.update(provenance.run_fields(board=board))
    return row


def capture(seconds, out, rc_adc=ADC_RC):
    board = measure.Board()
    hz = measure.hz_for(rc_adc)
    assert measure.rc_for(hz) == rc_adc, (rc_adc, hz)
    res = measure.run_capture(board, preset="=%d,1a" % hz, seconds=seconds)
    ps = res.stream
    vals = array.array("H", [int(v) for v in (ps.series.get(measure.CH_A0) or [])])
    with open(out, "wb") as f:
        f.write(vals.tobytes())
    meta = {"role": "capture", "rc_adc": eqtime.rc_from_hz(ps.declared_rate_hz),
            "declared_hz": ps.declared_rate_hz, "samples": len(vals),
            "bad": eqtime.check_contiguous(ps), "raw": os.path.basename(out),
            "ident": board.ask("v", secs=1.0).strip()}
    meta.update(provenance.run_fields(board=board))
    return meta


def _model_fields(trk):
    """What a reader needs to decide whether the phase model can be trusted."""
    m = trk["model"]
    return {"wander_ptp_ticks": m["wander_ptp"], "phase_rms_ticks": m["rms"],
            "phase_rms_linear_ticks": m["rms_linear"], "model_degree": m["degree"],
            "model_rho1": m["rho1"], "model_max_sigma": m["max_sigma"],
            "model_adequate": trk["adequate"],
            "time_axis_sigma_ns": m["sigma_model"] * e.TICK_NS}


def analyze(path, rc_dac, rc_adc):
    raw = array.array("H")
    with open(path, "rb") as f:
        raw.frombytes(f.read())
    vals = [float(v) for v in raw[:MAX_SAMPLES]]
    bits = e.prbs7()
    bins = len(bits) * rc_dac
    trk = etsperiod.track_clock_ratio(vals, rc_adc, bits, rc_dac)
    curve, cnt = etsperiod.fold_warped(vals, rc_adc, trk["model"], bins)
    row = {"samples": len(vals), "rc_dac": rc_dac, "rc_adc": rc_adc,
           "delta_ppm": trk["delta"] * 1e6, "period_ticks": trk["period"],
           "track_blocks": trk["blocks"], "track_rms_ticks": trk["rms"],
           "track_edge_hits": trk["edge_hits"],
           "coverage": eqtime.coverage(cnt), "min_per_bin": min(cnt)}
    row.update(_model_fields(trk))
    if row["coverage"] < 1.0:
        row["error"] = "fold has holes"
        return row
    fig, b0 = e.analyze(curve, rc_dac, bits)
    row.update(fig)
    row["trusted"] = bool(trk["adequate"] and fig["pattern_ok"])
    edge = [False] * bins
    for j in range(len(bits)):
        c = int(round(b0 + j * rc_dac))
        for x in range(-(rc_dac // 4), rc_dac // 4 + 1):
            edge[(c + x) % bins] = True
    blocks = []                      # (flat sum, flat n, edge sum, edge n) per 1,024
    sf = se = 0.0
    nf = ne = 0
    idx = etsperiod.phase_indices(len(vals), rc_adc, trk["model"], bins)
    for n, (v, i) in enumerate(zip(vals, idx), 1):
        r = v - curve[i]
        if edge[i]:
            se += r * r
            ne += 1
        else:
            sf += r * r
            nf += 1
        if n % 1024 == 0:
            blocks.append((sf, nf, se, ne))
            sf = se = 0.0
            nf = ne = 0
    rms = [math.sqrt((b[0] + b[2]) / (b[1] + b[3])) for b in blocks]
    med = sorted(rms)[len(rms) // 2]
    keep = [b for b, x in zip(blocks, rms) if x <= 3.0 * med]
    fs, fn = sum(b[0] for b in keep), sum(b[1] for b in keep)
    es, en = sum(b[2] for b in keep), sum(b[3] for b in keep)
    row["res_flat"] = math.sqrt(fs / fn) if fn else None
    row["res_edge"] = math.sqrt(es / en) if en else None
    row["blocks_dropped"] = len(blocks) - len(keep)
    return row


def _edge_offsets(curve, rc, bits, shift, b0, rising):
    """50% crossing of isolated edges, in bins from the nominal boundary."""
    L, P = len(bits), len(curve)
    offs = []
    for j in range(2, L - 1):
        m = (j + shift) % L
        pre, post = (0, 1) if rising else (1, 0)
        if not (bits[(m - 2) % L] == bits[(m - 1) % L] == pre
                and bits[m] == bits[(m + 1) % L] == post):
            continue
        c = b0 + j * rc

        def level(centre):
            d = max(1, rc // 8)
            ctr = int(round(centre))
            return sum(curve[(ctr + x) % P] for x in range(-d, d + 1)) / (2 * d + 1)
        a_, b_ = level(c - rc / 2.0), level(c + rc / 2.0)
        t = e._cross(curve, int(c - rc / 2), int(c + rc / 2), (a_ + b_) / 2, rising)
        if t is not None:
            offs.append(t - c)
    return offs


def resolution(path, rc_dac, rc_adc, k, kp):
    """Where the samples land between ticks, and what that does to an edge."""
    raw = array.array("H")
    with open(path, "rb") as f:
        raw.frombytes(f.read())
    vals = [float(v) for v in raw[:MAX_SAMPLES]]
    bits = e.prbs7()
    L = len(bits)
    trk = etsperiod.track_clock_ratio(vals, rc_adc, bits, rc_dac)
    unit = L * rc_dac
    nb, nbp = unit * k, unit * kp
    hist = [0] * 10
    acc = [0.0] * nb
    cnt = [0] * nb
    pacc = [[0.0] * nbp, [0.0] * nbp]
    pcnt = [[0] * nbp, [0] * nbp]
    for n, (v, i) in enumerate(zip(vals, etsperiod.phase_indices(
            len(vals), rc_adc, trk["model"], unit, k))):
        hist[(i % k) * 10 // k] += 1
        acc[i] += v
        cnt[i] += 1
        ip = i * kp // k
        pacc[n & 1][ip] += v
        pcnt[n & 1][ip] += 1
    row = {"samples": len(vals), "delta_ppm": trk["delta"] * 1e6,
           "frac_hist_10": hist, "frac_min_over_max": min(hist) / max(hist),
           "bins_per_tick": k, "fine_filled_share": sum(1 for c in cnt if c >= 20) / nb,
           "fine_min_per_bin": min(cnt), "track_rms_ticks": trk["rms"]}
    row.update(_model_fields(trk))
    tick_ns = e.TICK_NS
    if min(cnt) < 20:
        row["note"] = "fine fold has holes: the samples sit on a lattice, no edge reading"
        return row
    curve = [a / c for a, c in zip(acc, cnt)]
    fig, b0 = e.analyze(curve, rc_dac * k, bits)
    row.update({"pattern_ok": fig["pattern_ok"], "eye_frac": fig.get("eye_frac"),
                "rise_ns_fine": fig["rise_ns"] / k if fig["rise_ns"] else None,
                "fall_ns_fine": fig["fall_ns"] / k if fig["fall_ns"] else None})
    if not fig["pattern_ok"]:
        return row
    shift = fig["shift"]
    for name, rising in (("rise", True), ("fall", False)):
        offs = _edge_offsets(curve, rc_dac * k, bits, shift, b0, rising)
        if offs:
            mean = sum(offs) / len(offs)
            row["edge50_%s_n" % name] = len(offs)
            row["edge50_%s_sd_ns" % name] = math.sqrt(
                sum((x - mean) ** 2 for x in offs) / len(offs)) * tick_ns / k
    if min(min(pcnt[0]), min(pcnt[1])) >= 20:
        pc = [[a / c for a, c in zip(pacc[i], pcnt[i])] for i in (0, 1)]
        for name, rising in (("rise", True), ("fall", False)):
            m = []
            for i in (0, 1):
                o = _edge_offsets(pc[i], rc_dac * kp, bits, shift,
                                  b0 * kp / k, rising)
                m.append(sum(o) / len(o) * tick_ns / kp if o else None)
            row["edge50_%s_even_ns" % name], row["edge50_%s_odd_ns" % name] = m
            if None not in m:
                row["edge50_%s_odd_minus_even_ns" % name] = m[1] - m[0]
        diffs = [row.get("edge50_%s_odd_minus_even_ns" % n) for n in ("rise", "fall")]
        diffs = [d for d in diffs if d is not None]
        if diffs:
            shift_ns = sum(diffs) / len(diffs)
            row["odd_shift_ns"] = shift_ns
            row.update(_corrected(vals, rc_adc, trk["model"], rc_dac, bits, k,
                                  shift_ns / tick_ns * k))
    else:
        row["parity_note"] = "a parity fold has holes at %d bins per tick" % kp
    return row


def _corrected(vals, rc_adc, model, rc_dac, bits, k, shift_bins):
    """The fine fold again with the odd samples moved back by their offset.

    The odd samples' edge sits `shift_bins` fine bins later than the even
    samples', so subtracting that from their phase puts both on one edge.
    """
    L = len(bits)
    nb = L * rc_dac * k
    acc = [0.0] * nb
    cnt = [0] * nb
    back = int(round(shift_bins))
    for n, (v, i) in enumerate(zip(vals, etsperiod.phase_indices(
            len(vals), rc_adc, model, L * rc_dac, k))):
        i = (i - (back if n & 1 else 0)) % nb
        acc[i] += v
        cnt[i] += 1
    if min(cnt) < 20:
        return {"corrected_note": "corrected fold has holes"}
    curve = [a / c for a, c in zip(acc, cnt)]
    fig, b0c = e.analyze(curve, rc_dac * k, bits)
    out = {"corr_pattern_ok": fig["pattern_ok"], "corr_eye_frac": fig.get("eye_frac"),
           "corr_rise_ns": fig["rise_ns"] / k if fig["rise_ns"] else None,
           "corr_fall_ns": fig["fall_ns"] / k if fig["fall_ns"] else None}
    if fig["pattern_ok"]:
        for name, rising in (("rise", True), ("fall", False)):
            offs = _edge_offsets(curve, rc_dac * k, bits, fig["shift"], b0c, rising)
            if offs:
                mean = sum(offs) / len(offs)
                out["corr_edge50_%s_sd_ns" % name] = math.sqrt(
                    sum((x - mean) ** 2 for x in offs) / len(offs)) * e.TICK_NS / k
    return out


def both(a):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    raw = os.path.join(a.rawdir, "ets-cross-%s.bin" % stamp)
    me = os.path.abspath(__file__)
    env_p = dict(os.environ, DUE_DUT=a.play_dut)
    env_c = dict(os.environ, DUE_DUT=a.cap_dut)
    play_s = a.seconds + LEAD_S + 14.0
    src = subprocess.Popen([sys.executable, me, "play", "--rc", str(a.rc),
                            "--seconds", str(play_s), "--vpp-mv", str(a.vpp_mv)],
                           env=env_p, stdout=subprocess.PIPE, text=True)
    time.sleep(LEAD_S)
    cap = subprocess.run([sys.executable, me, "capture", "--seconds",
                          str(a.seconds), "--raw", raw, "--rc-adc",
                          str(a.rc_adc)], env=env_c,
                         stdout=subprocess.PIPE, text=True, timeout=a.seconds + 120)
    play_out, _ = src.communicate(timeout=play_s + 120)

    def last(text):
        rows = [json.loads(x) for x in text.splitlines() if x.startswith("{")]
        return rows[-1] if rows else {"error": "no row printed"}
    prow, crow = last(play_out), last(cap.stdout)
    row = {"play": prow, "capture": crow, "raw": raw}
    if crow.get("bad") or not crow.get("samples") or crow.get("rc_adc") != a.rc_adc:
        row["error"] = "capture not analysable: %s" % (
            crow.get("bad") or crow.get("error") or "rate mismatch")
        return row
    row.update(analyze(raw, a.rc, crow["rc_adc"]))
    return row


def fit_floor(points):
    """Fit rise**2 = a * step**2 + b to `(step_mv, rise_ns)` pairs.

    A slew-limited edge shrinks in proportion to the step, and whatever the
    path adds - the ADC's track-and-hold and the DAC's own small-signal
    response - does not, so `sqrt(b)` is the floor those two leave together.
    It bounds the ADC's share from above and says nothing finer.
    Returns `{a, floor_ns, rms_ns, n}`; `floor_ns` is None when the fit
    puts `b` below zero, i.e. the floor is not resolved.
    """
    xs = [s * s for s, _ in points]
    ys = [r * r for _, r in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    b = my - a * mx
    pred = [math.sqrt(max(0.0, a * x + b)) for x in xs]
    rms = math.sqrt(sum((p - r) ** 2 for p, (_, r) in zip(pred, points)) / n)
    return {"a_ns2_per_mv2": a, "floor_ns": math.sqrt(b) if b > 0 else None,
            "b_ns2": b, "rms_ns": rms, "n": n}


def sweep(a):
    """`both` and `resolution` at each swing, then the floor fit."""
    rows, pts = [], []
    vpps = [float(x) for x in a.vpps.split(",")]
    for i, vpp in enumerate([vpps[0]] + vpps):          # the first run is dropped
        a.vpp_mv = vpp
        got = both(a)
        if got.get("error") or "raw" not in got:
            rows.append({"vpp_mv": vpp, "error": got.get("error", "no raw")})
            continue
        res = resolution(got["raw"], a.rc, a.rc_adc, a.k, a.kp)
        row = {"vpp_mv": vpp, "run": i, "swing_mv": got.get("swing_codes", 0) * 3300.0 / 4095,
               "delta_ppm": res.get("delta_ppm"), "rise_ns_fine": res.get("rise_ns_fine"),
               "fall_ns_fine": res.get("fall_ns_fine"), "eye_frac": res.get("eye_frac"),
               "corr_rise_ns": res.get("corr_rise_ns"), "odd_shift_ns": res.get("odd_shift_ns"),
               "fine_filled_share": res.get("fine_filled_share"),
               "underruns": got["play"].get("underruns"), "rc_adc": a.rc_adc,
               "ident_play": got["play"].get("ident"), "ident_cap": got["capture"].get("ident")}
        row.update({k: got["capture"].get(k) for k in ("fw_repo_rev", "track", "dut")})
        rows.append(row)
        if i > 0 and row["rise_ns_fine"]:
            pts.append((row["swing_mv"], row["rise_ns_fine"]))
    if len(pts) >= 3:
        rows.append({"fit": fit_floor(pts), "points": pts, "rc_dac": a.rc})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("both", "play", "capture", "analyze", "resolution", "sweep"))
    ap.add_argument("raw_in", nargs="?")
    ap.add_argument("--rc", type=int, default=28, help="DAC RC; 28 is the playback floor")
    ap.add_argument("--rc-dac", type=int, dest="rc_dac")
    ap.add_argument("--rc-adc", type=int, dest="rc_adc", default=ADC_RC)
    ap.add_argument("--seconds", type=float, default=16.0)
    ap.add_argument("--vpp-mv", type=float, default=1000.0, dest="vpp_mv")
    ap.add_argument("--play-dut", default="dut1", dest="play_dut")
    ap.add_argument("--cap-dut", default="dut2", dest="cap_dut")
    ap.add_argument("--raw", help="where `capture` writes its samples")
    ap.add_argument("--rawdir", default="/tmp", help="where `both` keeps the raw capture")
    ap.add_argument("--k", type=int, default=10, help="`resolution`: fine bins per tick")
    ap.add_argument("--kp", type=int, default=2, help="`resolution`: bins per tick of the odd/even folds")
    ap.add_argument("--vpps", default="1000,700,500,350,250,175",
                    help="`sweep`: peak-to-peak swings in mV")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.what == "play":
        print(json.dumps(play(a.rc, a.seconds, a.vpp_mv)))
        return
    if a.what == "capture":
        print(json.dumps(capture(a.seconds, a.raw, a.rc_adc)))
        return
    if a.what == "sweep":
        for r in sweep(a):
            print(json.dumps(r))
            if a.out:
                with open(a.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r) + "\n")
        return
    if a.what == "resolution":
        row = resolution(a.raw_in, a.rc_dac or a.rc, a.rc_adc, a.k, a.kp)
    else:
        row = (analyze(a.raw_in, a.rc_dac or a.rc, a.rc_adc) if a.what == "analyze"
               else both(a))
    print(json.dumps(row))
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
