#!/usr/bin/env python3
"""Phase 0 of docs/ets-mode.md: a 1 V PRBS7 through the loop, folded.

    ets_phase0.py selftest
    ets_phase0.py loop --rcs 225,90,56,45,36,32,28 [--out rows.jsonl]
    ets_phase0.py both --rcs 56,28      the loop and the Rigol on one signal

`loop` plays a PRBS7 (one DAC update per symbol) from the host on the
DAC's own clock and captures A0 on one channel at an RC coprime with the
pattern period, so the fold reaches every timer tick. The two clocks
divide MCK, so the period in ticks is exactly `127 * rc_dac`. What it
reports per rate is whether the output repeats (`res_ratio`, `half_ratio`),
how open the eye is, and the isolated-transition rise and fall times.

`selftest` runs the analysis on a synthetic single-pole PRBS with a known
rise time, and again on a wrong period, which must collapse the eye.
Pure Python on purpose: the venv carries no numpy.
"""
import argparse
import json
import math
import os
import random
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("host", "tools", "tests"):
    sys.path.insert(0, os.path.join(ROOT, sub))
import eqtime  # noqa: E402
import measure  # noqa: E402
import provenance  # noqa: E402
import settletime as st  # noqa: E402

TC = eqtime.TC_CLOCK_HZ
TICK_NS = 1e9 / TC

#: One ADC code in millivolts at 3.3 V full scale, 12 bit.
ADC_LSB_MV = 3300.0 / 4095
#: DAC mV per code, from docs/hardware.md: code 0 about 546 mV and code
#: 4095 about 2760 mV at the loop.
DAC_LSB_MV = (2760.0 - 546.0) / 4095
#: One channel's trigger floor (CLAUDE.md: RC 44, 1,022,727 Hz).
ADC_ONE_CH_MIN_RC = 44

PRBS7_LEN = 127
#: Whole PRBS7 periods per host buffer, so the buffer is a multiple of
#: both a period (254 B) and 512 B (Feeder.WRITE_SIZE): 127 * 256 samples.
WAVE_PERIODS = 256


def prbs7():
    """x^7 + x^6 + 1, 127 bits; asserts the properties that define it."""
    s, bits = 0x7F, []
    for _ in range(PRBS7_LEN):
        bits.append(s & 1)
        s = ((s << 1) | (((s >> 6) ^ (s >> 5)) & 1)) & 0x7F
    assert s == 0x7F, "the register did not return to its seed in 127 steps"
    assert sum(bits) == 64, "a PRBS7 has 64 ones in 127 bits"
    return bits


def levels(vpp_mv):
    half = int(round(vpp_mv / 2 / DAC_LSB_MV))
    return 2048 - half, 2048 + half


def wave_bytes(bits, lo, hi):
    out = bytearray()
    for _ in range(WAVE_PERIODS):
        for b in bits:
            out += struct.pack("<H", (hi if b else lo) & 0xFFF)
    assert len(out) % 512 == 0
    return bytes(out)


def fold(vals, rc_adc, period, start=0):
    """Mean per tick position; `start` is the index of vals[0] in the run."""
    acc = [0.0] * period
    cnt = [0] * period
    step = rc_adc % period
    ph = (start * rc_adc) % period
    for v in vals:
        acc[ph] += v
        cnt[ph] += 1
        ph += step
        if ph >= period:
            ph -= period
    return [acc[i] / cnt[i] if cnt[i] else None for i in range(period)], cnt


def _cross(curve, a, b, level, rising):
    """Tick (fractional) where curve first crosses `level` in [a, b)."""
    P = len(curve)
    for k in range(a, b):
        y0, y1 = curve[k % P], curve[(k + 1) % P]
        if (y0 < level <= y1) if rising else (y0 > level >= y1):
            return k + (level - y0) / (y1 - y0)
    return None


def analyze(curve, rc_dac, bits):
    """Eye and edge figures from a folded period of the PRBS."""
    P, L = len(curve), len(bits)
    assert P == L * rc_dac and all(c is not None for c in curve)
    e = [0.0] * rc_dac
    for k in range(P):
        e[k % rc_dac] += abs(curve[(k + 1) % P] - curve[k])
    w = max(3, rc_dac // 3)
    phi = max(range(rc_dac), key=lambda p: sum(e[(p + i) % rc_dac]
                                               for i in range(w)))
    b0 = (phi + w / 2.0) % rc_dac
    d = max(1, rc_dac // 8)

    def centre(j):
        c = int(round(b0 + (j + 0.5) * rc_dac))
        return sum(curve[(c + x) % P] for x in range(-d, d + 1)) / (2 * d + 1)

    v = [centre(j) for j in range(L)]
    mid = (max(v) + min(v)) / 2
    cls = [1 if x > mid else 0 for x in v]
    shift = None
    for s in range(L):
        if all(bits[(j + s) % L] == cls[j] for j in range(L)):
            shift = s
            break
    ones = [x for x, c in zip(v, cls) if c]
    zeros = [x for x, c in zip(v, cls) if not c]
    out = {"b0_tick": round(b0, 2), "pattern_ok": shift is not None,
           "swing_codes": (sum(ones) / len(ones) - sum(zeros) / len(zeros)
                           if ones and zeros else 0.0)}
    if ones and zeros:
        out["eye_codes"] = min(ones) - max(zeros)
        out["eye_frac"] = out["eye_codes"] / out["swing_codes"]
    rise, fall = [], []
    for j in range(2, L - 1):
        if not (cls[j - 2] == cls[j - 1] != cls[j] == cls[(j + 1) % L]):
            continue
        a, b = v[j - 1], v[j]
        up = b > a
        lo10, hi90 = a + 0.1 * (b - a), a + 0.9 * (b - a)
        t0 = int(round(b0 + j * rc_dac)) - rc_dac // 2
        t1 = t0 + rc_dac
        x10 = _cross(curve, t0, t1, lo10, up)
        x90 = _cross(curve, t0, t1, hi90, up)
        if x10 is not None and x90 is not None:
            (rise if up else fall).append((x90 - x10) * TICK_NS)
    for name, xs in (("rise", rise), ("fall", fall)):
        out[name + "_ns"] = round(sum(xs) / len(xs), 1) if xs else None
        out[name + "_n"] = len(xs)
    return out, b0


def residuals(vals, rc_adc, curve, rc_dac, b0, start=0):
    """RMS of the samples against the fold, split flat against edge."""
    P = len(curve)
    edge = [False] * P
    for j in range(P // rc_dac):
        c = int(round(b0 + j * rc_dac))
        for x in range(-(rc_dac // 4), rc_dac // 4 + 1):
            edge[(c + x) % P] = True
    step = rc_adc % P
    ph = (start * rc_adc) % P
    sf = se = 0.0
    nf = ne = 0
    for v in vals:
        r = v - curve[ph]
        if edge[ph]:
            se += r * r
            ne += 1
        else:
            sf += r * r
            nf += 1
        ph += step
        if ph >= P:
            ph -= P
    return (math.sqrt((sf + se) / (nf + ne)),
            math.sqrt(sf / nf) if nf else None,
            math.sqrt(se / ne) if ne else None)


BLOCK = 1024
#: A block is steady when its residual rms is within this many times the
#: median block's. The capture starts before the host's feed does, and
#: the DAC then sits at its idle level for about 11 ms: left in, those
#: samples read as 600 codes of "noise" against the fold.
STEADY_X = 3.0


def steady_range(vals, rc_adc, P):
    """(first, last) sample of the longest run of blocks that fit the fold."""
    n = len(vals)
    q0, q1 = n // 4, 3 * n // 4
    curve, _ = fold(vals[q0:q1], rc_adc, P, start=q0)
    if any(c is None for c in curve):
        return 0, n
    step = rc_adc % P
    rms = []
    for i in range(0, n - BLOCK + 1, BLOCK):
        ph = (i * rc_adc) % P
        acc = 0.0
        for v in vals[i:i + BLOCK]:
            r = v - curve[ph]
            acc += r * r
            ph += step
            if ph >= P:
                ph -= P
        rms.append(math.sqrt(acc / BLOCK))
    med = sorted(rms)[len(rms) // 2]
    ok = [x <= STEADY_X * med for x in rms]
    best = (0, 0)
    i = 0
    while i < len(ok):
        if ok[i]:
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            if j - i > best[1] - best[0]:
                best = (i, j)
            i = j
        else:
            i += 1
    return best[0] * BLOCK, best[1] * BLOCK


def run_stats(vals, rc_adc, rc_dac, bits):
    P = len(bits) * rc_dac
    first, last = steady_range(vals, rc_adc, P)
    head, tail = first, len(vals) - last
    vals = vals[first:last]
    curve, cnt = fold(vals, rc_adc, P, start=first)
    cov = eqtime.coverage(cnt)
    if cov < 1.0:
        return {"coverage": cov, "error": "fold has holes"}
    fig, b0 = analyze(curve, rc_dac, bits)
    res, flat, edge = residuals(vals, rc_adc, curve, rc_dac, b0, first)
    n1 = len(vals) // 2
    c1, k1 = fold(vals[:n1], rc_adc, P, start=first)
    c2, k2 = fold(vals[n1:], rc_adc, P, start=first + n1)
    if any(x is None for x in c1) or any(x is None for x in c2):
        half = None
    else:
        diff = math.sqrt(sum((x - y) ** 2 for x, y in zip(c1, c2)) / P)
        exp = res * math.sqrt(1.0 / (n1 / P) + 1.0 / ((len(vals) - n1) / P))
        half = diff / exp
    fig.update({"coverage": cov, "period_ticks": P, "n": len(vals),
                "trim_head": head, "trim_tail": tail,
                "min_per_tick": min(cnt), "res_rms": round(res, 3),
                "res_flat": round(flat, 3) if flat is not None else None,
                "res_edge": round(edge, 3) if edge is not None else None,
                "half_ratio": round(half, 2) if half is not None else None})
    return fig


# --------------------------------------------------------------- selftest

def synth(bits, rc_dac, tau_ticks, rc_adc, n, sigma, lo=1000.0, hi=2400.0,
          lag=0):
    """Samples of a single-pole PRBS, with `lag` ticks of start offset."""
    P = len(bits) * rc_dac
    x = [hi if bits[(t // rc_dac) % len(bits)] else lo for t in range(P)]
    y, a = lo, 1.0 - math.exp(-1.0 / tau_ticks)
    for _ in range(4):
        for t in range(P):
            y += (x[t] - y) * a
    true = []
    for t in range(P):
        y += (x[t] - y) * a
        true.append(y)
    rnd = random.Random(7)
    out, ph, step = [], lag % P, rc_adc % P
    for _ in range(n):
        out.append(true[ph] + rnd.gauss(0, sigma))
        ph = (ph + step) % P
    return out


def selftest():
    bits = prbs7()
    rc_dac, tau = 28, 4.0
    P = len(bits) * rc_dac
    rc_adc, _ = st.coprime_adc_rc(P, 45, floor=ADC_ONE_CH_MIN_RC)
    vals = synth(bits, rc_dac, tau, rc_adc, 600000, 0.8, lag=37)
    got = run_stats(vals, rc_adc, rc_dac, bits)
    want = 2.197 * tau * TICK_NS
    print("good period :", got)
    assert got["pattern_ok"], "the fold did not recover the PRBS"
    assert abs(got["rise_ns"] - want) < 0.1 * want, (got["rise_ns"], want)
    assert abs(got["fall_ns"] - want) < 0.1 * want, (got["fall_ns"], want)
    assert got["eye_frac"] > 0.8, got["eye_frac"]
    assert 0.5 < got["half_ratio"] < 2.0, got["half_ratio"]
    head = [1800.0] * 11264
    dirty = run_stats(head + vals, rc_adc, rc_dac, bits)
    print("with a start-up transient:", dirty)
    assert dirty["trim_head"] >= 11264, dirty["trim_head"]
    assert dirty["eye_frac"] > 0.8 and abs(dirty["rise_ns"] - want) < 0.1 * want, dirty
    wrong = next(r for r in range(rc_adc + 2, rc_adc + 40)
                 if math.gcd(r, P) == 1)
    bad_curve, _ = fold(vals, wrong, P)
    fig, _ = analyze(bad_curve, rc_dac, bits)
    print("wrong ADC RC", wrong, ":", fig)
    assert (not fig["pattern_ok"]) or fig["eye_frac"] < 0.5, (
        "a fold on the wrong clock relation still shows an open eye: the "
        "check cannot tell a right fold from a wrong one", fig)
    # The scope-side reader, on a 10 ns record of a single-pole PRBS.
    dt, ui, rise_true = 10e-9, 28 * TICK_NS * 1e-9, 138e-9
    tau = rise_true / 2.197
    k, y, tr, rnd = 1 - math.exp(-dt / tau), 1.15, [], random.Random(3)
    for n in range(int(60 * 127 * ui / dt)):
        x = 2.15 if bits[int(n * dt / ui) % 127] else 1.15
        y += (x - y) * k
        tr.append(y + rnd.gauss(0, 0.004))
    sc = scope_edges(tr, dt, ui)
    print("scope reader :", sc)
    assert abs(sc["scope_rise_ns"] - 138) < 14 and sc["scope_rise_n"] > 100, sc
    assert abs(sc["scope_fall_ns"] - 138) < 14, sc
    assert abs(sc["scope_swing_mv"] - 1000) < 20, sc
    box = 15
    slow = [sum(tr[i:i + box]) / box for i in range(len(tr) - box)]
    slowed = scope_edges(slow, dt, ui)["scope_rise_ns"]
    assert slowed > sc["scope_rise_ns"] + 20, (
        "a 150 ns boxcar on the record reads no slower: the scope reader "
        "cannot see rise time", slowed)
    print("selftest ok: rise %.1f ns against %.1f ns expected"
          % (got["rise_ns"], want))


# -------------------------------------------------------------------- loop

def one(board, rc_dac, seconds, vpp_mv):
    bits = prbs7()
    lo, hi = levels(vpp_mv)
    hz = measure.hz_for(rc_dac)
    assert measure.rc_for(hz) == rc_dac, (rc_dac, hz)
    P = len(bits) * rc_dac
    rc_adc, adc_hz = st.coprime_adc_rc(P, ADC_ONE_CH_MIN_RC + 1,
                                       floor=ADC_ONE_CH_MIN_RC)
    res = measure.run_loop(board, dac_sps=hz, adc_hz=adc_hz, channels=1,
                           seconds=seconds, wave=wave_bytes(bits, lo, hi))
    ps = res.stream
    row = {"rc_dac": rc_dac, "dac_hz": hz, "rc_adc": rc_adc,
           "adc_hz": adc_hz, "lo_code": lo, "hi_code": hi,
           "vpp_mv": vpp_mv, "pattern": "prbs7", "samples_per_symbol": 1,
           "underruns": res.play.underruns,
           "via": res.play.via,
           "host_tx_bytes": res.host_tx_bytes,
           "play_bytes_in": res.play.bytes_in,
           "bad": eqtime.check_contiguous(ps),
           "declared_hz": ps.declared_rate_hz}
    declared = eqtime.rc_from_hz(ps.declared_rate_hz)
    vals = [float(v) for v in (ps.series.get(measure.CH_A0) or [])]
    if row["bad"] or not vals or declared != rc_adc:
        row["error"] = "not reconstructed: %s" % (
            row["bad"] or "no data or rate mismatch")
        return row
    row.update(run_stats(vals, rc_adc, rc_dac, bits))
    return row


# ------------------------------------------------------------------ scope

def scope_edges(v, dt, ui_s):
    """Isolated-transition figures from a scope record of the PRBS.

    A transition is isolated when the neighbouring crossings are at least
    2.2 symbols away, so both levels have settled. The 10-90% time is read
    between the medians of the settled levels, interpolated between the
    samples, and averaged over every such transition in the record.
    """
    srt = sorted(v)
    p1, p99 = srt[int(0.01 * len(srt))], srt[int(0.99 * len(srt)) - 1]
    mid = (p1 + p99) / 2
    ui = ui_s / dt                               # samples per symbol
    cross = []
    for i in range(len(v) - 1):
        if (v[i] < mid) != (v[i + 1] < mid):
            cross.append((i + (mid - v[i]) / (v[i + 1] - v[i]),
                          v[i + 1] > v[i]))

    def level(a, b):
        seg = sorted(v[max(0, int(a)):max(1, int(b))])
        return seg[len(seg) // 2] if seg else None

    def when(a, b, thr, up):
        for k in range(max(0, int(a)), min(len(v) - 1, int(b))):
            y0, y1 = v[k], v[k + 1]
            if (y0 < thr <= y1) if up else (y0 > thr >= y1):
                return k + (thr - y0) / (y1 - y0)
        return None

    rise, fall, sw = [], [], []
    for n in range(1, len(cross) - 1):
        t, up = cross[n]
        if t - cross[n - 1][0] < 2.2 * ui or cross[n + 1][0] - t < 2.2 * ui:
            continue
        a = level(t - 1.5 * ui, t - 0.7 * ui)
        b = level(t + 0.7 * ui, t + 1.5 * ui)
        if a is None or b is None:
            continue
        x10 = when(t - 0.5 * ui, t + 0.5 * ui, a + 0.1 * (b - a), up)
        x90 = when(t - 0.5 * ui, t + 0.5 * ui, a + 0.9 * (b - a), up)
        if x10 is None or x90 is None:
            continue
        (rise if up else fall).append((x90 - x10) * dt * 1e9)
        sw.append(abs(b - a))
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    return {"scope_rise_ns": mean(rise), "scope_rise_n": len(rise),
            "scope_fall_ns": mean(fall), "scope_fall_n": len(fall),
            "scope_swing_mv": round(1000 * sum(sw) / len(sw), 1) if sw else None,
            "scope_dt_ns": dt * 1e9, "scope_points": len(v)}


def rigol(ui_s, vpp_mv):
    import scope as scopemod
    inst = scopemod.open_scope()
    try:
        info = {"scope_model": inst.identify(), "scope_probe": inst.probe(1)}
        inst.channel_enable(1, True)
        inst.coupling(1, "DC")
        info["scope_scale_v"] = inst.channel_scale(1, 0.2)
        info["scope_offset_v"] = inst.channel_offset(1, -1.65)
        inst.timebase(5e-6)
        info["scope_trigger"] = inst.trigger_edge(
            source="CHAN1", level=1.65, slope="POS", sweep="AUTO")
        v, dt = inst.capture(1)
        if not v:
            info["scope_error"] = "no record"
            return info
        info.update(scope_edges(v, dt, ui_s))
        return info
    finally:
        inst.close()


def both(rc_dac, seconds, vpp_mv):
    """The loop capture in a child, the scope capture here, same signal."""
    import subprocess
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "loop", "--rcs",
         str(rc_dac), "--seconds", str(seconds), "--vpp-mv", str(vpp_mv),
         "--no-warm"], stdout=subprocess.PIPE, text=True)
    import time
    time.sleep(4.0)                      # the feed is steady well before this
    info = rigol(rc_dac / TC, vpp_mv)
    text, _ = child.communicate(timeout=seconds + 120)
    rows = [json.loads(l) for l in text.splitlines() if l.startswith("{")]
    row = rows[-1] if rows else {"error": "the loop child printed no row"}
    row.update(info)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("selftest", "loop", "both"))
    ap.add_argument("--rcs", default="225,90,56,45,36,32,28")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--vpp-mv", type=float, default=1000.0)
    ap.add_argument("--out")
    ap.add_argument("--no-warm", action="store_true", dest="no_warm")
    a = ap.parse_args()
    if a.what == "selftest":
        selftest()
        return
    if a.what == "both":
        out = open(a.out, "a", encoding="utf-8") if a.out else None
        for rc in [int(x) for x in a.rcs.split(",")]:
            r = both(rc, max(a.seconds, 16.0), a.vpp_mv)
            print(json.dumps(r))
            if out:
                out.write(json.dumps(r) + "\n")
                out.flush()
        return
    board = measure.Board()
    ident = board.ask("v", secs=1.0).strip()
    print(ident)
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    rcs = [int(x) for x in a.rcs.split(",")]
    if not a.no_warm:
        one(board, rcs[0], a.seconds, a.vpp_mv)  # run 0 is thrown away
    for rc in rcs:
        r = one(board, rc, a.seconds, a.vpp_mv)
        r["ident"] = ident
        r.update(provenance.run_fields(board=board))
        print(json.dumps(r))
        if out:
            out.write(json.dumps(r) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
