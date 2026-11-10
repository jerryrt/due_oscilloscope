"""Levels, eyes and gates of a PAM-N capture, from its raw samples.

`docs/ets-pam.md` defines the gates. The pattern is known, so once the clock
is tracked (`etsperiod`) every raw sample can be labelled with the symbol it
belongs to and its position inside that symbol, and everything here is read
from those labelled samples:

* the distribution of each level at the centre of its symbol;
* the ladder: the level means against the DAC codes, and how far each sits
  from the least-squares line;
* for each of the `N - 1` eyes between neighbouring levels, its height at the
  centre and its width.

Samples are placed on a grid of `1 / LABEL_K` tick, and everything is held as
integer histograms over the ADC's 4096 codes, so the memory is `N` histograms
per position, not the samples.

The labelling is numpy array operations in chunks on threads;
`tests/test_etspam.py` holds it to histograms known by hand.
"""
import math
import threading
from array import array

import dsp
import etspattern
import etsperiod

#: Positions per tick of the labelling grid.
LABEL_K = 10
#: Half-width of the centre window, in symbols: the middle fifth of a symbol.
CENTRE_HALF = 0.1
#: Positions across a symbol for the eye widths.
TBINS = 20
#: Percentile at each end for an eye edge, from the plan: 0.1% and 99.9%.
TAIL = 0.001
#: Gates, from the plan.
MIN_SEPARATION_SIGMA = 3.0
MAX_LINEARITY_SPACING = 0.25
MIN_EYE_WIDTH = 0.2
ADC_CODES = 4096
#: `np.bincount` holds the GIL, so serialising its large int64 result costs no
#: time and keeps one such result alive instead of one per thread.
_BINCOUNT = threading.Lock()


def boundary_offset(curve, rc):
    """Where, in ticks modulo `rc`, the edges of a folded staircase fall.

    The transitions between symbols are where the folded curve moves. The
    movement is summed over every symbol at each position modulo `rc`, the
    window of positions carrying most of it is found, and the offset is the
    centre of that movement inside the window, not the window's own centre:
    a window can sit anywhere over an edge that is narrower than it.
    `curve[k + 1] - curve[k]` is the slope at tick `k + 1`, hence the 1.

    Returns ticks in `[-rc / 2, rc / 2)`, the remainder nearest zero. The
    tracker lines the template's symbol boundaries up with the data's edges, so
    they fall near multiples of `rc`, and an edge at 28.9 ticks is one at -0.1,
    not the start of the next symbol: read the other way every label is one
    symbol off.
    """
    np = dsp.np
    c = np.asarray(curve, dtype=np.float64)
    d = np.abs(np.roll(c, -1) - c)
    if len(d) % rc == 0:
        energy = d.reshape(-1, rc).sum(axis=0).tolist()
    else:
        energy = np.bincount(np.arange(len(d)) % rc, weights=d, minlength=rc).tolist()
    return _boundary_from_energy(energy, rc)


def _boundary_from_energy(energy, rc):
    w = max(3, rc // 3)
    phi = max(range(rc), key=lambda p: sum(energy[(p + i) % rc] for i in range(w)))
    weights = [energy[(phi + i) % rc] for i in range(w)]
    total = sum(weights)
    if total <= 0:
        return 0.0
    centre = sum(i * wt for i, wt in enumerate(weights)) / total
    return (phi + centre + 1.0 + rc / 2.0) % rc - rc / 2.0


#: Samples labelled per pass; a multiple of `etsperiod.SEGMENT`, so the phase
#: curve is followed in the same segments as the reference follows it.
CHUNK = 2048 * 512


def label_samples(vals, rc_adc, model, pat, rc_dac, b0, cells=None, start=0):
    np = dsp.np
    nlev = pat.pam
    v_all = np.asarray(vals)

    def part(a, b):
        return label_range(v_all, a, b, rc_adc, model, pat, rc_dac, b0,
                           cells is not None, start)
    parts = dsp.map_ranges(part, len(v_all), etsperiod.SEGMENT)
    centre_n = sum(p[0] for p in parts)
    by_t_n = sum(p[1] for p in parts)
    if cells is not None:
        cells_n = sum(p[2] for p in parts)
        for key in np.nonzero(cells_n)[0].tolist():
            cells[key] = int(cells_n[key])
    centre = [_hist(centre_n[l * ADC_CODES:(l + 1) * ADC_CODES]) for l in range(nlev)]
    by_t = [[None] * nlev for _ in range(TBINS)]
    busy = by_t_n.reshape(TBINS * nlev, ADC_CODES).any(axis=1)
    for tbi in range(TBINS):
        for l in range(nlev):
            if busy[tbi * nlev + l]:
                by_t[tbi][l] = _hist(by_t_n[(tbi * nlev + l) * ADC_CODES:
                                            (tbi * nlev + l + 1) * ADC_CODES])
    return centre, by_t


def _hist(h):
    """A numpy histogram as the reference's `array("I")`, without a Python int per code."""
    out = array("I")
    out.frombytes(h.astype(dsp.np.uint32).tobytes())
    return out


def label_range(v_all, lo, hi, rc_adc, model, pat, rc_dac, b0, want_cells, start):
    """The labelling kernel over samples `lo .. hi`: `(centre, by_t, cells)` as
    flat integer histograms. The GPU backend replaces this function."""
    np = dsp.np
    unit = pat.length * rc_dac
    k = LABEL_K
    nlev = pat.pam
    shift = b0 * k
    span = rc_dac * k
    per_unit = unit * k
    two = 2 * span
    lo_t, hi_t = (0.5 - CENTRE_HALF), (0.5 + CENTRE_HALF)
    syms = np.asarray(pat.symbols, dtype=np.int64)
    # int32 is enough for a worker's share and halves what each thread holds
    centre_n = np.zeros(nlev * ADC_CODES, dtype=np.int32)
    by_t_n = np.zeros(TBINS * nlev * ADC_CODES, dtype=np.int32)
    cells_n = np.zeros(two * ADC_CODES, dtype=np.int32) if want_cells else None
    for i in range(lo, hi, CHUNK):
        m = min(CHUNK, hi - i)
        v = v_all[i:i + m].astype(np.int64)
        idx = dsp.phase_indices(m, rc_adc, lambda x: etsperiod.phase_at(model, x),
                                unit, k, start + i, etsperiod.SEGMENT)
        rel = (idx - shift) % per_unit                     # float when b0 is
        if cells_n is not None:
            key = (rel % two).astype(np.int64) * ADC_CODES + v
            with _BINCOUNT:
                np.add(cells_n, np.bincount(key, minlength=cells_n.size), out=cells_n,
                       casting="unsafe")
        j = (rel // span).astype(np.int64)
        t = (rel - j * span) / span
        lvl = syms[j]
        inside = (t >= lo_t) & (t < hi_t)
        key = lvl[inside] * ADC_CODES + v[inside]
        with _BINCOUNT:
            np.add(centre_n, np.bincount(key, minlength=centre_n.size), out=centre_n,
                   casting="unsafe")
        tb = (t * TBINS).astype(np.int64)
        key = (tb * nlev + lvl) * ADC_CODES + v
        with _BINCOUNT:
            np.add(by_t_n, np.bincount(key, minlength=by_t_n.size), out=by_t_n,
                   casting="unsafe")
    return centre_n, by_t_n, cells_n


def _quantile_rows(h, q, from_top=False):
    """`_quantile` of every row of a 2-D histogram at once: floats, NaN for an empty row."""
    np = dsp.np
    if from_top:
        h = h[..., ::-1]
    cum = np.cumsum(h, axis=-1)
    total = cum[..., -1]
    first = (cum >= (q * total)[..., None]).argmax(axis=-1)
    code = (ADC_CODES - 1 - first) if from_top else first
    return np.where(total == 0, np.nan, code.astype(np.float64))


def _stats(centre):
    """`_stats` of every level, from one matrix: the moments are products with
    the code vector, which is where BLAS takes them."""
    np = dsp.np
    h = np.stack([np.frombuffer(c, dtype=np.uint32) for c in centre]).astype(np.float64)
    codes = np.arange(ADC_CODES, dtype=np.float64)
    n = h.sum(axis=1).tolist()
    s = (h @ codes).tolist()
    ss = (h @ (codes * codes)).tolist()
    lo = _quantile_rows(h.astype(np.int64), TAIL).tolist()
    hi = _quantile_rows(h.astype(np.int64), TAIL, from_top=True).tolist()
    out = []
    for i in range(len(centre)):
        if n[i] == 0:
            out.append({"n": 0, "mean": None, "std": None, "lo": None, "hi": None})
            continue
        mean = s[i] / n[i]
        out.append({"n": int(n[i]), "mean": mean,
                    "std": math.sqrt(max(0.0, ss[i] / n[i] - mean * mean)),
                    "lo": lo[i], "hi": hi[i]})
    return out


def _eye_heights(by_t, nlev):
    """`_eye_heights` with the running sums over levels as cumulative sums."""
    np = dsp.np
    h = np.zeros((TBINS, nlev, ADC_CODES), dtype=np.int64)
    for tb in range(TBINS):
        for i in range(nlev):
            if by_t[tb][i] is not None:
                h[tb, i] = np.frombuffer(by_t[tb][i], dtype=np.uint32)
    lower = np.cumsum(h, axis=1)                         # levels 0..i
    upper = np.cumsum(h[:, ::-1], axis=1)[:, ::-1]       # levels i..top
    lower_hi = _quantile_rows(lower, TAIL, from_top=True)     # (TBINS, nlev)
    up_lo = _quantile_rows(upper, TAIL)
    heights = [[None] * TBINS for _ in range(nlev - 1)]
    for tb in range(TBINS):
        for i in range(1, nlev):
            a, b = up_lo[tb, i], lower_hi[tb, i - 1]
            if not (np.isnan(a) or np.isnan(b)):
                heights[i - 1][tb] = float(a - b)
    return heights


def _longest_open_run(heights):
    best = run = 0
    for h in heights:
        run = run + 1 if (h is not None and h > 0) else 0
        best = max(best, run)
    return best / float(len(heights))


def _ladder_fit(codes, means):
    n = len(codes)
    mx, my = sum(codes) / n, sum(means) / n
    sxx = sum((x - mx) ** 2 for x in codes)
    a = sum((x - mx) * (y - my) for x, y in zip(codes, means)) / sxx
    b = my - a * mx
    return a, b, [y - (a * x + b) for x, y in zip(codes, means)]


def analyze_levels(centre, by_t, pat):
    """The figures the gates read, from the labelled histograms."""
    nlev = pat.pam
    levels = [dict(st, level=i, code=pat.codes[i]) for i, st in enumerate(_stats(centre))]
    out = {"pam": nlev, "levels": levels}
    if any(lv["n"] == 0 for lv in levels):
        out["error"] = "a level has no samples at its symbol centre"
        return out
    means = [lv["mean"] for lv in levels]
    a, b, res = _ladder_fit(pat.codes, means)
    spacing = (means[-1] - means[0]) / (nlev - 1)
    gaps = [y - x for x, y in zip(means, means[1:])]
    sep = min(g / max(levels[i]["std"], levels[i + 1]["std"], 1e-9)
              for i, g in enumerate(gaps))
    heights = _eye_heights(by_t, nlev)
    centre_tb = int(0.5 * TBINS)
    eyes = []
    for i in range(nlev - 1):
        lo, hi = levels[i]["hi"], levels[i + 1]["lo"]
        eyes.append({"eye": i, "height_codes": hi - lo,
                     "width_symbols": _longest_open_run(heights[i]),
                     "height_by_position": heights[i][centre_tb]})
    out.update({
        "slope_adc_per_dac": a, "intercept_adc": b, "spacing_codes": spacing,
        "residual_codes": res, "residual_max_codes": max(abs(r) for r in res),
        "monotone": all(g > 0 for g in gaps),
        "min_separation_sigma": sep, "eyes": eyes,
        "eye_height_min": min(e["height_codes"] for e in eyes),
        "eye_width_min": min(e["width_symbols"] for e in eyes),
    })
    return out


def gates(result, trk):
    """The gates A3 to A6 of the plan, each a `(passed, reason)` pair."""
    g = {}
    g["A3"] = (bool(trk["adequate"]),
               "model adequate %s, common factor %d" % (trk["adequate"], trk["lattice_gcd"]))
    if "error" in result:
        for k in ("A4", "A5", "A6"):
            g[k] = (False, result["error"])
        return g
    g["A4"] = (result["monotone"] and result["min_separation_sigma"] >= MIN_SEPARATION_SIGMA,
               "monotone %s, smallest separation %.1f sigma (need %.0f)"
               % (result["monotone"], result["min_separation_sigma"], MIN_SEPARATION_SIGMA))
    limit = MAX_LINEARITY_SPACING * result["spacing_codes"]
    g["A5"] = (result["residual_max_codes"] <= limit,
               "largest residual %.2f codes against %.2f (a quarter of a level)"
               % (result["residual_max_codes"], limit))
    g["A6"] = (result["eye_height_min"] > 0 and result["eye_width_min"] >= MIN_EYE_WIDTH,
               "smallest eye height %.1f codes, smallest width %.2f symbols (need %.1f)"
               % (result["eye_height_min"], result["eye_width_min"], MIN_EYE_WIDTH))
    return g


def analyze(vals, rc_adc, pat, rc_dac, start=0, want_eye=False):
    """Track the clock, label every sample, and return the figures and gates.

    `vals` are ADC codes of one channel; `pat` is an `etspattern.Pattern`.
    With `want_eye` the result carries an `"eye"` document for the page script.
    """
    trk = etsperiod.track_clock_ratio(vals, rc_adc, pat.symbols, rc_dac,
                                      start=start, levels=pat.pam)
    unit = pat.length * rc_dac
    curve, cnt = etsperiod.fold_warped(vals, rc_adc, trk["model"], unit, 1, start)
    if min(cnt) == 0:
        curve = _fill_holes(curve)
    b0 = boundary_offset(curve, rc_dac)
    cells = {} if want_eye else None
    centre, by_t = label_samples(vals, rc_adc, trk["model"], pat, rc_dac, b0, cells, start)
    res = analyze_levels(centre, by_t, pat)
    res.update({"samples": len(vals), "rc_dac": rc_dac, "rc_adc": rc_adc,
                "delta_ppm": trk["delta"] * 1e6, "b0_ticks": b0,
                "model_adequate": trk["adequate"], "lattice_gcd": trk["lattice_gcd"],
                "phase_rms_ticks": trk["model"]["rms"],
                "time_axis_sigma_ns": trk["model"]["sigma_model"] * 1e9 / 45e6,
                "fold_holes": sum(1 for c in cnt if c == 0)})
    res["gates"] = {k: {"passed": ok, "why": why} for k, (ok, why) in gates(res, trk).items()}
    if want_eye:
        res["eye"] = eye_document(res, cells, centre, curve, pat, rc_dac, b0)
    return res


def eye_document(res, cells, centre, curve, pat, rc_dac, b0):
    """What `tools/ets_pam_page.py` draws: density, levels, eyes, gates.

    Millivolts at the ADC pin are `code * 3300 / 4095`; the page does that.
    """
    ys = [key % ADC_CODES for key in cells]
    lo = max(0, min(ys) - 4)
    hi = min(ADC_CODES - 1, max(ys) + 4)
    merged = [0] * (hi - lo + 1)
    for h in centre:
        for c in range(lo, hi + 1):
            merged[c - lo] += h[c]
    keep = ("pam", "levels", "slope_adc_per_dac", "intercept_adc", "spacing_codes",
            "residual_codes", "residual_max_codes", "monotone", "min_separation_sigma",
            "eyes", "eye_height_min", "eye_width_min", "samples", "rc_dac", "rc_adc",
            "delta_ppm", "model_adequate", "lattice_gcd", "time_axis_sigma_ns", "gates")
    doc = {k: res[k] for k in keep if k in res}
    levels = []
    for lv in doc.get("levels", []):
        levels.append({k: lv[k] for k in ("level", "code", "n", "mean", "std", "lo", "hi")})
    doc["levels"] = levels
    doc.update({
        "k": LABEL_K, "tick_ns": 1e9 / 45e6, "ui_ticks": rc_dac,
        "nx": 2 * rc_dac * LABEL_K, "ymin_code": lo, "ymax_code": hi,
        "adc_mv_per_code": 3300.0 / 4095,
        "cells": [[key // ADC_CODES, key % ADC_CODES, c] for key, c in cells.items()],
        "centre_hist": merged, "pattern": {"pam": pat.pam, "n": pat.n, "length": pat.length,
                                             "swing_mv": pat.swing_mv, "codes": pat.codes}})
    return doc


def _fill_holes(curve):
    """Bins nothing landed in, filled from their nearest neighbours."""
    n = len(curve)
    out = list(curve)
    for i, c in enumerate(curve):
        if c is not None:
            continue
        lo = next((curve[(i - d) % n], d) for d in range(1, n) if curve[(i - d) % n] is not None)
        hi = next((curve[(i + d) % n], d) for d in range(1, n) if curve[(i + d) % n] is not None)
        out[i] = (lo[0] * hi[1] + hi[0] * lo[1]) / (lo[1] + hi[1])
    return out
