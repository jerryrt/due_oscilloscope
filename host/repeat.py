"""Phase 0: measure the ruler before the thing.

`docs/measurement-suite.md` item 2. No tolerance gets written until its
own repeatability has been measured, because a tolerance is a claim
about spread and this project has repeatedly guessed one.

The evidence that it is not a formality is already in the record. Slew
read 1.991 / 1.893 / 2.110 V/us across three timebases in a single run -
a 5% spread from the *instrument*. `status.md` said the transport
spread was "about 5%" and IN turned out to span 40% once someone
interleaved a reflash between the arms. And two hypotheses died in one
day on issue #6 after looking like clean signal at four points.

Three things follow, and they are the whole design of this module.

**The spread is recorded, not only the tolerance derived from it.** A
tolerance is one number and it throws away the evidence that produced
it. `n`, the observed spread and the axis are stored beside it so that
"was seven enough" stays answerable by whoever reads it next, instead of
evaporating into a single figure nobody can re-examine.

**The axis is a result, not an input.** Some metrics should be
identical across a reflash and some are known not to be - issue #5's
draw changes with the binary. Measuring in-place spread and
across-reflash spread separately is what tells a metric's tolerance
which one it comes from. Picking one axis for the whole suite was the
first version of this rule and it was wrong: OUT and duplex hold to 1%
in place, and only IN needed the interleaving.

**A derived tolerance says how it was derived.** `suggest_tolerance()`
multiplies the observed half-width by a factor that is a stated choice
and not a measurement, and the record says so. Seven points bound the
observed spread; they bound nothing about the tail.

This module is deliberately board-free and instrument-free: it takes
values and returns statistics, so `tests/test_repeat.py` can run the
whole of it on synthetic series. That is not a stylistic preference.
Every scope-side number this project took before `host/trace.py` was
built the same way was wrong in a way a bench run could not see, and
six bugs in the analysis of one experiment were caught by synthetic
tests rather than by the bench - including two that produced confident
wrong *positive* results.
"""
from __future__ import annotations

import json
import math
import os
import statistics

#: Keys that name a row rather than measure it. A metric that returns a
#: list of dicts - `settle`'s bands, `step`'s timebases - is flattened
#: under the row's own label instead of its position, so a run that
#: skipped a band lines up with one that did not. Order is preference.
LABEL_KEYS = ("codes", "code", "timebase_s", "rc", "rate_hz", "hz",
              "trigger_hz", "points")

#: What `suggest_tolerance()` multiplies the observed half-width by.
#:
#: A stated choice, not a derivation. Seven points describe the seven
#: points; the eighth is not bounded by them, and this project has
#: twice watched a tight-looking series come apart on the fifth. Two is
#: enough to keep a tolerance off the observed edge without making it
#: so loose it stops being a test - the rule `baseline.json` already
#: states in its own `_comment`.
TOLERANCE_FACTOR = 2.0


def _label(row):
    """The name of a row in a metric's result list, and the key it came
    from, or (None, None).

    The key is returned so the caller can drop it from the row's values.
    A label is what a row *is*, not something measured about it: every
    run reports `codes = 2.0` for the two-code band, so keeping it would
    put a column of guaranteed-zero spread in every report and invite
    someone to read stability into it.
    """
    for k in LABEL_KEYS:
        if k in row and isinstance(row[k], (int, float)):
            v = row[k]
            return (f"{v:g}" if isinstance(v, float) else str(v)), k
    return None, None


def flatten(obj, prefix=""):
    """Flat `key -> number` pairs from whatever a metric returned.

    Nested dicts join with a dot. Lists of dicts use the row's own label
    where it has one - `bands.2.last_s` names the two-code band -
    because the position of a row is an accident of the loop that
    produced it and the band it describes is not.

    Non-numbers are dropped rather than stringified: a series is
    something you can take a spread of, and a field that is not is not
    part of one. Booleans are kept as 0/1 - "did this row hit the window
    limit" is a fact whose run-to-run stability is worth seeing.
    """
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).startswith("_"):
                continue
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            name, lkey = _label(v) if isinstance(v, dict) else (None, None)
            row = {k: x for k, x in v.items() if k != lkey} if lkey else v
            out.update(flatten(row, f"{prefix}{name if name else i}."))
    elif isinstance(obj, bool):
        out[prefix.rstrip(".")] = int(obj)
    elif isinstance(obj, (int, float)) and math.isfinite(obj):
        out[prefix.rstrip(".")] = obj
    return out


def summarise(values):
    """The spread of one metric key, and enough to re-examine it.

    `spread` is max - min, the thing actually observed. `half_width` is
    the larger distance from the median to either end, which is what a
    symmetric tolerance has to cover and is not spread/2 on an
    asymmetric series. `spread_rel` is against the median's magnitude
    and is None when the median is zero, rather than an infinity that
    would sort to the top of a report.

    `n` is carried because a spread from three points and a spread from
    seven are not the same claim, and the difference has to survive into
    whatever reads this.
    """
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return {"n": 0}
    lo, hi = min(vals), max(vals)
    med = statistics.median(vals)
    half = max(abs(hi - med), abs(med - lo))
    return {
        "n": len(vals),
        "min": lo,
        "max": hi,
        "median": med,
        "mean": statistics.fmean(vals),
        "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "spread": hi - lo,
        "half_width": half,
        "spread_rel": (hi - lo) / abs(med) if med else None,
        "n_missing": len(list(values)) - len(vals),
    }


def suggest_tolerance(stats, floor=0.0):
    """A tolerance from the observed spread, and never from a hope.

    Returns None for a series too short to have a spread: one point has
    no repeatability and a tolerance derived from it would be zero,
    which is the tightest possible lie.

    `floor` is for a metric with a known quantum - the scope's screen
    level, one DAC code - where a spread smaller than the resolution is
    an artifact of the ruler rather than a property of the thing. Pass
    it, and the tolerance never claims to be finer than the instrument.
    """
    if stats.get("n", 0) < 2:
        return None
    return max(TOLERANCE_FACTOR * stats["half_width"], floor)


def entry(stats, axis, floor=0.0):
    """One promotable line: the tolerance, and the evidence for it.

    The shape agreed on issue #6. `baseline.json` stores tolerances
    today and throws the evidence away; an entry carries `n`, the
    observed spread and the axis it was taken on, so a spread that
    later grows is visible as a changed spread rather than only as a
    failing assertion.
    """
    return {
        "median": stats.get("median"),
        "n": stats.get("n", 0),
        "spread": stats.get("spread"),
        "spread_rel": stats.get("spread_rel"),
        "axis": axis,
        "tolerance": suggest_tolerance(stats, floor),
        "tolerance_from": (
            f"{TOLERANCE_FACTOR:g}x the observed half-width"
            + (f", floored at {floor:g}" if floor else "")),
    }


def series(records, key, axis=None):
    """Every value of one key across runs, in the order they were taken.

    Order matters and is preserved: a drift is a different finding from
    a scatter, and only the sequence tells them apart.
    """
    return [r.get("values", {}).get(key)
            for r in records
            if not r.get("error") and (axis is None or r.get("axis") == axis)]


def keys(records):
    """Every metric key seen, in first-seen order across all runs.

    Union rather than intersection, on purpose: a key that appears in
    six runs of seven is a finding - the run that lacked it did
    something different - and an intersection would silently hide it.
    `n_missing` in the summary is where it shows up.
    """
    seen = []
    for r in records:
        for k in r.get("values", {}):
            if k not in seen:
                seen.append(k)
    return seen


def axes(records):
    """The axes present, in first-seen order."""
    seen = []
    for r in records:
        a = r.get("axis")
        if a and a not in seen:
            seen.append(a)
    return seen


def summarise_all(records, floors=None):
    """Per axis, per key: the spread, and a tolerance that states its
    own derivation.

    Failed runs are counted and excluded from the statistics rather than
    dropped silently. A metric that only manages five runs of seven has
    a repeatability problem of its own, and it is one that a spread over
    the five that worked cannot show.
    """
    floors = floors or {}
    out = {}
    for ax in axes(records) or [None]:
        runs = [r for r in records if ax is None or r.get("axis") == ax]
        ok = [r for r in runs if not r.get("error")]
        block = {
            "runs": len(runs),
            "failed": len(runs) - len(ok),
            "errors": sorted({r["error"] for r in runs if r.get("error")}),
            "keys": {},
        }
        for k in keys(ok):
            st = summarise(series(ok, k, axis=ax))
            block["keys"][k] = {**st,
                                **entry(st, ax, floors.get(k, 0.0))}
        out[ax or "unspecified"] = block
    return out


def compare_axes(summary, a, b):
    """Which keys care about the second axis, and by how much.

    The question Phase 0 exists to answer per metric: is this metric's
    spread across a reflash bigger than its spread in place? Reported as
    a ratio so that "1.0 means the axis bought nothing" is readable at a
    glance, and sorted worst first because that is the row that decides
    which axis the tolerance comes from.

    A key whose in-place spread is zero gives a ratio of None rather
    than an infinity: a metric that did not move at all in place has no
    denominator, and saying so is more honest than reporting a very
    large number.
    """
    ka = summary.get(a, {}).get("keys", {})
    kb = summary.get(b, {}).get("keys", {})
    rows = []
    for k in ka:
        if k not in kb:
            continue
        sa, sb = ka[k]["spread"], kb[k]["spread"]
        if sa is None or sb is None:
            continue
        rows.append({"key": k, f"{a}_spread": sa, f"{b}_spread": sb,
                     "ratio": (sb / sa) if sa else None})
    rows.sort(key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0.0)))
    return rows


class Recorder:
    """Append-only run records, flushed and fsynced per run.

    Per-run flush is not caution, it is a bug report from issue #6:
    `--calibrate` wrote only at session end, a run hung at 90%, and
    twelve minutes of measurement yielded nothing at all. A run that
    completed is evidence whether or not the ones after it do, and a
    harness that loses it has thrown away bench time nobody can get
    back.

    JSON Lines rather than one document, because that is the format an
    append survives a kill in.
    """

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)

    def add(self, record):
        with open(self.path, "a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return record


def load(path):
    """Read back what a Recorder wrote.

    A truncated last line - the kill the flush exists to survive - is
    skipped rather than raising. Losing the run that was being written
    is the cost of the crash; losing the six before it would be the cost
    of this reader.
    """
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out
