#!/usr/bin/env python3
"""Run the pinned issue #5 arm, or refuse before touching the board.

    .venv/bin/python tools/issue5_campaign.py --check     # preflight only
    .venv/bin/python tools/issue5_campaign.py

One command, identical on all three benches. It does not capture
anything itself: it checks that this bench is in the pinned
configuration and then hands off to `tools/issue5_sites.py`, which owns
the capture loop. **Two capture loops would be two homes for one
protocol**, which is the failure `CLAUDE.md` carves the shared-source
rule around, and a campaign whose three arms drifted apart would be
three near-misses of one experiment rather than one experiment.

## What is pinned, and why each item is

| pinned | why |
|---|---|
| firmware commit and image | #5's site set and severity are drawn by the binary. Two benches on two images are not two benches |
| container build, Track B | three host toolchains are two code generators (#78) |
| preset `=200000,200000M` | bare `M` leaves whatever the board booted with |
| the FWS plan, counterbalanced | a wait state redraws the site set as thoroughly as a compiler does, and a drift across the session would otherwise masquerade as the effect |
| n per wait state | a Jaccard's ceiling moves with sample size, so a bench at a different n cannot be read against the others |
| run 1 discarded by index | first-run outliers on all three benches, and a filter on what run 1 *does wrong* has already missed one |
| the analog path, declared | `bench.json` describes what is wired and, until this campaign, nothing about what is clipped on or what the wire is made of. Undeclared probes moved every severity figure on one bench |

## What is new in this arm, and why the old rows cannot be reused

Rows written before 2026-09-13 stored each run's six strongest sites and
nothing else. At FWS 6 that truncated **every row of every bench**: the
six recorded sites hold 40-55% of the severity and the rest was dropped
with nothing in the row to say so. The site set the campaign published
is the visible half of a larger set, and no re-analysis can recover the
other half from what was stored.

So this arm stores the whole 256-point profile and every site, and the
preflight refuses to run an instrument that does not - `--check` fails
on a tree whose `issue5_sites.py` still slices. That is what lets the
frequency-domain reading (`tools/issue5_spectrum.py`) run on the signal
rather than on six impulses.

## The pre-registered reading

Written before any row of this arm exists, so it can be wrong.

1. **The comb.** At FWS 6 the six recorded sites on every bench are
   12, 33, 117, 138, 159 and 180 - every one congruent to 12 modulo 21,
   resultant R = 1.000, and **0 of 20,000 uniform draws** reach a comb
   that tight at a period that long. If the comb is the structure and
   the old records were merely truncated, the dropped sites are at the
   unoccupied lattice points: **8, 54, 75, 96, 201, 222 and 243.**
   A dropped site anywhere else falsifies it.
2. **What it would mean.** A disturbance periodic in wall time smears
   away under a fold over hundreds of cycles. A comb that survives the
   fold is locked to the table index - and since 21 does not divide 256,
   a free-running period-21 disturbance would rotate by 4 positions
   every wrap and smear too. Surviving therefore also implies it is
   **re-synchronised at the table wrap**. No candidate mechanism is
   named here; that is what the profiles are for.
3. **What stays unexplained either way.** The severity spread across
   benches (342.7-445.5 on the old rows) is board, jumper material or
   USB IN DMA timing, and nothing in this arm separates them. This
   campaign is not that experiment.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

#: The freeze. A records or docs commit moves every artifact hash, so
#: this is the commit the board's image was BUILT at, not the tree the
#: instrument runs from.
PINNED_FW = "1b2a2d1"
PINNED_TRACK = "b"
PINNED_BUILD_ENV = "container"
PINNED_PRESET = "=200000,200000M"

#: 25 runs per wait state, counterbalanced, run 1 discarded by index -
#: leaving 24 analysed, which is the n every published ceiling was taken
#: at. The old arm took 72 runs and analysed 72; its first run was an
#: outlier in every bench's record and was carried into the figures.
PINNED_PLAN = "4x13,5x12,6x12,6x12,5x12,4x12"
PINNED_RUNS = 73
PINNED_SECONDS = 3.0
DISCARD_RUNS = (1,)

#: Fields `bench.json` must carry before this arm may run. `probes` and
#: `jumpers` are new: the first because undeclared scope probes moved
#: every severity figure on mac-bench while `wiring_source` still read
#: `declared`, the second because the one declared analog difference
#: between the benches is the loopback wire's metal and it reached the
#: record only as prose on an issue.
REQUIRED_BENCH_FIELDS = ("bench", "wiring", "wiring_since", "probes",
                         "jumpers")


def fail(msg):
    print(f"REFUSING: {msg}", file=sys.stderr)
    return 2


def check_instrument():
    """The capture tool must store whole profiles and every site.

    Checked by reading what a row would contain, not by grepping the
    source: a comment mentioning `profile` would satisfy a grep, and a
    check that passes because it cannot fail is worse than none.
    """
    import issue5_sites  # noqa: F401  (import path check)
    src = open(os.path.join(ROOT, "tools", "issue5_sites.py")).read()
    i = src.find('row = {"run"')
    if i < 0:
        return "issue5_sites.py: cannot find the row it writes"
    row = src[i:src.find("rows.append", i)]
    if '"profile"' not in row or '"n_sites"' not in row:
        return ("issue5_sites.py does not store `profile` and `n_sites`. "
                "This arm exists because the truncated rows cannot answer "
                "the question; running it with the old instrument would "
                "reproduce exactly the gap it is meant to close.")
    if "found[:6]" in row or "found[:" in row:
        return ("issue5_sites.py still slices its site list. Every FWS 6 "
                "row of the previous arm hit that cap.")
    return None


def check_bench():
    path = os.path.join(ROOT, "bench.json")
    if not os.path.exists(path):
        return (f"no {path}. An undeclared bench records the RETIRED DSO "
                f"wiring on every row it writes.")
    with open(path) as fh:
        b = json.load(fh)
    missing = [k for k in REQUIRED_BENCH_FIELDS if not b.get(k)]
    if missing:
        return (f"bench.json is missing {', '.join(missing)}. "
                f"`probes` is what mac-bench's arm lacked while reading "
                f"`declared`; `jumpers` is the one analog difference "
                f"between the benches that is known and was never in a "
                f"record. Declare them from the hardware in front of you, "
                f"not from this file.")
    return None


def check_board(quiet=False):
    """Ask the board what it is. Never assume from a page."""
    import measure
    import provenance
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        p = provenance.run_fields(board)
    finally:
        board.close()
    if not quiet:
        print("  board: " + ", ".join(f"{k}={v}" for k, v in p.items()))
    bad = []
    if (p.get("fw_repo_rev") or "")[:len(PINNED_FW)] != PINNED_FW:
        bad.append(f"fw_repo_rev {p.get('fw_repo_rev')!r}, want {PINNED_FW}")
    if (p.get("track") or "").lower() != PINNED_TRACK:
        bad.append(f"track {p.get('track')!r}, want {PINNED_TRACK}")
    if p.get("fw_build_env") != PINNED_BUILD_ENV:
        bad.append(f"fw_build_env {p.get('fw_build_env')!r}, "
                   f"want {PINNED_BUILD_ENV}")
    if p.get("fw_provenance") != "matched by commit":
        bad.append(f"fw_provenance {p.get('fw_provenance')!r}, want "
                   f"'matched by commit' - the board is unattributable")
    return "; ".join(bad) or None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="run the preflight and stop. Does open the board, "
                         "because three of the four checks are questions "
                         "only the board can answer")
    ap.add_argument("--no-board", action="store_true",
                    help="preflight the checks that need no board. Useful "
                         "on a bench with no hardware attached")
    ap.add_argument("--out", default=None,
                    help="where rows go. Defaults to a scratch path beside "
                         "the repo, NOT records/ - a new file in the tree "
                         "dirties `repo_rev` mid-run, so rows are copied in "
                         "afterwards")
    args = ap.parse_args()

    print("preflight")
    for name, err in (("instrument", check_instrument()),
                      ("bench.json", check_bench())):
        if err:
            return fail(err)
        print(f"  {name}: ok")
    if not args.no_board:
        err = check_board()
        if err:
            return fail(err)
        print("  board: ok")
    else:
        print("  board: SKIPPED (--no-board) - this is not a preflight pass")

    if args.check:
        print("\npreflight only; nothing captured")
        return 0

    with open(os.path.join(ROOT, "bench.json")) as fh:
        bench = json.load(fh)["bench"]
    out = args.out or os.path.join(
        os.path.dirname(ROOT), f"issue5-campaign-{bench}.jsonl")
    if os.path.exists(out):
        return fail(f"{out} exists. This arm is one session; appending to "
                    f"an existing file would merge two, and the "
                    f"block-to-block ceiling of a merged file means "
                    f"nothing. Move it aside.")

    cmd = [sys.executable, os.path.join(ROOT, "tools", "issue5_sites.py"),
           "-n", str(PINNED_RUNS), "-s", str(PINNED_SECONDS),
           "--preset", PINNED_PRESET, "--fws-plan", PINNED_PLAN,
           "--bench", bench, "--json", out]
    print("\n" + " ".join(cmd) + "\n", flush=True)
    rc = subprocess.call(cmd)
    if rc:
        return rc
    print(f"\nrows in {out}")
    print(f"DISCARD run {DISCARD_RUNS[0]} BY INDEX before analysing - "
          f"every bench's first run has been an outlier, and a filter on "
          f"what it does wrong has already missed one.")
    print(f"Then copy it into records/issue5-campaign-{bench}.jsonl and "
          f"commit, so the analysis runs from a clean tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
