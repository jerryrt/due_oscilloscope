#!/usr/bin/env python3
"""A PRBS7 from one Due, captured by another, folded with its own clock.

    ets_cross.py both --rc 28 --seconds 16 [--play-dut dut1 --cap-dut dut2]
    ets_cross.py analyze RAW.bin --rc-dac 28 --rc-adc 45

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


def capture(seconds, out):
    board = measure.Board()
    hz = measure.hz_for(ADC_RC)
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


def analyze(path, rc_dac, rc_adc):
    raw = array.array("H")
    with open(path, "rb") as f:
        raw.frombytes(f.read())
    vals = [float(v) for v in raw[:MAX_SAMPLES]]
    bits = e.prbs7()
    bins = len(bits) * rc_dac
    trk = etsperiod.track_clock_ratio(vals, rc_adc, bits, rc_dac)
    curve, cnt = etsperiod.fold_scaled(vals, rc_adc, trk["period"], bins)
    row = {"samples": len(vals), "rc_dac": rc_dac, "rc_adc": rc_adc,
           "delta_ppm": trk["delta"] * 1e6, "period_ticks": trk["period"],
           "track_blocks": trk["blocks"], "track_rms_ticks": trk["rms"],
           "track_edge_hits": trk["edge_hits"],
           "coverage": eqtime.coverage(cnt), "min_per_bin": min(cnt)}
    if row["coverage"] < 1.0:
        row["error"] = "fold has holes"
        return row
    fig, b0 = e.analyze(curve, rc_dac, bits)
    row.update(fig)
    scale = bins / trk["period"]
    step = rc_adc % trk["period"]
    ph = 0.0
    edge = [False] * bins
    for j in range(len(bits)):
        c = int(round(b0 + j * rc_dac))
        for x in range(-(rc_dac // 4), rc_dac // 4 + 1):
            edge[(c + x) % bins] = True
    blocks = []                      # (flat sum, flat n, edge sum, edge n) per 1,024
    sf = se = 0.0
    nf = ne = 0
    for n, v in enumerate(vals, 1):
        i = min(int(ph * scale), bins - 1)
        r = v - curve[i]
        if edge[i]:
            se += r * r
            ne += 1
        else:
            sf += r * r
            nf += 1
        ph += step
        if ph >= trk["period"]:
            ph -= trk["period"]
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
                          str(a.seconds), "--raw", raw], env=env_c,
                         stdout=subprocess.PIPE, text=True, timeout=a.seconds + 120)
    play_out, _ = src.communicate(timeout=play_s + 120)

    def last(text):
        rows = [json.loads(x) for x in text.splitlines() if x.startswith("{")]
        return rows[-1] if rows else {"error": "no row printed"}
    prow, crow = last(play_out), last(cap.stdout)
    row = {"play": prow, "capture": crow}
    if crow.get("bad") or not crow.get("samples") or crow.get("rc_adc") != ADC_RC:
        row["error"] = "capture not analysable: %s" % (
            crow.get("bad") or crow.get("error") or "rate mismatch")
        return row
    row.update(analyze(raw, a.rc, crow["rc_adc"]))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("both", "play", "capture", "analyze"))
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
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.what == "play":
        print(json.dumps(play(a.rc, a.seconds, a.vpp_mv)))
        return
    if a.what == "capture":
        print(json.dumps(capture(a.seconds, a.raw)))
        return
    row = (analyze(a.raw_in, a.rc_dac or a.rc, a.rc_adc) if a.what == "analyze"
           else both(a))
    print(json.dumps(row))
    if a.out:
        with open(a.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
