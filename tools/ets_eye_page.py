#!/usr/bin/env python3
"""Draw one or two PRBS eyes from `ets_cross.py eye` files as a standalone page.

    ets_eye_page.py same_board.json two_boards.json --out eyes.html
    ets_eye_page.py eye.json --title "DUT2 at 1.55 Msym/s" --out eye.html

Each input is the JSON `ets_cross.py eye` writes: a two-symbol density map
of every sample, placed by the fitted clock relation, and the folded waveform.
The page draws both on the same axes, zooms on the crossing with the folded
line through the samples, tabulates what each capture can claim, and prints
where each came from (the `provenance` block of the file). It needs no
server: the data is inside the page, and fonts fall back if the Google Fonts
link is blocked. Stdlib only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "ets_eye_template.html")
PLACEHOLDER = "/*DATA*/null"

#: What an eye file must carry for the page to draw it.
REQUIRED = ("dens", "nx", "ny", "ylo", "yb", "k", "tick_ns", "ui_ticks", "b0_ticks",
            "curve_mv", "curve_k", "bits", "samples", "rc_dac", "rc_adc")


def load(path):
    with open(path, encoding="utf-8") as f:
        eye = json.load(f)
    missing = [k for k in REQUIRED if k not in eye]
    if missing:
        raise SystemExit("%s is not an eye file from `ets_cross.py eye`: missing %s"
                         % (path, ", ".join(missing)))
    return eye


def build(eyes, title=None, lede=None, labels=None):
    """The page text for `eyes`, a list of one or two loaded eye files."""
    if not 1 <= len(eyes) <= 2:
        raise ValueError("the page draws one or two eyes, got %d" % len(eyes))
    for i, label in enumerate(labels or []):
        if label:
            eyes[i]["label"] = label
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    if text.count(PLACEHOLDER) != 1:
        raise SystemExit("the template must hold the data placeholder exactly once")
    data = {"title": title or ("PRBS Eye" if len(eyes) == 1 else "PRBS Eyes"),
            "lede": lede or "", "eyes": eyes}
    return text.replace(PLACEHOLDER, json.dumps(data, separators=(",", ":")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("eyes", nargs="+", help="one or two JSON files from `ets_cross.py eye`")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--lede", help="a sentence under the title")
    ap.add_argument("--label", action="append", default=[],
                    help="a name for each eye, in order (default: the file's own label)")
    a = ap.parse_args()
    page = build([load(p) for p in a.eyes], a.title, a.lede, a.label)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote %s (%d bytes, %d eye%s)" % (a.out, len(page), len(a.eyes),
                                            "" if len(a.eyes) == 1 else "s"))


if __name__ == "__main__":
    sys.exit(main())
