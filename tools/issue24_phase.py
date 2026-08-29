#!/usr/bin/env python3
"""Issue #24: what the "bidirectional jitter storm" actually is.

The ramp analysis reports matched forward/backward events of +-5-9
samples, thousands per window, and the obvious readings of that are
jitter, aliasing, or the host feed. All three are wrong, and this tool
is what shows it.

**One sample per DAC table wrap comes back low by ~17-30 ADC codes.**
That is the whole phenomenon. A single wrong-valued sample makes the
ramp's position arithmetic report a jump out and a jump straight back
at adjacent indices, which is exactly the "matched pair" signature; the
pairs then recur once per ramp wrap, at a phase that is fixed within a
run and redrawn across runs.

Three measurements separate that from every timing explanation, and the
tool reports all three:

  * **Event spacing is the ramp wrap, not the clock.** Hold every rate
    fixed and change only `--steps`: the spacing moves with the table
    period (512 captured samples at step 8, 1024 at step 4). Halve
    `--dac-sps` and the count halves with the wrap count - 3128 events
    becomes 1564, both exactly 4 per wrap.
  * **The magnitude is codes, not samples.** Mean |n| reads 10.4 at
    step 4, 5.5 at step 8, and nothing at step 16 (the same codes fall
    under the analysis's 3-sample tolerance). n * slope * step is
    constant, which is what a fixed code error looks like when it is
    reported in samples.
  * **There is no line at 522 Hz.** The residual spectrum is flat there
    in storm and clean runs alike; the only line is the wrap rate
    itself, and it tracks `--dac-sps`.

The "~522 Hz, rate-invariant" reading this replaces came from dividing
counts by a nominal 3 s window. The analysis window is the run minus
SETTLE_US - about 2 s - so a 200 ksps window holds 782 wraps and a
100 ksps window 391. A full-rate *forward* count of 1567 is 2/wrap and
a half-rate *total* of 1565 is 4/wrap; 2 x 782 and 4 x 391 are the same
number, so comparing the two quantities makes a count that halves look
like a count that does not.

    .venv/bin/python tools/issue24_phase.py -n 18 --steps 4,8,16
    .venv/bin/python tools/issue24_phase.py -n 8 --dac-sps 100000

Stdlib only, deliberately: both benches must be able to run the same
instrument, and neither venv here has numpy and pyserial together.
"""
import argparse
import cmath
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402

# Block-average by this much before transforming. The band of interest
# is under 3 kHz out of a 100 kHz capture, and a boxcar of 16 puts its
# first null at 6.25 kHz - so the decimation is also the anti-alias
# filter, at the cost of a sinc droop that is corrected below.
DECIM = 16
NFFT = 16384


def _fft(a):
    """Iterative radix-2 Cooley-Tukey. len(a) must be a power of two."""
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    size = 2
    while size <= n:
        ang = -2.0 * math.pi / size
        w = cmath.exp(complex(0, ang))
        half = size >> 1
        for start in range(0, n, size):
            cur = complex(1.0, 0.0)
            for k in range(start, start + half):
                u = a[k]
                v = a[k + half] * cur
                a[k] = u + v
                a[k + half] = u - v
                cur *= w
        size <<= 1
    return a


def phase_residual(ps, step, tag=measure.CH_A0):
    """Sampling-instant error, in DAC samples, per captured sample."""
    vals = ps.series.get(tag)
    if not vals:
        return None
    start = ps._index_at(tag, measure.SETTLE_US)
    tail = vals[start:]
    if len(tail) < 4 * NFFT:
        return None
    period = 4096 // step
    lo, hi = min(tail), max(tail)
    span = hi - lo
    if span <= 0:
        return None
    # Codes per DAC code, from the ramp's own extent - the DAC is not
    # rail to rail, so this is measured and never assumed.
    slope = span / float((period - 1) * step)
    denom = slope * step

    pos = [(v - lo) / denom for v in tail]

    # Undo the sawtooth wrap, and mark the samples either side of it
    # bad: the wrap is a full-scale analog step and those samples are
    # the DAC and the sample-and-hold settling, not a clock reading.
    # Letting a settling transient into the spectrum would put a line
    # at the wrap rate and invite it to be read as a disturbance.
    n = len(pos)
    good = bytearray(b"\x01") * n
    out = [0.0] * n
    bump = 0.0
    for i in range(n):
        if i and pos[i] - pos[i - 1] < -period * 0.4:
            bump += period
            for k in range(max(0, i - 2), min(n, i + 4)):
                good[k] = 0
        out[i] = pos[i] + bump
    if sum(good) < n * 0.5:
        return None

    # Interpolate across the excluded samples rather than dropping them:
    # a hole in a uniformly sampled series is itself a discontinuity.
    last = None
    for i in range(n):
        if good[i]:
            if last is not None and last != i - 1:
                a, b = out[last], out[i]
                for k in range(last + 1, i):
                    out[k] = a + (b - a) * (k - last) / (i - last)
            last = i

    # Remove the nominal advance - two DAC samples per captured sample,
    # fitted rather than assumed so a rate error does not become a ramp
    # in the residual.
    sx = n * (n - 1) / 2.0
    sxx = (n - 1) * n * (2 * n - 1) / 6.0
    sy = sum(out)
    sxy = sum(i * out[i] for i in range(n))
    det = n * sxx - sx * sx
    slope_fit = (n * sxy - sx * sy) / det
    icept = (sy - slope_fit * sx) / n
    return [out[i] - (slope_fit * i + icept) for i in range(n)], slope_fit


def spectrum(resid, fs):
    """Amplitude spectrum of the residual, in DAC samples."""
    m = len(resid) // DECIM
    dec = [sum(resid[i * DECIM:(i + 1) * DECIM]) / DECIM for i in range(m)]
    if m < NFFT:
        return None
    dec = dec[:NFFT]
    mean = sum(dec) / NFFT
    win = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / NFFT)
           for i in range(NFFT)]
    coh = sum(win)
    a = [complex((dec[i] - mean) * win[i], 0.0) for i in range(NFFT)]
    _fft(a)
    df = (fs / DECIM) / NFFT
    half = NFFT // 2
    freq = [k * df for k in range(half)]
    mag = [abs(a[k]) * 2.0 / coh for k in range(half)]
    # Undo the boxcar's droop, so an amplitude in samples reads as an
    # amplitude in samples wherever in the band the line sits. A
    # D-long moving average at fs has |H(f)| = |sin(pi f D / fs)| /
    # (D |sin(pi f / fs)|); at 522 Hz that is 0.99, at 3 kHz it is 0.64,
    # which is a factor worth removing rather than carrying.
    for k in range(1, half):
        num = math.sin(math.pi * freq[k] * DECIM / fs)
        den = DECIM * math.sin(math.pi * freq[k] / fs)
        h = abs(num / den) if den else 1.0
        if h > 0.05:
            mag[k] /= h
    return freq, mag


def band(freq, mag, lo, hi):
    sel = [(mag[k], freq[k]) for k in range(len(freq)) if lo <= freq[k] <= hi]
    return max(sel) if sel else (0.0, 0.0)


def event_geometry(ps, ev, step, tag=measure.CH_A0):
    """Event rate and spacing against the window actually analysed.

    A count divided by the nominal run length is not a rate: the
    analysis starts SETTLE_US in, and the ramp's own wrap sets a natural
    unit the spacing can be read against. Both are reported so nobody
    has to divide a count by a window that was never measured.
    """
    vals = ps.series.get(tag) or []
    start = ps._index_at(tag, measure.SETTLE_US)
    n = len(vals) - start
    fs = ps.measured_rate_hz() or 0.0
    out = {"analysed_samples": n,
           "analysed_s": round(n / fs, 4) if fs else None}
    if fs and n:
        out["ev_rate_hz"] = round(len(ev) / (n / fs), 1)
        # The wrap rate is counted from the data, not computed from the
        # requested dac_sps: the wrap is the ramp's own unit and the
        # question is whether the events are locked to it.
        tail = vals[start:]
        period = 4096 // step
        span = max(tail) - min(tail)
        wraps = sum(1 for k in range(1, len(tail))
                    if tail[k] - tail[k - 1] < -span * 0.4)
        out["wraps"] = wraps
        out["wrap_hz"] = round(wraps / (n / fs), 1)
        out["ev_per_wrap"] = round(len(ev) / wraps, 3) if wraps else None
        out["samples_per_wrap"] = round(n / wraps, 2) if wraps else None
    idx = [i for i, _ in ev]
    # Where in the ramp period the events sit. If they are locked to
    # the table they cluster at one offset; if they are locked to the
    # play ring's slot they cluster at the slot boundaries, which for
    # a table longer than a slot is a different answer.
    if idx and fs:
        tail = vals[start:]
        span = max(tail) - min(tail)
        first = next((k for k in range(1, len(tail))
                      if tail[k] - tail[k - 1] < -span * 0.4), None)
        per = round(out.get("samples_per_wrap") or 0)
        if first is not None and per > 1:
            ph = {}
            for i in idx:
                b = int((i - first) % per) * 16 // per
                ph[b] = ph.get(b, 0) + 1
            out["phase16"] = [ph.get(b, 0) for b in range(16)]
            out["phase_first"] = [int((i - first) % per) for i in idx[:6]]
    if len(idx) > 8:
        gaps = [idx[k] - idx[k - 1] for k in range(1, len(idx))]
        hist = {}
        for g in gaps:
            hist[g] = hist.get(g, 0) + 1
        top = sorted(hist.items(), key=lambda kv: -kv[1])[:4]
        out["gap_top"] = [[g, c] for g, c in top]
        out["gap_median"] = sorted(gaps)[len(gaps) // 2]
        out["gap_mean"] = round(sum(gaps) / len(gaps), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--steps", default=str(measure.RAMP_STEP),
                    help="comma-separated ramp steps, alternated run by "
                         "run so the weather cannot favour one of them")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    steps = [int(x) for x in args.steps.split(",")]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            # Alternated, never blocked: this phenomenon comes and
            # goes on a scale of minutes, so a block of one step
            # followed by a block of the other would compare the
            # weather rather than the steps.
            step = steps[(i - 1) % len(steps)]
            res = measure.run_loop(board, dac_sps=args.dac_sps,
                                   adc_hz=args.adc_hz, channels=2,
                                   ramp=step, seconds=args.seconds)
            ps = res.stream
            ev = measure.ramp_discontinuities(ps, step=step)
            fwd = [n for _, n in ev if n > 4]
            back = [-n for _, n in ev if n < -4]
            row = {
                "run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "bench": args.bench, "dac_sps": args.dac_sps,
                "ramp_step": step,
                "seconds": args.seconds,
                "dev_span_s": round(ps.dev_span_s, 6),
                "fs_per_ch": round(ps.measured_rate_hz() or 0.0, 1),
                "events": len(ev), "fwd": len(fwd), "back": len(back),
                "fwd_samples": sum(fwd), "back_samples": sum(back),
                "under": res.play.underruns if res.play else None,
                "deficit_bytes": res.host_tx_bytes - (res.play.bytes_in or 0),
                "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                "overrun": ps.overrun_frames,
            }
            # Where the events fall, not just how many. windows-desk
            # derived ~522 Hz by dividing a count by a nominal 3 s
            # window; the analysis window is the run minus SETTLE_US,
            # so that divisor is not the one to use. Rate against the
            # window actually analysed, and the spacing histogram, say
            # what the events are locked to without any division.
            row.update(event_geometry(ps, ev, step))

            got = phase_residual(ps, step)
            sp = None
            if got:
                resid, adv = got
                rms = math.sqrt(sum(v * v for v in resid) / len(resid))
                row["resid_rms"] = round(rms, 4)
                row["advance"] = round(adv, 6)
                sp = spectrum(resid, ps.measured_rate_hz() or 100000.0)
            if sp:
                freq, mag = sp
                # Floor: the median over the analysed band, so a line is
                # reported as a multiple of the noise it sits in rather
                # than as an absolute nobody can compare across benches.
                vals = sorted(m for m, f in zip(mag, freq)
                              if 50.0 <= f <= 3000.0)
                floor = vals[len(vals) // 2] if vals else 0.0
                row["floor"] = round(floor, 6)
                order = sorted(range(len(mag)),
                               key=lambda k: mag[k], reverse=True)
                row["peaks"] = [[round(freq[k], 2), round(mag[k], 4),
                                 round(mag[k] / floor, 1) if floor else None]
                                for k in order[:6] if 50.0 <= freq[k] <= 3000.0]
                for name, lo, hi in (("f522", 515.0, 530.0),
                                     ("f391", 386.0, 396.0)):
                    m, f = band(freq, mag, lo, hi)
                    row[name] = round(m, 4)
                    row[name + "_hz"] = round(f, 2)
                    row[name + "_x"] = round(m / floor, 2) if floor else None
                print(f"run {i}: step={step:2d} ev={row['events']:5d} "
                      f"f/b={row['fwd']}/{row['back']}  "
                      f"rms={row['resid_rms']:.3f}samp  "
                      f"floor={floor:.2e}  "
                      f"522Hz={row['f522']:.4f} ({row['f522_x']}x)  "
                      f"evrate={row.get('ev_rate_hz')}Hz "
                      f"gap~{row.get('gap_median')} ev/wrap={row.get('ev_per_wrap')}  "
                      f"top=" + ", ".join(
                          f"{p[0]:.0f}Hz {p[2]}x" for p in row["peaks"][:3]),
                      flush=True)
            else:
                print(f"run {i}: step={step} ev={row['events']} - no residual",
                      flush=True)
            rows.append(row)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
