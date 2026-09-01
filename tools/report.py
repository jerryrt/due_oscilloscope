#!/usr/bin/env python3
"""Generate the figure tables that documentation would otherwise hand-copy.

Issue #6, item 7. The problem this solves is not typing: it is that a
number copied into prose stops being connected to the measurement that
produced it, and then outlives it. This project has retracted a noise
floor, a settling tail and a transport figure for exactly that reason,
and `docs/status.md` opens with an audit of which of its own figures
predate which fix.

So the contract is narrow and worth stating:

**This does not generate documents.** It generates the *tables* whose
every cell comes from a recorded measurement, and writes them into
marked regions of a document that is otherwise prose. Argument, caveat
and retraction stay hand-written, because they are the part a generator
cannot check and the part that carries the meaning.

**A region is machine-owned or it is not.** Between the markers nothing
survives regeneration, so nothing hand-written may be put there. The
markers name the table, so a reader knows which half they are in.

    <!-- generated: rates -->
    ...table...
    <!-- end generated -->

**Drift is a test failure, not a chore.** `--check` regenerates and
compares without writing, so a figure that moved in `tests/baseline.json`
and was not carried into the document fails rather than waiting to be
noticed. That is the whole point: the reason to generate a table nobody
minds typing is to make the copy verifiable.

Sources, each named in the output so a cell can be chased:

    tests/baseline.json   what --calibrate records, and what the suite
                          asserts against
    calibration.json      dac_mv and adc_transfer, moved out of the test
                          fixture in 9cc92d1 because five non-test
                          modules were reaching into it

    python3 tools/report.py                 # print the tables
    python3 tools/report.py --write         # update docs/status.md
    python3 tools/report.py --check         # fail if the document drifted
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(HERE, "tests", "baseline.json")
CALIBRATION = os.path.join(HERE, "calibration.json")
STATUS = os.path.join(HERE, "docs", "status.md")

BEGIN = "<!-- generated: %s -->"
END = "<!-- end generated -->"


def _load(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _rows(table):
    """Markdown, with the header taken from the first row's keys."""
    if not table:
        return "*(no rows)*"
    cols = list(table[0])
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for r in table:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def t_rates(b, c):
    """Trigger rates and the RC values behind them.

    RC rather than the frequency is the primary column because the device
    divides an integer: the frequency is `(SystemCoreClock/2)/RC` rounded
    down, so quoting it alone loses the value that produced it. That is
    the same recovery `host/eqtime.py` depends on.
    """
    rc, hz, clk = b["rc"], b["rates_hz"], b["clock"]
    rows = [
        {"what": "two channels, per channel", "RC": rc["two_ch_floor"],
         "sps": "{:,}".format(hz["two_ch_per_channel"])},
        {"what": "two channels, aggregate", "RC": rc["two_ch_floor"],
         "sps": "{:,}".format(hz["two_ch_aggregate"])},
        {"what": "one channel", "RC": rc["one_ch_floor"],
         "sps": "{:,}".format(hz["one_ch"])},
        {"what": "DAC top", "RC": rc["dac_top"],
         "sps": "{:,}".format(hz["dac_top"])},
    ]
    # All three are nominal: the board derives them from registers and
    # has never measured them (issue #52). Said here because this table
    # is read as a specification.
    tail = ("\n\nTC clock {:,} Hz, MCK {:,} Hz, ADC clock {:,} Hz"
            " (nominal, register-derived)."
            .format(clk["tc_clock_hz"], clk["mck_hz"], clk["adc_clock_hz"]))
    return _rows(rows) + tail


def t_transport(b, c):
    """Measured throughput against the floor the suite asserts.

    Both columns, because a measured figure with no floor beside it does
    not say whether it is a result or a regression - and the floor alone
    does not say how much air there is.
    """
    meas, floor = b["transport_measured_mbs"], b["transport_min_mbs"]
    rows = []
    for k in sorted(set(meas) | set(floor)):
        if k.startswith("_"):
            continue
        m, f = meas.get(k), floor.get(k)
        # A measured entry is a [low, high] observed range, not a point,
        # and the margin is taken from the LOW end. The question a floor
        # answers is whether the worst run cleared it; a margin computed
        # from the best one would report pass while the suite reports
        # fail. See issue #6 - the IN direction spreads ~40%, which is
        # what made a single reading look quotable.
        lo = m[0] if isinstance(m, list) and m else m
        shown = ("-" if m is None
                 else "{}-{}".format(m[0], m[1]) if isinstance(m, list)
                 else str(m))
        margin = "-"
        if isinstance(lo, (int, float)) and isinstance(f, (int, float)) and f:
            margin = "{:.2f}x".format(lo / f)
        rows.append({"direction": k,
                     "measured MB/s": shown,
                     "floor MB/s": "-" if f is None else str(f),
                     "worst-case margin": margin})
    return _rows(rows)


def t_frame(b, c):
    f, a = b["frame"], b["amplitude"]
    rows = [
        {"field": "frame header", "value": "{} bytes".format(f["header_bytes"])},
        {"field": "samples per frame", "value": f["samples"]},
        {"field": "frame size", "value": "{} bytes".format(f["bytes"])},
        {"field": "full scale", "value": "{} codes".format(a["full_scale_codes"])},
        {"field": "window floor",
         "value": "{} codes".format(a["window_floor_codes"])},
        {"field": "window fraction", "value": a["window_fraction"]},
    ]
    return _rows(rows)


def t_calibration(b, c):
    """The two keys that left the test fixture in 9cc92d1.

    Named here because five non-test modules used to reach into
    `tests/baseline.json` for them, and a reader of a figure derived from
    them should be able to find where they now live.
    """
    # Scalars only. The file carries long _comment arrays recording how
    # each number was arrived at, and those are the argument rather than
    # the figure - they belong where they are and not in a table.
    rows = []
    for group, body in sorted(c.items()):
        if group.startswith("_") or not isinstance(body, dict):
            continue
        for k, v in sorted(body.items()):
            if k.startswith("_") or isinstance(v, (list, dict)):
                continue
            rows.append({"group": group, "key": k, "value": v})
    return (_rows(rows)
            + "\n\nFrom `calibration.json`, via `host/calibration.py`. The"
            + " `_comment` blocks there record how each figure was arrived"
            + " at and are deliberately not reproduced: they are the"
            + " argument, not the number.")


TABLES = {
    "rates": t_rates,
    "transport": t_transport,
    "frame": t_frame,
    "calibration": t_calibration,
}


def render(name, b, c):
    return TABLES[name](b, c)


def apply_to(text, b, c):
    """Replace every marked region. Unknown names are left alone.

    Left alone rather than errored: a document may mark a region this
    version does not know how to fill, and destroying it would be worse
    than leaving it stale for one release.
    """
    missing = []
    for name in sorted(TABLES):
        begin = BEGIN % name
        if begin not in text:
            missing.append(name)
            continue
        pat = re.compile(re.escape(begin) + ".*?" + re.escape(END), re.DOTALL)
        text = pat.sub(lambda _m, n=name: (BEGIN % n) + "\n"
                       + render(n, b, c) + "\n" + END, text)
    return text, missing


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="update the document in place")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the document is not what this "
                         "would generate")
    ap.add_argument("--doc", default=STATUS)
    args = ap.parse_args()

    b, c = _load(BASELINE), _load(CALIBRATION)

    if not (args.write or args.check):
        for name in sorted(TABLES):
            print("## %s\n\n%s\n" % (name, render(name, b, c)))
        return 0

    with io.open(args.doc, encoding="utf-8") as fh:
        text = fh.read()
    new, missing = apply_to(text, b, c)

    if args.check:
        if new != text:
            print("docs drifted from tests/baseline.json - run "
                  "`python3 tools/report.py --write`", file=sys.stderr)
            return 1
        if missing:
            print("no region for: %s (nothing to check)" % ", ".join(missing),
                  file=sys.stderr)
        print("generated regions match the recorded figures")
        return 0

    with io.open(args.doc, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    print("wrote %s" % args.doc)
    if missing:
        print("no region for: %s" % ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
