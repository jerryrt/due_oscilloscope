#!/usr/bin/env python3
"""Issue #5 in the frequency domain: is the site set a comb?

    .venv/bin/python tools/issue5_spectrum.py
    .venv/bin/python tools/issue5_spectrum.py --json out.jsonl

Needs no board; reads the committed `records/issue5-*.jsonl`.

## Why look here at all

The site table answers "which positions" and says nothing about
"spaced how". At FWS 6 the six sites every bench draws are 12, 33, 117,
138, 159 and 180, and those are not six arbitrary positions: they are
all congruent to 12 modulo 21. Written as a comb, they are k = 0, 1, 5,
6, 7 and 8 of the twelve lattice points `12 + 21k (mod 256)`.

A statement like that is worth nothing asserted from six numbers, which
is why this file exists rather than a sentence in a document. It
measures the periodicity with a null model and a scan correction, and it
reports the answer whether or not it is the one above.

## The two instruments, and why there are two

**Circular concentration** (`comb_score`) is the one that works on what
the old records actually store. For a candidate period p it folds every
site position to a phase on p and takes the resultant length

    R(p) = | (1/n) * sum over sites of exp(2*pi*i*b/p) |

R = 1 means every site sits at the same phase of p - a perfect comb.
R near 1/sqrt(n) is what scattered positions give. `CLAUDE.md` requires
circular statistics on a folded phase rather than a linear spread, and
for the same reason: a linear spread of positions either side of a wrap
reports a disagreement that is not there.

**The DFT of the profile** (`profile_spectrum`) is the stronger reading
and needs the whole 256-point fold, which rows only carry from
2026-09-13. Where a row has one it is used; where it does not, the
comb score runs on the site positions alone and says so. A comb of
period p in a 256-point profile puts its energy at bin 256/p and its
multiples - non-integer for p = 21, so the line is split between
neighbouring bins rather than landing in one. That leakage is the reason
the integer-period score is the primary instrument here and the DFT is
the corroborating one, not the other way round.

## The null model, and the scan

`comb_score` is maximised over every period from `PMIN` to `PMAX`, so
the best R is a maximum over ~126 candidates and is biased upward by the
search. `comb_pvalue` therefore compares it against the **same maximised
statistic** computed on random position sets of the same size - not
against R at one period. A p-value that forgot the scan would call a
comb in noise about half the time; this one is checked against exactly
that case in `tests/test_issue5_spectrum.py`.

The null draws positions uniformly from 0..bins-1. That is the honest
simple null and it is not a complete one: real sites are the strongest
few of a larger set and may be constrained in ways a uniform draw is
not. What the p-value licenses is "not uniform scatter", which is the
claim being made.
"""
import argparse
import cmath
import collections
import glob
import json
import math
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")

#: One cycle of the DAC table, pair-differenced.
BINS = 256

#: Periods worth testing. Below 3 a comb is meaningless; above half the
#: record a "period" cannot repeat enough to be one.
PMIN, PMAX = 3, BINS // 2

#: Draws for the permutation null. 20,000 puts the resolution of the
#: p-value at 5e-5, which is finer than any claim made from it.
NDRAW = 20000


def comb_score(positions, period, bins=BINS):
    """Resultant length of the site positions folded onto `period`.

    1.0 is a perfect comb; a scattered set of n positions gives about
    1/sqrt(n). Circular, so it does not care where the wrap falls.
    """
    if not positions:
        return 0.0
    acc = sum(cmath.exp(2j * math.pi * (b % period) / period)
              for b in positions)
    return abs(acc) / len(positions)


def best_comb(positions, bins=BINS, pmin=PMIN, pmax=PMAX):
    """The period that folds the positions tightest, and its score.

    **Ties go to the LARGEST period, and the reason is the whole
    reading.** If every site is congruent mod 21 then every site is
    also congruent mod 7 and mod 3, so R = 1 at all three - the
    divisors of a true period score exactly as well as the period. The
    smallest is the weakest true statement ("all the sites are
    multiples of 3"); the largest is the generator, and it is the one
    that predicts where the other lattice points are.

    Reporting the smallest was this function's first behaviour and it
    described a period-21 comb on three benches as "period 3", which is
    true, useless, and would have hidden the lattice entirely.

    No multiple of a true period ties with it - positions congruent mod
    21 fall into two phases mod 42 - so taking the largest does not run
    away upward.
    """
    best = (0.0, None)
    for p in range(pmin, min(pmax, bins) + 1):
        r = comb_score(positions, p, bins)
        if r > best[0] + 1e-9 or (abs(r - best[0]) <= 1e-9 and best[1]):
            if r > best[0] + 1e-9 or p > best[1]:
                best = (max(r, best[0]), p)
    return best


def comb_pvalue(positions, bins=BINS, ndraw=NDRAW, seed=0,
                pmin=PMIN, pmax=PMAX):
    """P(a uniform set of the same size scans to a comb this tight).

    **One scalar statistic - `best_comb`'s maximum R - compared against
    the same maximum on every draw.** The scan over ~126 periods is
    therefore charged to the null as well, which is the whole
    correction: an observed maximum compared against a null taken at one
    fixed period is the version of this test that cannot fail.

    The period is reported beside this number and is NOT part of it.
    That distinction cost a rewrite. The first version conjoined "and at
    a period at least this long" onto the null condition, which reads as
    a sharper test and is not a p-value at all: for a uniform set the
    maximum R already exceeds the null's about half the time by
    symmetry, and the extra condition then cuts the count *further*,
    so the number came out small on noise. Measured, not reasoned:
    6 of 25 uniform draws scored below 0.05 on it, against the 1 or 2
    a calibrated 5% threshold allows. `tests/test_issue5_spectrum.py`
    is where that showed up.

    For a period fixed in advance use `fixed_period_pvalue`, which is
    exact and far better powered - and which is the test the campaign
    arm pre-registers, since period 21 came out of this scan and cannot
    be tested on the data that produced it.
    """
    n = len(positions)
    if n < 3 or ndraw <= 0:
        return None
    obs, obsp = best_comb(positions, bins, pmin, pmax)
    rng = random.Random(seed)
    hits = 0
    for _ in range(ndraw):
        draw = rng.sample(range(bins), n)
        if best_comb(draw, bins, pmin, pmax)[0] >= obs - 1e-9:
            hits += 1
    return {"p": (hits + 1) / (ndraw + 1), "statistic": "max R over the scan",
            "period_reported_not_tested": obsp, "ndraw": ndraw}


def fixed_period_pvalue(positions, period, bins=BINS, ndraw=NDRAW, seed=0):
    """P(a uniform set concentrates on THIS period as tightly).

    No scan, so no correction and no bias: exactly calibrated, and much
    the stronger test. Only valid for a period chosen before the data -
    which period 21 now is for any arm taken after 2026-09-13, and is
    not for the rows it was found in.
    """
    n = len(positions)
    if n < 3 or ndraw <= 0:
        return None
    obs = comb_score(positions, period, bins)
    rng = random.Random(seed)
    hits = sum(1 for _ in range(ndraw)
               if comb_score(rng.sample(range(bins), n), period, bins)
               >= obs - 1e-9)
    return {"p": (hits + 1) / (ndraw + 1), "period": period,
            "R": round(obs, 4), "ndraw": ndraw,
            "statistic": "R at a period fixed in advance"}


#: A lattice with many more points than sites predicts nothing: at
#: period 3 the "missing" points are 81 of the 85 positions on the
#: lattice, which no re-run could fail to confirm. A prediction is only
#: reported where the comb is sparse enough for it to be falsifiable.
PREDICT_MAX_RATIO = 3.0


def lattice(positions, period, bins=BINS):
    """Describe the positions as members of one `period` comb.

    Returns the offset, which lattice indices are occupied, and which
    are not - the missing ones being where a site would be if the comb
    were complete. That is a prediction a re-run can check, which is the
    only thing that makes this reading worth more than a pattern.
    """
    if not positions:
        return None
    # Circular mean phase -> the offset the comb sits at.
    acc = sum(cmath.exp(2j * math.pi * (b % period) / period)
              for b in positions)
    off = (cmath.phase(acc) / (2 * math.pi) * period) % period
    # Only the points that fit inside ONE cycle. This used to add
    # `bins % period` as an extra k, which wraps: at period 21 in 256
    # bins it emitted 12 + 21*12 = 264 -> 8, and 8 is not congruent to
    # 12 mod 21. That phantom point went into a pre-registered
    # prediction on #5 as "8, 54, 75, ...", so a real arm was asked to
    # confirm a position the lattice never contained.
    pts = []
    k = 0
    while round(off + period * k) < bins:
        pts.append(round(off + period * k))
        k += 1
    pts = sorted(set(pts))
    occupied, residual = [], []
    for b in positions:
        near = min(pts, key=lambda q: min(abs(q - b), bins - abs(q - b)))
        d = min(abs(near - b), bins - abs(near - b))
        occupied.append(near)
        residual.append(d)
    return {"period": period, "offset": round(off, 2),
            "points": pts, "occupied": sorted(set(occupied)),
            "missing": [q for q in pts if q not in set(occupied)],
            "max_residual": max(residual) if residual else 0,
            "on_lattice": sum(1 for d in residual if d == 0),
            "n": len(positions)}


def phase_table(positions, period, bins=BINS):
    """Every position's phase on a FIXED period, with the resultant.

    `best_comb` fits a period; this one is handed the period and asks
    what each wait state does on it. That distinction is the difference
    between "FWS 5 has a comb of its own" and "FWS 5 sits on FWS 6's
    comb at a different offset" - and only the second is a statement
    about one structure, so only the second is worth making.
    """
    mods = [b % period for b in positions]
    acc = sum(cmath.exp(2j * math.pi * m / period) for m in mods)
    R = abs(acc) / len(mods) if mods else 0.0
    off = (cmath.phase(acc) / (2 * math.pi) * period) % period if mods else 0.0
    return {"period": period, "phases": mods, "R": round(R, 4),
            "offset": round(off, 2),
            "histogram": dict(sorted(collections.Counter(mods).items()))}


def predict_missing(positions, period, bins=BINS):
    """Where the sites a truncated row dropped should be, if it is a comb.

    The lattice through the observed sites has more points than the
    sites occupy. If the comb is the structure and the record is merely
    truncated, the dropped sites are at the unoccupied points - which is
    a prediction with a number in it, checkable by one re-run with the
    fixed tool, and falsifiable by any dropped site that lands
    elsewhere.

    Stated here rather than in prose so that it is registered before the
    data that tests it exists.
    """
    L = lattice(positions, period, bins)
    if L is None or not positions:
        return None
    if len(L["points"]) > PREDICT_MAX_RATIO * len(positions):
        return None
    return L["missing"]


def across_fws(per_fws, period=None):
    """Whether the wait states share one comb, and at what offsets.

    `period` defaults to the period the wait state with the tightest
    comb selects - so the others are read on a period that was not
    fitted to them. Reporting each wait state's own best period instead
    would let three different periods look like three different
    structures when they are one structure sampled differently.
    """
    fitted = [(a["comb"]["R"], a["comb"]["period"], f)
              for f, a in per_fws.items() if a and a.get("comb")]
    if not fitted:
        return None
    fitted.sort(reverse=True)
    if period is None:
        period = fitted[0][1]
    out = {"period": period, "chosen_from_fws": fitted[0][2], "by_fws": {}}
    for f, a in per_fws.items():
        if not a or not a["strong"]:
            continue
        t = phase_table(a["strong"], period)
        t["sites"] = a["strong"]
        out["by_fws"][str(f)] = t
    return out


def dft(series):
    """Magnitude spectrum, bins 0..n/2. Plain O(n^2) transform.

    256 points, so it is 65k complex operations and needs no library -
    the same reasoning that put a Goertzel rather than an FFT package in
    `host/`.
    """
    n = len(series)
    if n == 0:
        return []
    mean = sum(series) / n
    out = []
    for k in range(n // 2 + 1):
        acc = sum((v - mean) * cmath.exp(-2j * math.pi * k * i / n)
                  for i, v in enumerate(series))
        out.append(abs(acc) * 2 / n)
    return out


def profile_spectrum(profiles):
    """Mean magnitude spectrum over a wait state's profiles, if stored.

    Rows carry `profile` only from 2026-09-13. Returns None where they
    do not, rather than inventing a series - a spectrum synthesised from
    six impulses is not a spectrum of the signal.
    """
    if not profiles:
        return None
    spec = None
    for p in profiles:
        s = dft(p)
        spec = s if spec is None else [a + b for a, b in zip(spec, s)]
    return [round(v / len(profiles), 4) for v in spec]


def site_series(phases, bins=BINS):
    """The recorded sites as an impulse train, weighted by incidence.

    Each position carries its median deviation times the fraction of
    runs that drew it. This is what the comb reading has to work from
    when there is no stored profile, and it is a censored view of the
    real one: it holds only the sites a row had room for.
    """
    ser = [0.0] * bins
    for ph in phases:
        ser[ph["phase"] % bins] = ph["median"] * (ph["count"] / ph["n"])
    return ser


def analyse(rows, fws, bins=BINS, seed=0, ndraw=NDRAW, cut=0.5):
    """Everything this file has to say about one arm at one wait state."""
    v = [r for r in rows if r.get("fws") == fws]
    if not v:
        return None
    counts = collections.Counter(b for r in v for b, _x, _z in r["sites"])
    strong = sorted([b for b, k in counts.items() if k >= cut * len(v)])
    phases = []
    for ph in sorted(counts):
        vals = [x for r in v for b, x, _z in r["sites"] if b == ph]
        phases.append({"phase": ph, "count": counts[ph], "n": len(v),
                       "median": statistics.median(vals)})

    out = {"fws": fws, "n_runs": len(v), "strong": strong,
           "all_positions": sorted(counts)}
    if len(strong) >= 3:
        r, p = best_comb(strong, bins)
        pv = comb_pvalue(strong, bins, ndraw, seed)
        out["comb"] = {"period": p, "R": round(r, 4), "p_value": pv,
                       "fixed21": fixed_period_pvalue(strong, 21, bins,
                                                      ndraw, seed),
                       "ndraw": ndraw,
                       "chance_R": round(1 / math.sqrt(len(strong)), 4)}
        out["lattice"] = lattice(strong, p, bins)
        out["predicted_missing"] = predict_missing(strong, p, bins)
    else:
        out["comb"] = None
        out["lattice"] = None

    stored = [r["profile"] for r in v if r.get("profile")]
    out["profiles_stored"] = len(stored)
    spec = profile_spectrum(stored)
    out["spectrum"] = spec
    out["spectrum_source"] = "profile" if spec else "sites"
    if spec is None:
        spec = dft(site_series(phases, bins))
        out["spectrum"] = [round(x, 4) for x in spec]
    peaks = sorted(range(1, len(spec)), key=lambda k: -spec[k])[:6]
    out["top_bins"] = [{"bin": k, "period": round(bins / k, 2),
                        "mag": round(spec[k], 4)} for k in peaks]
    return out


def arms():
    out = {}
    pats = ("issue5-onimage-*.jsonl", "issue5-fws5-repeat-*.jsonl",
            "issue5-campaign-*.jsonl")
    for path in sorted(sum((glob.glob(os.path.join(RECORDS, q))
                            for q in pats), [])):
        with open(path) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        if rows:
            out[os.path.basename(path)] = rows
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ndraw", type=int, default=NDRAW)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rows_out, cross = [], []
    for name, rows in arms().items():
        print(f"\n{'=' * 72}\n{name}")
        for fws in (4, 5, 6):
            a = analyse(rows, fws, seed=args.seed, ndraw=args.ndraw)
            if a is None:
                continue
            a["file"] = name
            rows_out.append(a)
            print(f"  FWS {fws}  n={a['n_runs']}  sites {a['strong']}")
            if not a["comb"]:
                print("    fewer than three sites at the cut-off; no comb "
                      "reading")
                continue
            c, L = a["comb"], a["lattice"]
            pv = c["p_value"] or {}
            print(f"    comb: period {c['period']:3d}  R = {c['R']:.4f} "
                  f"(scatter would give {c['chance_R']:.3f})")
            if pv:
                print(f"          p = {pv['p']:.2e}  ({pv['statistic']}, "
                      f"{pv['ndraw']} draws)")
            fp = c.get("fixed21")
            if fp:
                print(f"          R at period 21 = {fp['R']:.4f}, "
                      f"p = {fp['p']:.2e} (period fixed in advance; valid "
                      f"only for rows taken after 2026-09-13)")
            print(f"    lattice {L['on_lattice']}/{L['n']} exactly on "
                  f"{L['period']}k + {L['offset']:.0f}, worst residual "
                  f"{L['max_residual']}")
            if L["missing"]:
                print(f"    lattice points with no recorded site: "
                      f"{L['missing']}")
            print(f"    spectrum from {a['spectrum_source']}: top bins "
                  + ", ".join(f"k={t['bin']} (period {t['period']})"
                              for t in a["top_bins"][:3]))
            if a.get("predicted_missing"):
                print(f"    IF the comb is the structure, the sites this "
                      f"row could not store are at {a['predicted_missing']}")
        xf = across_fws({f: analyse(rows, f, seed=args.seed,
                                    ndraw=0) for f in (4, 5, 6)})
        if xf:
            print(f"  -- the wait states on ONE period ({xf['period']}, "
                  f"fitted on FWS {xf['chosen_from_fws']}) --")
            for f, t in sorted(xf["by_fws"].items()):
                print(f"     FWS {f}: phases {t['histogram']}  "
                      f"R={t['R']:.3f}  offset={t['offset']:.2f}")
            xf["file"] = name
            cross.append(xf)
    if args.json:
        with open(args.json, "w") as fh:
            for r in rows_out:
                fh.write(json.dumps(r) + "\n")
            for r in cross:
                fh.write(json.dumps({"cross_fws": r}) + "\n")
        print(f"\nwrote {len(rows_out)} rows to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
