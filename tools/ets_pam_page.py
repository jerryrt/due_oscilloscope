#!/usr/bin/env python3
"""Draw a PAM-N eye from an `ets_pam.py` eye file as a standalone page.

    ets_pam_page.py pam4_eye.json --out pam4.html --title "PAM4, montreal5"

The input is the eye document `host/etspam.py` writes (`ets_pam.py ... --eye-out`):
a density of every sample placed by the fitted clock, the levels and eyes, the
gates and a histogram of the levels at the symbol centre. The page draws the
`N - 1` eyes with the level means and each eye's height marked, the level
histogram on the same vertical axis, a zoom on the middle eye, and tables of the
gates, levels and eyes. It is the PRBS eye page (`ets_eye_page.py`) made for
several eyes, and like it needs no server. Stdlib only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "ets_pam_template.html")
PLACEHOLDER = "/*DATA*/null"

#: What an eye document must carry for the page to draw it.
REQUIRED = ("cells", "nx", "k", "tick_ns", "ui_ticks", "ymin_code", "ymax_code",
            "adc_mv_per_code", "levels", "eyes", "gates", "centre_hist", "pattern",
            "residual_codes", "samples", "rc_dac", "rc_adc", "pam")


def load(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    eye = doc.get("eye", doc)
    missing = [k for k in REQUIRED if k not in eye]
    if missing:
        raise SystemExit("%s is not a PAM eye document from `ets_pam.py`: missing %s"
                         % (path, ", ".join(missing)))
    return doc


def build(doc, title=None, lede=None):
    """The page text for one loaded eye document."""
    eye = doc.get("eye", doc)
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    if text.count(PLACEHOLDER) != 1:
        raise SystemExit("the template must hold the data placeholder exactly once")
    data = {"title": title or ("PAM%d Eye" % eye["pam"]), "lede": lede or "",
            "eye": eye, "provenance": doc.get("provenance", {})}
    text = text.replace("<title>PAM Eye</title>", "<title>PAM%d Eye</title>" % eye["pam"], 1)
    return text.replace(PLACEHOLDER, json.dumps(data, separators=(",", ":")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("eye", help="the JSON `ets_pam.py` writes with --eye-out")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--lede", help="a sentence under the title")
    a = ap.parse_args()
    page = build(load(a.eye), a.title, a.lede)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print("wrote %s (%d bytes)" % (a.out, len(page)))


if __name__ == "__main__":
    sys.exit(main())
